"""Return preparation: GSTR-1, GSTR-3B, GSTR-9 and GSTR-9C in one place.

For each return: a readiness checklist (is the data there and reconciled?), the figures of the return, the files
to file it, and a "final" mark that remembers the figures – if the data changes afterwards the return shows as
changed and must be prepared again.

What the GST portal accepts:
* GSTR-1 – the JSON is uploaded on the portal (Returns Dashboard → GSTR-1 → Prepare Offline → Upload) or opened in
  the GST Offline Tool;
* GSTR-9 – the JSON is opened in the GSTR-9 offline tool, which validates it and generates the file to upload;
* GSTR-9C – prepared in the GSTR-9C offline tool; the Excel here follows its tables, for entering / copying;
* GSTR-3B – the portal has no file upload for GSTR-3B: the filing sheet lists every figure in the order of the
  portal's screens, to enter and compare with the system-calculated values.
Nothing is filed or uploaded by the program.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import AppSetting, Client, Invoice, ReconRun
from ..importers.parsing import parse_period
from ..itc.annual import fy_months
from .common import ServiceError, audit

RETURNS = {"GSTR1": "GSTR-1", "GSTR3B": "GSTR-3B", "GSTR9": "GSTR-9", "GSTR9C": "GSTR-9C"}
HOW = {
    "GSTR1": "Upload the JSON on the GST portal: Returns Dashboard → choose the period → GSTR-1 → Prepare Offline → "
             "Upload → choose the file. Check the summary on the portal, then file with DSC / EVC.",
    "GSTR3B": "The portal has no file upload for GSTR-3B. Open GSTR-3B on the portal and enter the figures from the "
              "filing sheet table by table (compare with the system-calculated values), then pay and file.",
    "GSTR9": "Open the JSON in the GSTR-9 offline tool (Open → JSON), check every table – the mapping file lists what "
             "to enter there – generate the JSON in the tool and upload it on the portal (GSTR-9 → Prepare Offline).",
    "GSTR9C": "Enter the figures in the GSTR-9C offline tool from the Excel (it follows the tool's tables), add the "
              "reasons for differences, generate the JSON and upload it with the GSTR-9C on the portal.",
}
OK, WARN, MISSING = "ok", "warn", "missing"


@dataclass
class CheckItem:
    status: str  # ok / warn / missing
    text: str


@dataclass
class Prep:
    kind: str
    period: str  # YYYY-MM (GSTR-1 / 3B) or the FY (GSTR-9 / 9C)
    checklist: list[CheckItem] = field(default_factory=list)
    figures: list[tuple[str, Decimal | None, Decimal | None]] = field(default_factory=list)  # label, value, tax
    notes: list[str] = field(default_factory=list)
    final: dict | None = None
    changed_since_final: bool = False

    @property
    def ready(self) -> bool:
        return not any(c.status == MISSING for c in self.checklist)

    def fingerprint(self) -> str:
        data = [(lbl, str(v), str(t)) for lbl, v, t in self.figures]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()


class ReturnPrepService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ helpers
    def _client(self, client_id: int) -> Client:
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            s.expunge(c)
            return c

    def _counts(self, client_id: int, months: list[str]) -> dict[tuple[str, str], int]:
        with self.db.session() as s:
            return {(src, p): n for src, p, n in s.execute(
                select(Invoice.source_type, Invoice.period, func.count()).where(
                    Invoice.client_id == client_id, Invoice.period.in_(months))
                .group_by(Invoice.source_type, Invoice.period))}

    def _run(self, client_id: int, comparison: str, month: str) -> ReconRun | None:
        with self.db.session() as s:
            return s.scalar(select(ReconRun).where(ReconRun.client_id == client_id, ReconRun.comparison == comparison,
                                                   ReconRun.period_from == month, ReconRun.period_to == month)
                            .order_by(ReconRun.id.desc()).limit(1))

    @staticmethod
    def _key(kind: str, client_id: int, period: str) -> str:
        return f"return_prep:{kind}:{client_id}:{period}"

    @staticmethod
    def gstr1_months(client: Client, period: str) -> list[str]:
        """A quarterly (QRMP) filer's GSTR-1 for the quarter's last month covers the whole quarter."""
        from ..compliance.calendar import is_quarterly, quarter_end
        from .composition import quarter_months

        return quarter_months(period) if is_quarterly(client.return_frequency or "") and quarter_end(period) \
            else [period]

    # ------------------------------------------------------------ prepare
    def prepare(self, kind: str, client_id: int, period: str) -> Prep:
        if kind not in RETURNS:
            raise ServiceError(f"Unknown return {kind}")
        client = self._client(client_id)
        if kind in ("GSTR1", "GSTR3B"):
            p = parse_period(period)
            if not p:
                raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        else:
            p = period
            if len(p) != 7 or p[4] != "-":
                raise ServiceError(f"Invalid financial year {period} – use e.g. 2025-26")
        prep = Prep(kind, p)
        getattr(self, f"_{kind.lower()}")(client, prep)
        saved = self.final_status(kind, client_id, p)
        if saved:
            prep.final = saved
            prep.changed_since_final = saved.get("fingerprint") != prep.fingerprint()
        return prep

    def _gstr1(self, client: Client, prep: Prep) -> None:
        from ..outward.gstr1_json import build_gstr1
        from .gstr1_prep import Gstr1PrepService
        from .tax_checks import TaxCheckService

        months = self.gstr1_months(client, prep.period)
        counts = self._counts(client.id, months)
        docs = []
        for m in months:
            n = counts.get(("SALES", m), 0)
            prep.checklist.append(CheckItem(OK if n else MISSING, f"Sales register {m}: " + (
                f"{n} document(s)" if n else "not imported")))
            if n:
                docs += Gstr1PrepService(self.db).docs(client.id, m)[0]
        if len(months) > 1:
            prep.notes.append(f"Quarterly return: covers {months[0]} to {months[-1]} (IFF invoices of the first two "
                              "months are already on the portal – remove them before uploading, or file only the "
                              "rest).")
        issues = TaxCheckService(self.db).check(client.id, months[0], months[-1], sources=("SALES",)) if docs else []
        prep.checklist.append(CheckItem(OK if not issues else WARN, "Tax type and rate checks: " + (
            "no problems" if not issues else f"{len(issues)} document(s) to check (Reconcile → Tax checks)")))
        for m in months:
            if counts.get(("EINV", m)):
                run = self._run(client.id, "SALES_VS_EINV", m)
                prep.checklist.append(CheckItem(OK if run else WARN, f"e-Invoices {m}: " + (
                    "reconciled with the sales register" if run else "imported but not reconciled")))
        if not docs:
            return
        draft = build_gstr1(client.gstin, months[-1], docs, client.state_code)
        left = [i for i in draft.issues if i.severity == "error"]
        prep.checklist.append(CheckItem(OK if not left else WARN, "Documents fitting GSTR-1: " + (
            "all" if not left else f"{len(left)} left out – see the issues list")))
        for sec, n in draft.counts.items():
            t = draft.totals.get(sec, {})
            tax = sum((t.get(k, ZERO) for k in ("igst", "cgst", "sgst", "cess")), ZERO)
            prep.figures.append((f"{sec.upper()} – {n} document(s)", t.get("taxable", ZERO), tax))
        self._gstr1_draft = draft

    def _gstr3b(self, client: Client, prep: Prep) -> None:
        from .gstr3b_draft import Gstr3bDraftService

        m = prep.period
        counts = self._counts(client.id, [m])
        for src, label, empty in (("SALES", "Sales register", "not imported – Table 3.1 will be nil"),
                                  ("BOOKS", "Purchase register", "not imported"), ("GSTR2B", "GSTR-2B", "not imported")):
            n = counts.get((src, m), 0)
            prep.checklist.append(CheckItem(OK if n else WARN, f"{label}: " + (f"{n} document(s)" if n else empty)))
        if counts.get(("BOOKS", m)) and counts.get(("GSTR2B", m)):
            run = self._run(client.id, "BOOKS_VS_GSTR2B", m)
            prep.checklist.append(CheckItem(OK if run else WARN, "Purchases reconciled with GSTR-2B: " + (
                f"run #{run.id}" if run else "not yet – ITC is then taken from GSTR-2B")))
        g1 = self.final_status("GSTR1", client.id, m)
        prep.checklist.append(CheckItem(OK if g1 else WARN, "GSTR-1 of the month: " + (
            "prepared and marked final" if g1 else "not marked final here (file GSTR-1 first)")))
        try:
            d = Gstr3bDraftService(self.db).draft(client.id, m)
        except ServiceError as exc:
            prep.checklist.append(CheckItem(MISSING, f"GSTR-3B draft: {exc}"))
            return
        from ..importers.gstr3b import TABLE4, TABLE31

        for code in TABLE31:
            v = d.t31[code]
            prep.figures.append((f"3.1{TABLE31[code][3:6]} {TABLE31[code][7:60]}", v.taxable, v.total))
        for code in TABLE4:
            v = d.t4[code]
            prep.figures.append((TABLE4[code][:70], None, v.total))
        prep.figures.append(("6.1 Tax to be paid in cash", None, d.setoff.total_cash))
        prep.notes += d.notes
        self._gstr3b_draft = d

    def _gstr9(self, client: Client, prep: Prep) -> None:
        from .gstr9 import Gstr9Service
        from .itc import ItcService

        months = fy_months(prep.period)
        counts = self._counts(client.id, months)
        from .gstr3b import Gstr3bService

        filed = Gstr3bService(self.db).values(client.id, months)
        no3b = [m for m in months if m not in filed]
        no1 = [m for m in months if not counts.get(("GSTR1", m)) and not counts.get(("SALES", m))]
        prep.checklist.append(CheckItem(OK if not no3b else (WARN if len(no3b) < 12 else MISSING),
                                        "GSTR-3B of all 12 months: " + ("imported" if not no3b else
                                                                        "missing " + ", ".join(no3b))))
        prep.checklist.append(CheckItem(OK if not no1 else WARN, "GSTR-1 / sales of all 12 months: " + (
            "imported" if not no1 else "missing " + ", ".join(no1))))
        try:
            t8 = ItcService(self.db).annual(client.id, prep.period)
            prep.checklist.append(CheckItem(OK, f"Table 8 (ITC as per GSTR-2B): worked out (8D {t8.d.total:,.2f})"))
        except ServiceError as exc:
            prep.checklist.append(CheckItem(WARN, f"Table 8: {exc}"))
        w = Gstr9Service(self.db).working(client.id, prep.period)
        for r in w.table4 + w.table5 + w.table6 + w.table7:
            if r.gstr1 is not None and (r.gstr1.taxable or r.gstr1.total):
                prep.figures.append((f"{r.code} {r.label[:60]}", r.gstr1.taxable, r.gstr1.total))
        for t in w.table9:
            prep.figures.append((f"9 Tax payable – {t.head.upper()}", None, t.payable))
        prep.notes += w.notes[:6]

    def _gstr9c(self, client: Client, prep: Prep) -> None:
        from ..gstr9.reconciliation_9c import TABLE5
        from .gstr9c import Gstr9cService

        g9 = self.final_status("GSTR9", client.id, prep.period)
        prep.checklist.append(CheckItem(OK if g9 else WARN, "GSTR-9: " + ("prepared and marked final" if g9 else
                                                                         "not marked final here")))
        svc = Gstr9cService(self.db)
        inputs = svc.inputs(client.id, prep.period)
        audited = [c for c, _l, _s in TABLE5 if c in inputs]
        prep.checklist.append(CheckItem(OK if "5A" in inputs else MISSING, "Turnover as per audited accounts (5A): " +
                                        ("entered" if "5A" in inputs else "not entered – GSTR-3B & annual → GSTR-9C")))
        prep.checklist.append(CheckItem(OK if "12A" in inputs else WARN, "ITC as per audited accounts (12A): " +
                                        ("entered" if "12A" in inputs else "not entered (books figure used)")))
        st = svc.statement(client.id, prep.period)
        unrec = [ln for ln in st.table5 + st.table7 + st.table12 if ln.code in ("5R", "7G", "12F") and ln.amount]
        missing_reason = [ln.code for ln in unrec if not st.reasons.get({"5R": "R6", "7G": "R8", "12F": "R13"}[ln.code])]
        prep.checklist.append(CheckItem(OK if not missing_reason else WARN, "Reasons for un-reconciled amounts: " + (
            "given" if not missing_reason else "missing for " + ", ".join(missing_reason))))
        for ln in st.table5 + st.table7 + st.table12:
            if ln.code in ("5A", "5P", "5Q", "5R", "7E", "7F", "7G", "12D", "12E", "12F"):
                prep.figures.append((f"{ln.code} {ln.label[:60]}", ln.amount, None))
        prep.notes.append(f"{len(audited)} audited figure(s) of Table 5 entered; the rest are defaults from the "
                          "registers.")
        prep.notes += st.notes[:5]

    # -------------------------------------------------------------- files
    def files(self, kind: str, client_id: int, period: str, out_dir: str | Path, user: str | None = None,
              firm: str = "") -> list[Path]:
        prep = self.prepare(kind, client_id, period)
        if not prep.ready:
            raise ServiceError("Not ready: " + "; ".join(c.text for c in prep.checklist if c.status == MISSING))
        client = self._client(client_id)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        made: list[Path] = []
        if kind == "GSTR1":
            from .gstr1_prep import Gstr1PrepService

            draft = self._gstr1_draft
            fp = prep.period.replace("-", "")
            made.append(Gstr1PrepService(self.db).save(client_id, draft, out / f"GSTR1_{client.gstin}_{fp[4:]}{fp[:4]}"
                                                                              f".json", user))
            if draft.issues:
                made.append(self._issues_xlsx(draft.issues, out / f"GSTR1_{client.gstin}_{prep.period}_issues.xlsx"))
        elif kind == "GSTR3B":
            from ..reports.gstr3b_draft_pdf import build_pdf

            d = self._gstr3b_draft
            made.append(self._filing_sheet_3b(client, d, out / f"GSTR3B_filing_sheet_{client.gstin}_{prep.period}.xlsx"))
            made.append(build_pdf(d, out / f"GSTR3B_{client.gstin}_{prep.period}.pdf", firm))
        elif kind == "GSTR9":
            from .gstr9 import Gstr9Service

            made += list(Gstr9Service(self.db).draft_json(client_id, prep.period, out, user=user))
        else:
            made.append(self._gstr9c_xlsx(client, prep.period, out / f"GSTR9C_{client.gstin}_FY{prep.period}.xlsx"))
        with self.db.session() as s:
            audit(s, "EXPORT", "return_prep", f"{kind}:{prep.period}", {"files": [p.name for p in made]}, user,
                  client_id)
        return made

    @staticmethod
    def _issues_xlsx(issues, path: Path) -> Path:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Issues"
        ws.append(["Severity", "Document", "Date", "Customer", "Issue"])
        for i in issues:
            d = i.doc
            ws.append([i.severity, d.number if d else "", d.date if d else None, (d.name or d.gstin) if d else "",
                       i.message])
        wb.save(path)
        return path

    @staticmethod
    def _filing_sheet_3b(client: Client, d, path: Path) -> Path:
        """Every GSTR-3B figure in the order of the portal's screens."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        from ..compliance.gstr3b_draft import HEADS
        from ..importers.gstr3b import TABLE4, TABLE31

        wb = Workbook()
        ws = wb.active
        ws.title = "GSTR-3B"
        ws.append([f"GSTR-3B filing sheet – {client.name} ({client.gstin}) – {d.period}"])
        ws["A1"].font = Font(bold=True, size=12)
        ws.append(["Enter these figures on the portal table by table and compare them with the system-calculated "
                   "values before filing."])
        head = Font(bold=True, color="FFFFFF")
        fill = PatternFill("solid", fgColor="1F3864")

        def title(text, cols):
            ws.append([])
            ws.append([text])
            ws.cell(ws.max_row, 1).font = Font(bold=True, size=11)
            ws.append(cols)
            for c in ws[ws.max_row]:
                c.font, c.fill = head, fill

        def f(v):
            return float(v) if v is not None else None

        title("3.1 Details of outward supplies and inward supplies liable to reverse charge",
              ["Nature of supplies", "Total taxable value", "Integrated tax", "Central tax", "State/UT tax", "Cess"])
        for code in TABLE31:
            v = d.t31[code]
            ws.append([TABLE31[code], f(v.taxable), f(v.igst), f(v.cgst), f(v.sgst), f(v.cess)])
        title("3.2 Inter-state supplies to unregistered persons", ["Place of supply", "Taxable value",
                                                                    "Integrated tax"])
        for pos, taxable, igst in d.t32:
            ws.append([pos, f(taxable), f(igst)])
        title("4. Eligible ITC", ["Details", "Integrated tax", "Central tax", "State/UT tax", "Cess"])
        for code in TABLE4:
            v = d.t4[code]
            ws.append([TABLE4[code], f(v.igst), f(v.cgst), f(v.sgst), f(v.cess)])
        title("5. Exempt, nil-rated and non-GST inward supplies", ["Nature of supplies", "Inter-state", "Intra-state"])
        ws.append(["From a supplier under composition scheme, exempt and nil rated supply", f(d.t5["inter"]),
                   f(d.t5["intra"])])
        title("6.1 Payment of tax", ["Description", "Tax payable", "Paid through ITC – IGST", "CGST", "SGST", "Cess",
                                     "Tax paid in cash"])
        so = d.setoff
        for h in HEADS:
            paid = so.paid_by(h)
            ws.append([h.upper(), f(so.liability[h] + so.rcm[h]), *[f(paid[c]) for c in HEADS], f(so.cash[h])])
        ws.append([])
        for n in d.notes:
            ws.append([f"Note: {n}"])
        ws.column_dimensions["A"].width = 70
        for col in "BCDEFG":
            ws.column_dimensions[col].width = 16
        wb.save(path)
        return path

    def _gstr9c_xlsx(self, client: Client, fy: str, path: Path) -> Path:
        from openpyxl import Workbook

        from ..reports.excel_report import _register_styles
        from ..reports.gstr9_sheets import gstr9c_sheet
        from .gstr9c import Gstr9cService

        wb = Workbook(write_only=True)
        _register_styles(wb)
        gstr9c_sheet(wb, Gstr9cService(self.db).statement(client.id, fy))
        wb.save(path)
        return path

    # -------------------------------------------------------------- final
    def final_status(self, kind: str, client_id: int, period: str) -> dict | None:
        with self.db.session() as s:
            row = s.get(AppSetting, self._key(kind, client_id, period))
            return json.loads(row.value_json) if row else None

    def mark_final(self, kind: str, client_id: int, period: str, user: str, files: list[str] | None = None) -> dict:
        prep = self.prepare(kind, client_id, period)
        if not prep.ready:
            raise ServiceError("Cannot mark final – " + "; ".join(c.text for c in prep.checklist if c.status == MISSING))
        data = {"fingerprint": prep.fingerprint(), "by": user, "at": f"{datetime.now():%Y-%m-%d %H:%M}",
                "files": files or [], "figures": [[lbl, str(v), str(t)] for lbl, v, t in prep.figures]}
        with self.db.session() as s:
            key = self._key(kind, client_id, prep.period)
            row = s.get(AppSetting, key)
            if row is None:
                row = AppSetting(key=key, value_json="{}")
                s.add(row)
            row.value_json = json.dumps(data)
            audit(s, "RETURN_FINAL", "return_prep", f"{kind}:{prep.period}", {"by": user}, user, client_id)
        return data

    def reopen(self, kind: str, client_id: int, period: str, user: str) -> None:
        with self.db.session() as s:
            row = s.get(AppSetting, self._key(kind, client_id, period))
            if row is not None:
                s.delete(row)
            audit(s, "RETURN_REOPEN", "return_prep", f"{kind}:{period}", {}, user, client_id)


__all__ = ["ReturnPrepService", "RETURNS", "HOW", "ZERO", "date"]
