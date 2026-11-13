"""Client MIS: month-by-month figures of the financial year for charts and a management pack (PDF / Excel).

All figures come from the client's imported data; a month without the data shows a blank, never a guessed
number. Output tax and ITC are taken from the GSTR-3B imported, else from the sales register / GSTR-2B (and the
pack says which). Cash paid is GSTR-3B 6.1 when imported, else output tax less ITC claimed (marked as an
estimate).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Invoice
from ..itc.annual import fy_months
from .common import ServiceError

TOP_SUPPLIERS = 10


@dataclass
class MisMonth:
    period: str
    sales: Decimal | None = None  # taxable value of the sales register
    output_tax: Decimal | None = None
    output_basis: str = ""  # "GSTR-3B" / "sales register"
    itc_books: Decimal | None = None
    itc_2b: Decimal | None = None
    itc_claimed: Decimal | None = None  # GSTR-3B Table 4 net
    itc_at_risk: Decimal | None = None
    cash_paid: Decimal | None = None
    cash_estimated: bool = False

    @property
    def label(self) -> str:
        return date(int(self.period[:4]), int(self.period[5:]), 1).strftime("%b-%y")


@dataclass
class Mis:
    client: str
    gstin: str
    fy: str
    months: list[MisMonth]
    suppliers: list[tuple[str, str, Decimal, int]] = field(default_factory=list)  # name, GSTIN, ITC at risk, docs
    notes: list[str] = field(default_factory=list)

    def total(self, attr: str) -> Decimal:
        return sum((getattr(m, attr) or ZERO for m in self.months), ZERO)

    @property
    def active(self) -> list[MisMonth]:
        """Months up to the last one with any figure (later months of the year are left off the charts)."""
        last = max((i for i, m in enumerate(self.months) if any(
            getattr(m, a) is not None for a in ("sales", "output_tax", "itc_books", "itc_2b", "itc_claimed"))),
            default=-1)
        return self.months[:last + 1]


def _tax(v) -> Decimal:
    return v.igst + v.cgst + v.sgst + v.cess


class MisService:
    def __init__(self, db: Database):
        self.db = db

    def build(self, client_id: int, fy: str, today: date | None = None) -> Mis:
        today = today or date.today()
        return self.db.cached(("mis", client_id, fy, today), lambda: self._build(client_id, fy, today))

    def _build(self, client_id: int, fy: str, today: date | None = None) -> Mis:
        from .compliance import ComplianceService
        from .gstr3b import Gstr3bService
        from .supplier_score import SupplierScoreService

        cc = ComplianceService(self.db).client_summary(client_id, fy, today)
        months = fy_months(fy)
        filed = Gstr3bService(self.db).values(client_id, months)
        with self.db.session() as s:
            sales: dict[str, Decimal] = {}
            for p, taxable in s.execute(select(Invoice.period, Invoice.taxable).where(
                    Invoice.client_id == client_id, Invoice.source_type == "SALES", Invoice.period.in_(months))):
                sales[p] = sales.get(p, ZERO) + (taxable or ZERO)  # money is added in Python (exact decimals)
            books: dict[str, Decimal] = {}
            for p, doc, i, c, sg, cs in s.execute(select(Invoice.period, Invoice.doc_type, Invoice.igst, Invoice.cgst,
                                                         Invoice.sgst, Invoice.cess).where(
                    Invoice.client_id == client_id, Invoice.source_type == "BOOKS", Invoice.period.in_(months))):
                k = -1 if doc == "CRN" else 1
                books[p] = books.get(p, ZERO) + k * ((i or ZERO) + (c or ZERO) + (sg or ZERO) + (cs or ZERO))
        out = Mis(cc.name, cc.gstin, fy, [])
        estimated = False
        for ms in cc.months:
            m = MisMonth(ms.period, sales=sales.get(ms.period))
            t = filed.get(ms.period, {})
            if ms.output_3b is not None:
                m.output_tax, m.output_basis = ms.output_3b, "GSTR-3B"
            elif ms.output_sales is not None:
                m.output_tax, m.output_basis = ms.output_sales, "sales register"
            m.itc_books = (ms.itc_books if ms.inward_run_id else books.get(ms.period)) if ms.purchase_docs else None
            m.itc_2b = ms.itc_2b if ms.gstr2b_docs else None
            m.itc_claimed = ms.itc_3b
            m.itc_at_risk = ms.itc_at_risk if ms.inward_run_id else None
            if "61CASH" in t:
                m.cash_paid = _tax(t["61CASH"])
            elif m.output_tax is not None and m.itc_claimed is not None:
                m.cash_paid = max(m.output_tax - m.itc_claimed, ZERO)
                m.cash_estimated = estimated = True
            out.months.append(m)
        if estimated:
            out.notes.append("Cash paid is estimated (output tax less ITC claimed) for months without GSTR-3B "
                             "Table 6.1 – import the GSTR-3B JSON for the actual figure.")
        if any(m.output_basis == "sales register" for m in out.months):
            out.notes.append("Output tax is from the sales register for months without GSTR-3B.")
        try:
            scores, notes = SupplierScoreService(self.db).scores(client_id, fy)
        except ServiceError:
            scores, notes = [], []
        risky = sorted((x for x in scores if x.itc_at_risk > 0), key=lambda x: x.itc_at_risk, reverse=True)
        out.suppliers = [(x.name or x.gstin, x.gstin, x.itc_at_risk, x.missing_docs) for x in risky[:TOP_SUPPLIERS]]
        out.notes += notes
        return out

    # --------------------------------------------------------------- pack
    def export_xlsx(self, mis: Mis, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, LineChart, Reference
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Monthly"
        ws.append([f"{mis.client} ({mis.gstin}) – GST MIS {mis.fy}"])
        ws["A1"].font = Font(bold=True, size=13)
        head = ["Month", "Sales (taxable)", "Output tax", "ITC books", "ITC GSTR-2B", "ITC claimed (3B)",
                "ITC at risk", "Cash paid", "Note"]
        ws.append(head)
        for c in ws[2]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
        rows = mis.active or mis.months
        for m in rows:
            ws.append([m.label, *(None if v is None else float(v) for v in (
                m.sales, m.output_tax, m.itc_books, m.itc_2b, m.itc_claimed, m.itc_at_risk, m.cash_paid)),
                "cash estimated" if m.cash_estimated else ""])
        n = len(rows)
        ws.append(["Total", *(float(mis.total(a)) for a in ("sales", "output_tax", "itc_books", "itc_2b",
                                                             "itc_claimed", "itc_at_risk", "cash_paid"))])
        for row in ws.iter_rows(min_row=3, max_row=3 + n, min_col=2, max_col=8):
            for c in row:
                c.number_format = "#,##,##0.00"
        ws.column_dimensions["A"].width = 10
        for col in "BCDEFGH":
            ws.column_dimensions[col].width = 16
        if n:
            cats = Reference(ws, min_col=1, min_row=3, max_row=2 + n)
            ch = LineChart()
            ch.title, ch.y_axis.title, ch.height, ch.width = "ITC by month", "₹", 8, 18
            ch.add_data(Reference(ws, min_col=4, max_col=6, min_row=2, max_row=2 + n), titles_from_data=True)
            ch.set_categories(cats)
            for s, colour in zip(ch.series, ("2A78D6", "EB6834", "1BAF7A")):
                s.graphicalProperties.line.solidFill = colour
                s.graphicalProperties.line.width = 22000
                s.smooth = False
            ws.add_chart(ch, f"A{n + 6}")
            for col, title, anchor in ((2, "Sales by month", "K3"), (8, "Cash paid by month", "K20")):
                b = BarChart()
                b.title, b.height, b.width, b.legend = title, 8, 16, None
                b.add_data(Reference(ws, min_col=col, min_row=2, max_row=2 + n), titles_from_data=True)
                b.set_categories(cats)
                b.series[0].graphicalProperties.solidFill = "2A78D6"
                b.series[0].graphicalProperties.line.noFill = True
                ws.add_chart(b, anchor)
        s2 = wb.create_sheet("Supplier risk")
        s2.append(["Supplier", "GSTIN", "ITC at risk", "Documents not in GSTR-2B"])
        for c in s2[1]:
            c.font = Font(bold=True)
        for name, g, amount, docs in mis.suppliers:
            s2.append([name, g, float(amount), docs])
        s2.column_dimensions["A"].width = 34
        s2.column_dimensions["B"].width = 18
        s2.column_dimensions["C"].width = 16
        if mis.notes:
            s3 = wb.create_sheet("Notes")
            for t in mis.notes:
                s3.append([t])
        path = Path(path)
        wb.save(path)
        return path

    def export_pdf(self, mis: Mis, path: str | Path, firm: str = "") -> Path:
        from ..reports.mis_pdf import build_mis_pdf

        return build_mis_pdf(mis, Path(path), firm)
