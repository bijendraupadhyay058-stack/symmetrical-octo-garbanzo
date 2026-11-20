"""Year-end closing pack for a client's financial year: one indexed PDF and one Excel workbook for the audit file.

Contents: month-by-month compliance status, GSTR-9 working (Tables 4–9), GSTR-9C summary, ITC Table 8, the ITC
claim plan at the year end (documents still on hold or time-barred), interest and late fee, open notices and the
suppliers with the most ITC at risk. Every figure is taken from the program's own workings; a part without data
says so instead of showing zeros.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO
from ..db.database import Database
from .common import ServiceError, audit


@dataclass
class ClosingData:
    client: object
    fy: str
    as_of: date
    compliance: object = None
    gstr9: object = None
    gstr9c: object = None
    table8: object = None
    plan: object = None
    interest: object = None
    notices: list = field(default_factory=list)
    suppliers: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)  # parts that could not be prepared, with the reason


class ClosingPackService:
    def __init__(self, db: Database):
        self.db = db

    def gather(self, client_id: int, fy: str, as_of: date | None = None) -> ClosingData:
        from .claim_plan import ClaimPlanService
        from .clients import ClientService
        from .compliance import ComplianceService
        from .gstr9 import Gstr9Service
        from .gstr9c import Gstr9cService
        from .interest import InterestService
        from .itc import ItcService
        from .notices import NoticeService
        from .reconciliation import months_between
        from .supplier_score import SupplierScoreService

        as_of = as_of or date.today()
        client = ClientService(self.db).get(client_id)
        if client is None:
            raise ServiceError(f"Client {client_id} not found")
        d = ClosingData(client, fy, as_of)

        def part(name, fn):
            try:
                return fn()
            except ServiceError as exc:
                d.gaps.append(f"{name}: {exc}")
                return None

        d.compliance = part("Compliance status", lambda: ComplianceService(self.db).client_summary(client_id, fy,
                                                                                                   as_of))
        d.gstr9 = part("GSTR-9 working", lambda: Gstr9Service(self.db).working(client_id, fy))
        d.gstr9c = part("GSTR-9C", lambda: Gstr9cService(self.db).statement(client_id, fy))
        itc = ItcService(self.db)
        d.table8 = part("ITC Table 8", lambda: itc.annual(client_id, fy))
        last = f"{int(fy[:4]) + 1}-03"
        d.plan = part("ITC claim plan", lambda: ClaimPlanService(self.db).build(client_id, last, as_of))
        d.interest = part("Interest and late fee", lambda: InterestService(self.db).working(client_id, fy, as_of))
        d.notices = [n for n in NoticeService(self.db).list(client_id) if n.status != "CLOSED"]
        scores = part("Supplier risk", lambda: SupplierScoreService(self.db).scores(client_id, fy))
        if scores:
            d.suppliers = sorted((x for x in scores[0] if x.itc_at_risk > 0), key=lambda x: x.itc_at_risk,
                                 reverse=True)[:15]
        if d.table8 is not None:
            d.claims = itc.claim_register(client_id, months_between(f"{fy[:4]}-04", d.table8.cutoff))
        return d

    def build(self, client_id: int, fy: str, out_dir: str | Path, firm: str = "", as_of: date | None = None,
              user: str | None = None) -> tuple[Path, Path]:
        from ..reports.closing_pdf import build_closing_pdf

        d = self.gather(client_id, fy, as_of)
        folder = Path(out_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"Year-end_pack_{d.client.gstin}_FY{fy}"
        pdf = build_closing_pdf(d, folder / f"{stem}.pdf", firm)
        xlsx = self._xlsx(d, folder / f"{stem}.xlsx")
        with self.db.session() as s:
            audit(s, "EXPORT", "closing_pack", fy, {"files": [pdf.name, xlsx.name], "gaps": d.gaps}, user, client_id)
        return pdf, xlsx

    # -------------------------------------------------------------- Excel
    def _xlsx(self, d: ClosingData, path: Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        from ..itc.claim_plan import BARRED, HOLD
        from ..reports.annual_report import build_annual
        from .itc import ItcService
        from .tds_tcs import TdsTcsService

        if d.table8 is not None and d.gstr9 is not None and d.gstr9c is not None:
            from openpyxl import load_workbook

            annual = build_annual(d.client, d.table8, d.claims, ItcService(self.db).rules(d.client.id), d.gstr9,
                                  d.gstr9c, TdsTcsService(self.db).statement(d.client.id, d.fy))
            part = path.with_suffix(".annual.xlsx")
            annual.save(part)  # written in streaming mode: reopened to add the year-end sheets
            wb = load_workbook(part)
            part.unlink()
        else:
            wb = Workbook()
            wb.remove(wb.active)
        bold = Font(bold=True)

        def sheet(title, head, rows):
            ws = wb.create_sheet(title)
            ws.append(head)
            for c in ws[1]:
                c.font = bold
            for r in rows:
                ws.append([float(v) if isinstance(v, Decimal) else v for v in r])
            for i, _h in enumerate(head):
                ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = 16 if i else 22
            return ws

        if d.compliance is not None:
            sheet("Status by month", ["Month", "Status", "Purchase docs", "GSTR-2B docs", "Sales docs", "GSTR-3B",
                                      "Issues"],
                  [[m.period, m.rag.upper(), m.purchase_docs, m.gstr2b_docs, m.sales_docs,
                    "imported" if m.gstr3b_imported else "–", "; ".join(t for _r, t in m.issues)]
                   for m in d.compliance.months])
        if d.plan is not None:
            sheet("ITC on hold", ["Plan", "Supplier", "GSTIN", "Invoice no", "Date", "ITC", "Last date", "Why"],
                  [[ln.bucket, ln.doc.supplier_name, ln.doc.supplier_gstin, ln.doc.invoice_no, ln.doc.invoice_date,
                    ln.itc, ln.deadline, ln.reason] for ln in d.plan.lines if ln.bucket in (HOLD, BARRED)])
        if d.interest is not None:
            sheet("Interest & late fee", ["Return", "Period", "Due", "Filed", "Days late", "Interest", "Late fee"],
                  [[r.return_type, r.period, r.due, r.filed, r.days, r.interest_total, r.fee_total]
                   for r in d.interest.late])
        sheet("Open notices", ["Form", "Reference", "Date", "Period", "Amount", "Reply due", "Status"],
              [[n.form, n.reference, n.notice_date, f"{n.period_from}..{n.period_to}", n.amount, n.reply_due, n.status]
               for n in d.notices])
        sheet("Supplier risk", ["Supplier", "GSTIN", "ITC at risk", "Docs not in 2B", "Score", "Risk"],
              [[x.name, x.gstin, x.itc_at_risk, x.missing_docs, x.score, x.band] for x in d.suppliers])
        idx = wb.create_sheet("Index", 0)
        idx.append([f"Year-end pack – {d.client.name} ({d.client.gstin}) – FY {d.fy}"])
        idx["A1"].font = Font(bold=True, size=13)
        idx.append([f"Prepared on {d.as_of:%d-%m-%Y}"])
        idx.append([])
        idx.append(["Sheet"])
        idx["A4"].font = bold
        for ws in wb.worksheets[1:]:
            idx.append([ws.title])
            c = idx.cell(idx.max_row, 1)
            c.hyperlink = f"#'{ws.title}'!A1"
            c.style = "Hyperlink"
        if d.gaps:
            idx.append([])
            idx.append(["Not prepared"])
            for g in d.gaps:
                idx.append([g])
        idx.column_dimensions["A"].width = 60
        wb.active = 0
        tmp = path.with_suffix(".tmp.xlsx")
        wb.save(tmp)
        tmp.replace(path)
        return path


__all__ = ["ClosingPackService", "ClosingData", "ZERO"]
