"""Month status and client compliance summary.

A month is assessed from what has been imported and reconciled – the software has no
access to the GST portal, so "filed" always means "GSTR-3B imported". Each month gets
a RAG status:

* RED   – possible short payment of output tax, ITC in GSTR-3B above GSTR-2B, or data
          imported but not reconciled;
* AMBER – exceptions pending review, GSTR-3B not imported, differences to explain;
* GREEN – reconciled with nothing pending;
* GREY  – no data for the month.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.money import ZERO

RAG_ORDER = {"grey": 0, "green": 1, "amber": 2, "red": 3}
RAG_LABEL = {"grey": "No data", "green": "Reconciled", "amber": "Attention", "red": "Action required"}


def due_dates(period: str) -> dict[str, date]:
    """Standard monthly due dates (GSTR-1: 11th, GSTR-3B: 20th of the next month).
    Extensions notified by CBIC and QRMP due dates are not modelled."""
    y, m = int(period[:4]), int(period[5:])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return {"GSTR-1": date(y, m, 11), "GSTR-3B": date(y, m, 20)}


@dataclass
class MonthStatus:
    period: str
    purchase_docs: int = 0
    gstr2b_docs: int = 0
    sales_docs: int = 0
    gstr1_docs: int = 0
    gstr1_summary: bool = False
    gstr3b_imported: bool = False
    inward_run_id: int | None = None
    outward_run_id: int | None = None
    inward: dict | None = None  # dashboard summary of the latest inward run
    outward: dict | None = None
    itc_2b: Decimal = ZERO
    itc_books: Decimal = ZERO
    itc_3b: Decimal | None = None
    output_gstr1: Decimal | None = None
    output_3b: Decimal | None = None
    output_sales: Decimal | None = None
    issues: list[tuple[str, str]] = field(default_factory=list)  # (rag, text)

    @property
    def has_data(self) -> bool:
        return any((self.purchase_docs, self.gstr2b_docs, self.sales_docs, self.gstr1_docs, self.gstr1_summary,
                    self.gstr3b_imported))

    @property
    def rag(self) -> str:
        if not self.has_data:
            return "grey"
        worst = "green"
        for r, _t in self.issues:
            if RAG_ORDER[r] > RAG_ORDER[worst]:
                worst = r
        return worst

    @property
    def pending(self) -> int:
        return sum(int((d or {}).get("pending_cases", 0)) for d in (self.inward, self.outward))

    @property
    def itc_at_risk(self) -> Decimal:
        return Decimal(str((self.inward or {}).get("itc_at_risk", 0)))

    @property
    def itc_excess(self) -> Decimal:
        # GSTR-2B ITC is taken from the latest reconciliation of the month
        if self.itc_3b is None or self.inward is None:
            return ZERO
        return max(ZERO, self.itc_3b - self.itc_2b)

    @property
    def short_payment(self) -> Decimal:
        if self.output_3b is None or self.output_gstr1 is None:
            return ZERO
        return max(ZERO, self.output_gstr1 - self.output_3b)


def assess(m: MonthStatus, today: date, tolerance: Decimal = Decimal("1.00")) -> MonthStatus:
    """Fill ``m.issues`` from the month's figures."""
    m.issues = []
    add = m.issues.append
    if not m.has_data:
        return m
    inward_data = m.purchase_docs or m.gstr2b_docs
    if inward_data and m.inward_run_id is None:
        add(("red", "Purchase register / GSTR-2B imported but not reconciled"))
    elif inward_data and not (m.purchase_docs and m.gstr2b_docs):
        add(("amber", f"{'Purchase register' if not m.purchase_docs else 'GSTR-2B'} not imported"))
    outward_data = m.sales_docs or m.gstr1_docs
    if outward_data and m.outward_run_id is None and m.sales_docs and m.gstr1_docs:
        add(("red", "Sales register / GSTR-1 imported but not reconciled"))
    elif m.sales_docs and not (m.gstr1_docs or m.gstr1_summary):
        add(("amber", "GSTR-1 not imported"))
    elif (m.gstr1_docs or m.gstr1_summary) and not m.sales_docs:
        add(("amber", "Sales register not imported"))
    if m.pending:
        add(("amber", f"{m.pending} reconciliation exception(s) pending review"))
    if m.itc_at_risk > tolerance:
        add(("amber", f"ITC at risk ₹{m.itc_at_risk:,.2f}"))
    due = due_dates(m.period)["GSTR-3B"]
    if not m.gstr3b_imported:
        add(("amber", f"GSTR-3B not imported (due {due:%d-%m-%Y})" if today > due else
             f"GSTR-3B due {due:%d-%m-%Y}"))
    else:
        if m.itc_excess > tolerance:
            add(("red", f"ITC claimed in GSTR-3B exceeds GSTR-2B by ₹{m.itc_excess:,.2f} (Section 16(2)(aa))"))
        if m.short_payment > tolerance:
            add(("red", f"Output tax in GSTR-1 exceeds GSTR-3B by ₹{m.short_payment:,.2f} – possible short payment"))
        elif m.output_3b is not None and m.output_gstr1 is not None and m.output_3b - m.output_gstr1 > tolerance:
            add(("amber", f"GSTR-3B output tax exceeds GSTR-1 by ₹{m.output_3b - m.output_gstr1:,.2f}"))
    if m.output_sales is not None and m.output_gstr1 is not None and abs(m.output_sales - m.output_gstr1) > tolerance:
        add(("amber", f"Sales register tax differs from GSTR-1 by ₹{m.output_sales - m.output_gstr1:,.2f}"))
    return m


@dataclass
class ClientCompliance:
    client_id: int
    name: str
    gstin: str
    fy: str
    months: list[MonthStatus]
    followups_due: int = 0

    @property
    def rag(self) -> str:
        return max((m.rag for m in self.months), key=RAG_ORDER.get, default="grey")

    @property
    def months_with_data(self) -> int:
        return sum(1 for m in self.months if m.has_data)

    @property
    def months_reconciled(self) -> int:
        return sum(1 for m in self.months if m.has_data and m.rag == "green")

    def total(self, attr: str) -> Decimal:
        return sum((getattr(m, attr) for m in self.months), ZERO)

    @property
    def pending(self) -> int:
        return sum(m.pending for m in self.months)

    @property
    def red_issues(self) -> int:
        return sum(1 for m in self.months for r, _ in m.issues if r == "red")
