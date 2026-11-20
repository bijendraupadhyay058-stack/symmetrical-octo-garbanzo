"""Follow-up work from the Return comparison, in one click each:

* **Supplier letters** – for the months where GSTR-3B claims more ITC than GSTR-2B shows, letters to the suppliers
  whose bills are not in GSTR-2B (from the purchase vs GSTR-2B reconciliation of those months).
* **Reply draft** – DRC-01B (GSTR-1 tax above GSTR-3B, rule 88C) or DRC-01C (GSTR-3B ITC above GSTR-2B, rule 88D):
  the intimation is entered in the GST notices register and the Word reply is drafted from the data.
* **DRC-03 working** – the difference by tax head with interest under section 50 up to the chosen payment date,
  ready to enter in DRC-03 on the portal (the program never pays or files anything).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO
from ..db.database import Database
from .common import ServiceError
from .return_compare import TOLERANCE, ReturnCompareService

FORM_OF = {"1_3B": "DRC-01B", "3B_2B": "DRC-01C"}
EXPOSURE_OF = {"1_3B": "SHORT_PAYMENT", "3B_2B": "EXCESS_ITC"}
HEADS = ("igst", "cgst", "sgst", "cess")
CAUSE = {"1_3B": "Tax short paid – GSTR-1 liability above GSTR-3B (rule 88C / DRC-01B)",
         "3B_2B": "ITC availed in GSTR-3B above GSTR-2B (rule 88D / DRC-01C)"}


@dataclass
class Drc03Row:
    period: str
    head: str
    tax: Decimal
    days: int
    interest: Decimal
    basis: str


@dataclass
class Drc03Working:
    kind: str
    client: str
    gstin: str
    fy: str
    pay_on: date
    rows: list[Drc03Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def cause(self) -> str:
        return CAUSE[self.kind]

    def by_head(self) -> dict[str, dict[str, Decimal]]:
        out = {h: {"tax": ZERO, "interest": ZERO} for h in HEADS}
        for r in self.rows:
            out[r.head]["tax"] += r.tax
            out[r.head]["interest"] += r.interest
        return out

    @property
    def total(self) -> Decimal:
        return sum((r.tax + r.interest for r in self.rows), ZERO)


class CompareActionService:
    def __init__(self, db: Database):
        self.db = db
        self.compare = ReturnCompareService(db)

    def excess_months(self, client_id: int, fy: str, kind: str) -> list[str]:
        """Months where the left return is above the right one (GSTR-1 above 3B / 3B ITC above 2B)."""
        if kind not in FORM_OF:
            raise ServiceError("Letters and replies are prepared from GSTR-1 vs 3B or GSTR-3B vs 2B")
        comp = self.compare.compare(kind, client_id, fy)
        return [m for r in comp.rows if r.diff is not None and r.diff.total > TOLERANCE for m in r.months]

    # ------------------------------------------------------------ letters
    def supplier_letters(self, client_id: int, fy: str, out_dir: str | Path, user: str | None = None,
                         signatory: str = "", formats: tuple[str, ...] = ("docx", "pdf")) -> tuple[int, list[Path]]:
        """Letters for the months with excess ITC; returns (number of letters, files)."""
        from .itc import ItcService
        from .letters import LetterService

        months = self.excess_months(client_id, fy, "3B_2B")
        if not months:
            raise ServiceError(f"GSTR-3B does not claim more ITC than GSTR-2B in any month of {fy} – no letters "
                               "needed from this comparison")
        with self.db.session() as s:
            runs = ItcService(self.db)._latest_month_runs(s, client_id, months)
        if not runs:
            raise ServiceError("Reconcile the purchase register with GSTR-2B for " + ", ".join(months)
                               + " first (Reconcile page) – the letters list the bills found missing there")
        n, files = 0, []
        for m in sorted(runs):
            for _letter, paths in LetterService(self.db).generate(runs[m], out_dir, formats=formats,
                                                                  signatory=signatory, user=user):
                n += 1
                files += paths
        if not n:
            raise ServiceError("The reconciliations of " + ", ".join(sorted(runs)) + " have no bills for the "
                               "suppliers to correct – the difference is on your side (check the ITC claimed)")
        return n, files

    # ------------------------------------------------------------ replies
    def reply_draft(self, client_id: int, fy: str, kind: str, out_dir: str | Path, by, reference: str = "",
                    notice_date: date | None = None, officer: str = "", signatory: str = "",
                    reply_due: date | None = None) -> tuple[Path, int]:
        """Enter the DRC-01B / DRC-01C intimation in the notices register and draft its reply (Word)."""
        from .notices import NoticeService

        months = self.excess_months(client_id, fy, kind)
        if not months:
            a, b = {"1_3B": ("GSTR-1", "GSTR-3B"), "3B_2B": ("GSTR-3B", "GSTR-2B")}[kind]
            raise ServiceError(f"{a} is not above {b} in any month of {fy} – there is nothing for a "
                               f"{FORM_OF[kind]} reply to explain")
        comp = self.compare.compare(kind, client_id, fy)
        amount = sum((r.diff.total for r in comp.rows if r.diff is not None and r.diff.total > TOLERANCE), ZERO)
        svc = NoticeService(self.db)
        values = {"form": FORM_OF[kind], "reference": reference.strip()[:80], "notice_date": notice_date or date.today(),
                  "period_from": min(months), "period_to": max(months), "amount": amount, "officer": officer.strip(),
                  "remarks": "Entered from Return comparison – check the reference and date with the intimation"}
        if reply_due is not None:
            values["reply_due"] = reply_due
        nid = svc.add(client_id, by, **values)
        path, _draft = svc.draft(nid, out_dir, signatory=signatory, user=getattr(by, "username", None))
        return path, nid

    # ------------------------------------------------------------- DRC-03
    def drc03(self, client_id: int, fy: str, kind: str, pay_on: date | None = None) -> Drc03Working:
        from .interest import InterestService

        if kind not in EXPOSURE_OF:
            raise ServiceError("A DRC-03 working is prepared from GSTR-1 vs 3B or GSTR-3B vs 2B")
        pay_on = pay_on or date.today()
        comp = self.compare.compare(kind, client_id, fy)
        w = InterestService(self.db).working(client_id, fy, pay_on)
        out = Drc03Working(kind, comp.client, comp.gstin, fy, pay_on)
        for e in w.exposures:
            if e.kind != EXPOSURE_OF[kind] or e.status != "OPEN":
                continue
            out.rows.append(Drc03Row(e.period, e.head, e.amount, e.days, e.interest, e.basis))
        out.rows.sort(key=lambda r: (r.period, HEADS.index(r.head)))
        settled = [e for e in w.exposures if e.kind == EXPOSURE_OF[kind] and e.status != "OPEN"]
        if settled:
            out.notes.append(f"{len({e.period for e in settled})} month(s) already recorded as paid / not payable "
                             "(GSTR-3B & annual → Interest & late fee) are left out.")
        if kind == "3B_2B":
            out.notes.append("Worked on net ITC – GSTR-3B 4(C) against GSTR-2B – so ITC already reversed in 4(B) reduces "
                             "it; it can be lower than the 4(A) difference on the comparison screen.")
            out.notes.append("Excess ITC can also be reversed in the next GSTR-3B (Table 4(B)(2)); interest is an "
                             "UPPER LIMIT – it runs only on the part of the ITC actually used (rule 88B(3)).")
        out.notes += [n for n in w.notes if "not imported" in n or "not recorded" in n]
        if not out.rows:
            out.notes.insert(0, "Nothing to pay: no open difference for the months with both returns imported.")
        return out

    def export_drc03(self, w: Drc03Working, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "DRC-03 working"
        ws.append([f"{w.client} ({w.gstin}) – DRC-03 working, FY {w.fy}"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([f"Cause: {w.cause}"])
        ws.append([f"Interest at 18% p.a. under section 50 up to {w.pay_on:%d-%m-%Y} (the date of payment)"])
        ws.append([])
        head = ["Tax head", "Tax", "Interest", "Total"]
        ws.append(head)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
        names = {"igst": "Integrated tax (IGST)", "cgst": "Central tax (CGST)", "sgst": "State/UT tax (SGST)",
                 "cess": "Cess"}
        for h, v in w.by_head().items():
            ws.append([names[h], float(v["tax"]), float(v["interest"]), float(v["tax"] + v["interest"])])
        ws.append(["Total", float(sum((r.tax for r in w.rows), ZERO)), float(sum((r.interest for r in w.rows), ZERO)),
                   float(w.total)])
        ws[ws.max_row][0].font = Font(bold=True)
        ws.append([])
        ws.append(["Month", "Head", "Tax", "Days", "Interest", "Basis"])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        for r in w.rows:
            ws.append([r.period, r.head.upper(), float(r.tax), r.days, float(r.interest), r.basis])
        for row in ws.iter_rows(min_row=6, min_col=2, max_col=5):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##,##0.00"
        ws.append([])
        for n in w.notes + ["Pay on the portal: Services → User Services → My Applications → Intimation of Voluntary "
                            "Payment – DRC-03 (or from the DRC-01B / DRC-01C reply). FIN TAX PRO does not pay or file."]:
            ws.append([n])
        ws.column_dimensions["A"].width = 26
        for col in "BCDE":
            ws.column_dimensions[col].width = 15
        ws.column_dimensions["F"].width = 90
        path = Path(path)
        wb.save(path)
        return path
