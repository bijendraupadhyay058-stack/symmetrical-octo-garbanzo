"""Year-on-year comparison of a client: the MIS figures (sales, output tax, ITC as per books / GSTR-2B / claimed,
ITC at risk, tax paid in cash) of the chosen year beside the earlier years, in total and month by month, with the
change, and the main suppliers' purchases across the years.

Figures come from the data imported for each year (see services/mis.py); a year or month without data shows a
blank, never a nil or a guessed figure, and the change is worked only when both years have the figure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Invoice
from ..itc.annual import fy_months
from .common import ServiceError
from .mis import Mis, MisService

METRICS = (("sales", "Sales (taxable value)"), ("output_tax", "Output tax"), ("itc_books", "ITC as per books"),
           ("itc_2b", "ITC in GSTR-2B"), ("itc_claimed", "ITC claimed in GSTR-3B"), ("itc_at_risk", "ITC at risk"),
           ("cash_paid", "Tax paid in cash"))
LABELS = dict(METRICS)
MONTHS = ("Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar")
TOP_SUPPLIERS = 15


def prev_fy(fy: str) -> str:
    start = int(fy[:4]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def pct(new: Decimal | None, old: Decimal | None) -> Decimal | None:
    if new is None or old is None or not old:
        return None
    return ((new - old) * 100 / abs(old)).quantize(Decimal("0.1"), ROUND_HALF_UP)


@dataclass
class SupplierYears:
    gstin: str
    name: str
    purchases: dict[str, Decimal] = field(default_factory=dict)  # fy -> taxable value (credit notes deducted)
    itc: dict[str, Decimal] = field(default_factory=dict)

    def status(self, years: list[str]) -> str:
        latest, before = years[-1], years[:-1]
        if not self.purchases.get(latest) and any(self.purchases.get(y) for y in before):
            return "No purchases this year"
        if self.purchases.get(latest) and before and not any(self.purchases.get(y) for y in before):
            return "New supplier"
        return ""


@dataclass
class Yoy:
    client: str
    gstin: str
    years: list[str]  # oldest first; the last is the chosen year
    mis: dict[str, Mis]
    suppliers: list[SupplierYears] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def latest(self) -> str:
        return self.years[-1]

    @property
    def previous(self) -> str | None:
        return self.years[-2] if len(self.years) > 1 else None

    def total(self, fy: str, metric: str) -> Decimal | None:
        vals = [getattr(m, metric) for m in self.mis[fy].months]
        return None if all(v is None for v in vals) else sum((v or ZERO for v in vals), ZERO)

    def month(self, fy: str, metric: str, i: int) -> Decimal | None:
        return getattr(self.mis[fy].months[i], metric)

    def change(self, metric: str) -> tuple[Decimal | None, Decimal | None]:
        """(difference, % change) of the chosen year against the previous one."""
        if self.previous is None:
            return None, None
        new, old = self.total(self.latest, metric), self.total(self.previous, metric)
        return (None if new is None or old is None else new - old), pct(new, old)

    def like_for_like(self, metric: str) -> tuple[Decimal | None, Decimal | None, int]:
        """Totals of the chosen and previous year over the months both have (a year in progress is compared with the
        same months of the previous year): (latest, previous, months)."""
        if self.previous is None:
            return None, None, 0
        a = b = ZERO
        n = 0
        for i in range(12):
            x, y = self.month(self.latest, metric, i), self.month(self.previous, metric, i)
            if x is not None and y is not None:
                a, b, n = a + x, b + y, n + 1
        return (a, b, n) if n else (None, None, 0)

    def has_data(self, fy: str) -> bool:
        return any(self.total(fy, m) is not None for m, _l in METRICS)


class YoyService:
    def __init__(self, db: Database):
        self.db = db

    def build(self, client_id: int, fy: str, years: int = 3, today: date | None = None) -> Yoy:
        today = today or date.today()
        return self.db.cached(("yoy", client_id, fy, years, today), lambda: self._build(client_id, fy, years, today))

    def _build(self, client_id: int, fy: str, years: int, today: date) -> Yoy:
        if not 2 <= years <= 5:
            raise ServiceError("Compare 2 to 5 years")
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            name, gstin = c.name, c.gstin
        fys = [fy]
        while len(fys) < years:
            fys.insert(0, prev_fy(fys[0]))
        mis = MisService(self.db)
        out = Yoy(name, gstin, fys, {y: mis.build(client_id, y, today) for y in fys})
        empty = [y for y in fys if not out.has_data(y)]
        if empty:
            out.notes.append("No data imported for " + ", ".join(empty) + " – import its registers / returns to "
                             "compare (the earlier year's files can be imported with the current year).")
        if f"{today:%Y-%m}" <= fy_months(fy)[-1] and out.previous:
            out.notes.append(f"{fy} is still in progress – look at the like-for-like change (the same months of "
                             f"{out.previous}).")
        for y in fys:
            out.notes += [f"{y}: {n}" for n in out.mis[y].notes if "estimated" in n]
        out.suppliers = self._suppliers(client_id, fys)
        return out

    def _suppliers(self, client_id: int, fys: list[str]) -> list[SupplierYears]:
        fy_of = {m: y for y in fys for m in fy_months(y)}
        by: dict[str, SupplierYears] = {}
        with self.db.session() as s:
            q = select(Invoice.supplier_gstin, Invoice.supplier_name, Invoice.period, Invoice.doc_type,
                       Invoice.taxable, Invoice.igst, Invoice.cgst, Invoice.sgst, Invoice.cess).where(
                Invoice.client_id == client_id, Invoice.source_type == "BOOKS", Invoice.period.in_(list(fy_of)))
            for g, nm, period, doc, taxable, i, cg, sg, cs in s.execute(q):
                k = -1 if doc == "CRN" else 1
                sup = by.setdefault(g or "(no GSTIN)", SupplierYears(g or "", nm or ""))
                sup.name = sup.name or nm or ""
                y = fy_of[period]
                sup.purchases[y] = sup.purchases.get(y, ZERO) + k * (taxable or ZERO)
                sup.itc[y] = sup.itc.get(y, ZERO) + k * ((i or ZERO) + (cg or ZERO) + (sg or ZERO) + (cs or ZERO))
        ranked = sorted(by.values(), key=lambda x: max((abs(v) for v in x.purchases.values()), default=ZERO),
                        reverse=True)
        return ranked[:TOP_SUPPLIERS]

    # ------------------------------------------------------------- export
    def export_xlsx(self, y: Yoy, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.chart import LineChart, Reference
        from openpyxl.styles import Font, PatternFill

        def f(v):
            return None if v is None else float(v)

        def header(ws, cols):
            ws.append(cols)
            for c in ws[ws.max_row]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="1F3864")

        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append([f"{y.client} ({y.gstin}) – year-on-year comparison {y.years[0]} to {y.latest}"])
        ws["A1"].font = Font(bold=True, size=13)
        header(ws, ["Figure", *y.years, f"Change vs {y.previous}" if y.previous else "Change", "Change %",
                    "Like-for-like change %"])
        for m, label in METRICS:
            d, p = y.change(m)
            a, b, _n = y.like_for_like(m)
            ws.append([label, *(f(y.total(fy, m)) for fy in y.years), f(d), f(p), f(pct(a, b))])
        for row in ws.iter_rows(min_row=3, min_col=2, max_col=len(y.years) + 2):
            for c in row:
                c.number_format = "#,##,##0.00"
        ws.column_dimensions["A"].width = 26
        for i in range(len(y.years) + 4):
            ws.column_dimensions[chr(66 + i)].width = 16
        mws = wb.create_sheet("Monthly")
        row0 = 1
        for m, label in METRICS:
            mws.cell(row0, 1, label).font = Font(bold=True)
            mws.append(["Month", *y.years])
            for c in mws[mws.max_row]:
                c.font = Font(bold=True)
            for i, mon in enumerate(MONTHS):
                mws.append([mon, *(f(y.month(fy, m, i)) for fy in y.years)])
            if m == "sales":
                ch = LineChart()
                ch.title, ch.height, ch.width = "Sales by month", 8, 18
                ch.add_data(Reference(mws, min_col=2, max_col=1 + len(y.years), min_row=row0 + 1, max_row=row0 + 13),
                            titles_from_data=True)
                ch.set_categories(Reference(mws, min_col=1, min_row=row0 + 2, max_row=row0 + 13))
                for s, colour in zip(ch.series, ("9AA5B1", "EB6834", "2A78D6", "1BAF7A", "7E57C2")[-len(y.years):]):
                    s.graphicalProperties.line.solidFill = colour
                    s.smooth = False
                mws.add_chart(ch, "H2")
            mws.append([])
            row0 = mws.max_row + 1
        for row in mws.iter_rows(min_col=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##,##0.00"
        sws = wb.create_sheet("Suppliers")
        header(sws, ["Supplier", "GSTIN", *(f"Purchases {fy}" for fy in y.years), *(f"ITC {fy}" for fy in y.years),
                     "Note"])
        for sup in y.suppliers:
            sws.append([sup.name, sup.gstin, *(f(sup.purchases.get(fy)) for fy in y.years),
                        *(f(sup.itc.get(fy)) for fy in y.years), sup.status(y.years)])
        sws.column_dimensions["A"].width = 34
        sws.column_dimensions["B"].width = 18
        if y.notes:
            n = wb.create_sheet("Notes")
            for t in y.notes:
                n.append([t])
        path = Path(path)
        wb.save(path)
        return path
