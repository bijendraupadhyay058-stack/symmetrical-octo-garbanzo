"""GSTR-9C reconciliation statement (self-certified), Part A Tables 5, 7, 9 and 12.

Figures from the audited financial statements are entered by the preparer (``inputs``).
Where the application has a reasonable stand-in, the default is shown and marked as a
default: the sales register for turnover and for the rate-wise tax, and the purchase
register for ITC. A default is never presented as the audited figure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..core.models import DocType, InvoiceRecord
from ..core.money import ZERO
from .expenses import TABLE14, TABLE14_INPUTS
from .working import Gstr9Working, classify_sale

#: Table 5 adjustments: (code, label, sign). 5A is the starting figure.
TABLE5 = [
    ("5A", "Turnover (including exports) as per audited financial statements", 1),
    ("5B", "Unbilled revenue at the beginning of the financial year", 1),
    ("5C", "Unadjusted advances at the end of the financial year", 1),
    ("5D", "Deemed supply under Schedule I", 1),
    ("5E", "Credit notes issued after the end of the financial year but reflected in the annual return", 1),
    ("5F", "Trade discounts accounted for in the audited financial statements but not permissible under GST", 1),
    ("5H", "Unbilled revenue at the end of the financial year", -1),
    ("5I", "Unadjusted advances at the beginning of the financial year", -1),
    ("5J", "Credit notes accounted for in the audited financial statements but not permissible under GST", -1),
    ("5K", "Adjustments on account of supply of goods by SEZ units to DTA units", -1),
    ("5L", "Turnover for the period under composition scheme", -1),
    ("5M", "Adjustments in turnover under section 15 and rules thereunder", 1),
    ("5N", "Adjustments in turnover due to foreign exchange fluctuations", 1),
    ("5O", "Adjustments in turnover due to reasons not listed above", 1),
]
LABELS = {c: lab for c, lab, _s in TABLE5} | {
    "5P": "Annual turnover after adjustments", "5Q": "Turnover as declared in the annual return (GSTR-9)",
    "5R": "Un-reconciled turnover (Q − P)",
    "7A": "Annual turnover after adjustments (5P)",
    "7B": "Value of exempted, nil rated, non-GST supplies and no-supply turnover",
    "7C": "Zero rated supplies without payment of tax", "7D": "Supplies on which tax is paid by the recipient "
                                                               "on reverse charge basis",
    "7E": "Taxable turnover as per adjustments above (A − B − C − D)",
    "7F": "Taxable turnover as per liability declared in the annual return (GSTR-9)",
    "7G": "Un-reconciled taxable turnover (F − E)",
    "12A": "ITC availed as per audited financial statements or books of account",
    "12B": "ITC booked in earlier financial years claimed in the current financial year",
    "12C": "ITC booked in the current financial year to be claimed in subsequent financial years",
    "12D": "ITC availed as per audited financial statements or books of account (A + B − C)",
    "12E": "ITC claimed in the annual return (GSTR-9)", "12F": "Un-reconciled ITC (E − D)",
}
#: Items the preparer enters (amounts); the reason codes hold explanations of differences.
INPUT_ITEMS = [c for c, _l, _s in TABLE5] + ["7B", "7C", "7D", "12A", "12B", "12C", "9INT", "9FEE", "9PEN",
                                              "9OTH"] + TABLE14_INPUTS
REASON_ITEMS = {"R6": "Reasons for un-reconciled turnover (Table 6)",
                "R8": "Reasons for un-reconciled taxable turnover (Table 8)",
                "R10": "Reasons for un-reconciled tax payable (Table 10)",
                "R13": "Reasons for un-reconciled ITC (Table 13)",
                "R15": "Reasons for un-reconciled ITC on expenses (Table 15)"}
SLABS = [Decimal(x) for x in ("5", "12", "18", "28", "3", "0.25", "0.1", "40")]


@dataclass
class Line:
    code: str
    amount: Decimal | None
    source: str = ""  # "entered", "default – sales register", "GSTR-9", "computed", ...

    @property
    def label(self) -> str:
        return LABELS.get(self.code, self.code)


@dataclass
class RateRow:
    rate: str
    taxable: Decimal = ZERO
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess


@dataclass
class ExpenseRow:
    code: str
    label: str
    value: Decimal = ZERO
    itc_total: Decimal = ZERO
    itc_eligible: Decimal = ZERO


@dataclass
class Gstr9cStatement:
    fy: str
    table5: list[Line] = field(default_factory=list)
    table7: list[Line] = field(default_factory=list)
    table9: list[RateRow] = field(default_factory=list)  # books, rate-wise
    table9_other: dict[str, Decimal] = field(default_factory=dict)  # interest, late fee, penalty, others
    table9_paid: dict[str, Decimal | None] = field(default_factory=dict)  # per head, per GSTR-9
    table12: list[Line] = field(default_factory=list)
    table14: list["ExpenseRow"] = field(default_factory=list)
    table14_claimed: Decimal = ZERO  # 14S – ITC claimed in GSTR-9
    reasons: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def line(self, code: str) -> Line:
        return next(x for x in self.table5 + self.table7 + self.table12 if x.code == code)

    @property
    def table14_total(self) -> Decimal:
        """14R – total eligible ITC availed on expenses."""
        return sum((x.itc_eligible for x in self.table14), ZERO)

    @property
    def table14_unreconciled(self) -> Decimal:
        """14T = 14S − 14R."""
        return self.table14_claimed - self.table14_total

    @property
    def table9_total(self) -> dict[str, Decimal]:
        out = {h: sum((getattr(r, h) for r in self.table9), ZERO) for h in ("igst", "cgst", "sgst", "cess")}
        return out

    @property
    def table9_unreconciled(self) -> dict[str, Decimal | None]:
        tot = self.table9_total
        return {h: (None if self.table9_paid.get(h) is None else self.table9_paid[h] - tot[h]) for h in tot}


def _rate_of(r: InvoiceRecord) -> str:
    if not r.taxable:
        return "Other"
    eff = (r.total_tax - r.cess) * 100 / r.taxable
    best = min(SLABS, key=lambda s: abs(s - eff))
    return f"{best.normalize():f}%" if abs(best - eff) <= Decimal("0.5") else "Other"


def build_9c(fy: str, g9: Gstr9Working, sales: list[InvoiceRecord], books_itc: Decimal,
             inputs: dict[str, tuple[Decimal | None, str]]) -> Gstr9cStatement:
    st = Gstr9cStatement(fy)

    def given(code):
        amount, _note = inputs.get(code, (None, ""))
        return amount

    # sales register stand-ins
    by_row: dict[str, Decimal] = {}
    turnover = ZERO
    for r in sales:
        code = classify_sale(r)
        v = r.signed("taxable")
        by_row[code] = by_row.get(code, ZERO) + abs(v)
        turnover += v

    # Table 5
    total = ZERO
    for code, _label, sign in TABLE5:
        amount = given(code)
        if code == "5A" and amount is None:
            st.table5.append(Line(code, turnover, "default – sales register (enter the audited figure)"))
            total += turnover
            continue
        st.table5.append(Line(code, amount if amount is not None else ZERO, "entered" if amount is not None else ""))
        total += (amount or ZERO) * sign
    st.table5.append(Line("5P", total, "computed"))
    q = g9.row("5N").gstr1.taxable
    st.table5.append(Line("5Q", q, "GSTR-9 5N"))
    st.table5.append(Line("5R", q - total, "computed"))

    # Table 7
    defaults = {"7B": sum((by_row.get(c, ZERO) for c in ("5D", "5E", "5F")), ZERO),
                "7C": by_row.get("5A", ZERO) + by_row.get("5B", ZERO), "7D": by_row.get("5C", ZERO)}
    st.table7.append(Line("7A", total, "5P"))
    e = total
    for code in ("7B", "7C", "7D"):
        amount = given(code)
        if amount is None:
            st.table7.append(Line(code, defaults[code], "default – sales register"))
            e -= defaults[code]
        else:
            st.table7.append(Line(code, amount, "entered"))
            e -= amount
    st.table7.append(Line("7E", e, "computed"))
    f = g9.row("4N").gstr1.taxable - g9.row("4G").gstr1.taxable
    st.table7.append(Line("7F", f, "GSTR-9 4N − 4G"))
    st.table7.append(Line("7G", f - e, "computed"))

    # Table 9: rate-wise tax per books (sales register) vs paid per GSTR-9
    rows: dict[str, RateRow] = {}
    for r in sales:
        if r.total_tax == 0 and r.doc_type == DocType.INVOICE:
            continue
        rate = _rate_of(r) if r.doc_type == DocType.INVOICE else "Credit/debit notes"
        row = rows.setdefault(rate, RateRow(rate))
        row.taxable += r.signed("taxable")
        for h in ("igst", "cgst", "sgst", "cess"):
            setattr(row, h, getattr(row, h) + r.signed(h))
    order = [f"{s.normalize():f}%" for s in SLABS] + ["Other", "Credit/debit notes"]
    st.table9 = [rows[k] for k in order if k in rows]
    st.table9_other = {"Interest": given("9INT") or ZERO, "Late fee": given("9FEE") or ZERO,
                       "Penalty": given("9PEN") or ZERO, "Others": given("9OTH") or ZERO}
    for x in g9.table9:
        st.table9_paid[x.head.lower()] = x.paid if x.paid is not None else None
    if all(v is None for v in st.table9_paid.values()):
        st.notes.append("GSTR-3B Table 6.1 (payments) not imported – Table 9 'paid as declared in GSTR-9' is blank.")

    # Table 12
    a = given("12A")
    a_line = Line("12A", a, "entered") if a is not None else Line(
        "12A", books_itc, "default – purchase register (enter the figure per the audited accounts)")
    b, c = given("12B") or ZERO, given("12C") or ZERO
    d = a_line.amount + b - c
    e12 = next(x for x in g9.table7 if x.code == "7J").gstr1.total
    st.table12 = [a_line, Line("12B", b, "entered" if given("12B") is not None else ""),
                  Line("12C", c, "entered" if given("12C") is not None else ""), Line("12D", d, "computed"),
                  Line("12E", e12, "GSTR-9 7J"), Line("12F", e12 - d, "computed")]

    # Table 14: ITC availed on expenses (entered or imported from the expense ledger)
    for code, label in TABLE14:
        st.table14.append(ExpenseRow(code, label, given(f"{code}-V") or ZERO, given(f"{code}-T") or ZERO,
                                     given(f"{code}-E") or ZERO))
    st.table14_claimed = e12
    if not any(x.value or x.itc_eligible for x in st.table14):
        st.notes.append("Table 14 (ITC on expenses) is empty – import the expense ledger or enter the heads.")

    st.reasons = {k: inputs.get(k, (None, ""))[1] for k in REASON_ITEMS}
    defaults_used = [x.code for x in st.table5 + st.table7 + st.table12 if x.source.startswith("default")]
    if defaults_used:
        st.notes.append("Defaults used for " + ", ".join(defaults_used) + " – replace them with the figures from "
                        "the audited financial statements before certifying.")
    if any(x.itc_eligible for x in st.table14) and abs(st.table14_unreconciled) >= Decimal("1") \
            and not st.reasons.get("R15"):
        st.notes.append("14T shows an un-reconciled difference – record the reasons (Table 15).")
    for code, reason_key in (("5R", "R6"), ("7G", "R8"), ("12F", "R13")):
        if abs(st.line(code).amount) >= Decimal("1") and not st.reasons.get(reason_key):
            st.notes.append(f"{code} shows an un-reconciled difference – record the reasons ({REASON_ITEMS[reason_key]}).")
    st.notes.extend(n for n in g9.notes if "not imported" in n)
    return st
