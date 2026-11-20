"""Supplier compliance score: how reliably each supplier reports its invoices.

From the year's purchase register, GSTR-2B and the latest books vs GSTR-2B
reconciliation of each month. The score starts at 100, and points are deducted for:

| Signal | Up to | Measured as |
|---|---:|---|
| Documents in the books still missing in GSTR-2B | 40 | share of the supplier's books documents |
| Documents reported in a later month's GSTR-2B than their date (GSTR-1 filed late, or reported late) | 25 | share of its GSTR-2B documents |
| Matched documents with value / tax differences | 20 | share of its books documents |
| Documents marked "ITC not available" in GSTR-2B | 10 | share of its GSTR-2B documents |
| Amended documents (B2BA / CDNRA) | 5 | share of its GSTR-2B documents |

Risk bands:

* *Low* – 80 or more;
* *Medium* – 60 to 79;
* *High* – below 60;
* *Too little data* – fewer than three documents in all.

Every deduction is explained in words. Suppliers are ranked for follow-up by risk and by
the ITC at risk, which is the ITC on documents still missing in GSTR-2B.

The score is a working aid built from the client's own data. It is not a rating of the
supplier's compliance with the law.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..core.models import Category, InvoiceRecord, ReconLine
from ..core.money import ZERO

WEIGHTS = {"missing": 40, "late": 25, "mismatch": 20, "unavailable": 10, "amended": 5}
VALUE_DIFFERENCES = frozenset({Category.TAXABLE_DIFFERENCE, Category.IGST_DIFFERENCE, Category.CGST_SGST_DIFFERENCE,
                               Category.CESS_DIFFERENCE, Category.MULTIPLE_DIFFERENCES, Category.CDN_DIFFERENCE})
BANDS = (("Low", 80), ("Medium", 60), ("High", 0))


def _months(period: str) -> int:
    return int(period[:4]) * 12 + int(period[5:])


@dataclass
class SupplierScore:
    gstin: str
    name: str
    books_docs: int = 0
    books_itc: Decimal = ZERO
    gstr2b_docs: int = 0
    gstr2b_itc: Decimal = ZERO
    missing_docs: int = 0
    itc_at_risk: Decimal = ZERO
    late_docs: int = 0
    max_lag: int = 0  # months
    mismatched: int = 0
    unavailable: int = 0
    amended: int = 0
    score: int = 100
    band: str = "Low"
    reasons: list[str] = field(default_factory=list)
    followup: str = ""

    def deduct(self, key: str, count: int, base: int, text: str) -> None:
        if not count or not base:
            return
        points = round(WEIGHTS[key] * min(count / base, 1))
        if points:
            self.score -= points
            self.reasons.append(f"−{points}: {text}")


def score_suppliers(books: list[InvoiceRecord], gstr2b: list[InvoiceRecord], monthly_lines: list[list[ReconLine]],
                    followups: dict[str, str] | None = None) -> list[SupplierScore]:
    """``monthly_lines``: the lines of the latest books vs GSTR-2B run of each month, in month order."""
    out: dict[str, SupplierScore] = {}

    def sup(r: InvoiceRecord) -> SupplierScore:
        s = out.get(r.supplier_gstin)
        if s is None:
            s = out[r.supplier_gstin] = SupplierScore(r.supplier_gstin, r.supplier_name)
        s.name = s.name or r.supplier_name
        return s

    for r in books:
        if not r.supplier_gstin:
            continue
        s = sup(r)
        s.books_docs += 1
        s.books_itc += r.signed("itc")
    for r in gstr2b:
        s = sup(r)
        s.gstr2b_docs += 1
        s.gstr2b_itc += r.signed("itc")
        lag = _months(r.period) - _months(f"{r.invoice_date:%Y-%m}") if r.period else 0
        if lag >= 1:
            s.late_docs += 1
            s.max_lag = max(s.max_lag, lag)
        if r.itc_availability == "N":
            s.unavailable += 1
        if r.is_amendment:
            s.amended += 1
    # the last line each books document appeared on, across the months
    last: dict[int, ReconLine] = {}
    for lines in monthly_lines:
        for ln in lines:
            if ln.books is not None and ln.books.db_id is not None:
                last[ln.books.db_id] = ln
    for ln in last.values():
        b = ln.books
        if not b.supplier_gstin:
            continue
        s = sup(b)
        if ln.category == Category.MISSING_IN_2B:
            s.missing_docs += 1
            s.itc_at_risk += b.signed("itc")
        elif ln.category in VALUE_DIFFERENCES:
            s.mismatched += 1
    for s in out.values():
        s.deduct("missing", s.missing_docs, s.books_docs,
                 f"{s.missing_docs} of {s.books_docs} books document(s) still missing in GSTR-2B "
                 f"(ITC ₹{s.itc_at_risk:,.2f} at risk)")
        s.deduct("late", s.late_docs, s.gstr2b_docs,
                 f"{s.late_docs} of {s.gstr2b_docs} document(s) reported in a later month's GSTR-2B "
                 f"(up to {s.max_lag} month(s) late)")
        s.deduct("mismatch", s.mismatched, s.books_docs, f"{s.mismatched} document(s) with value / tax differences")
        s.deduct("unavailable", s.unavailable, s.gstr2b_docs,
                 f"{s.unavailable} document(s) marked 'ITC not available' in GSTR-2B")
        s.deduct("amended", s.amended, s.gstr2b_docs, f"{s.amended} amended document(s)")
        s.score = max(s.score, 0)
        s.band = next(name for name, floor in BANDS if s.score >= floor)
        if s.books_docs + s.gstr2b_docs < 3:
            s.band = "Too little data"
        if not s.reasons:
            s.reasons.append("No issues found in the data imported")
        s.followup = (followups or {}).get(s.gstin, "")
    order = {"High": 0, "Medium": 1, "Low": 2, "Too little data": 3}
    return sorted(out.values(), key=lambda s: (order[s.band], -s.itc_at_risk, s.score, s.gstin))
