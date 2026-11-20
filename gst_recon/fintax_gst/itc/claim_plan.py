"""ITC claim plan for a GSTR-3B month, across months.

Every purchase-register document not yet claimed (from the previous financial year onwards, up to the month) is
looked for in every GSTR-2B imported up to the month – so an April invoice that the supplier reports only in
June's GSTR-2B moves from "hold" to "claim now" in June. The plan sorts each document into:

* **claim now** – in a GSTR-2B up to the month, the tax agrees (within the tolerance), no open review flag, still
  within the section 16(4) time limit;
* **check first** – in GSTR-2B but GSTR-2B shows less tax than the books, or a review flag is open (blocked
  credit, etc.); the reviewer decides;
* **hold** – not yet in any GSTR-2B (the supplier has not reported it): carried forward with its age and the last
  date to claim; flagged when the time limit is near;
* **time-barred** – not claimed and the section 16(4) date has passed;
* **written off** – the firm decided not to claim it (with the reason); it stays listed for the record.

Separately: documents in GSTR-2B up to the month that are not in the books at all (to ask the client).
Nothing is claimed by the plan itself; the user records the claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.invoice_no import loose_invoice_no
from ..core.models import DocType, InvoiceRecord
from ..core.money import ZERO
from .deadlines import itc_deadline

CLAIM, CHECK, HOLD, BARRED, WRITTEN_OFF = "Claim now", "Check first", "Hold", "Time-barred", "Written off"
ORDER = [CLAIM, CHECK, HOLD, BARRED, WRITTEN_OFF]
NEAR_DAYS = 60


@dataclass
class PlanLine:
    doc: InvoiceRecord
    bucket: str
    itc: Decimal  # books ITC (credit notes negative)
    in_2b: InvoiceRecord | None = None
    reason: str = ""
    deadline: date | None = None
    days_left: int | None = None
    months_pending: int = 0

    @property
    def gstr2b_period(self) -> str:
        return self.in_2b.period if self.in_2b else ""


@dataclass
class ClaimPlan:
    period: str
    lines: list[PlanLine] = field(default_factory=list)
    not_in_books: list[InvoiceRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def bucket(self, name: str) -> list[PlanLine]:
        return [ln for ln in self.lines if ln.bucket == name]

    def total(self, name: str) -> Decimal:
        return sum((ln.itc for ln in self.bucket(name)), ZERO)


def _key(r: InvoiceRecord) -> tuple:
    note = r.doc_type == DocType.CREDIT_NOTE
    return (r.supplier_gstin, loose_invoice_no(r.invoice_no), note)


def _tax(r: InvoiceRecord) -> Decimal:
    return r.igst + r.cgst + r.sgst + r.cess


def _months(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:])


def build_plan(period: str, books: list[InvoiceRecord], gstr2b: list[InvoiceRecord], claimed: set[int],
               flags: dict[int, str], written_off: dict[int, str], as_of: date,
               tolerance: Decimal = Decimal("1.00"), unreviewed_periods: set[str] | None = None) -> ClaimPlan:
    """``claimed``: books document ids with a claim recorded; ``flags``: id -> open high/medium review flags;
    ``written_off``: id -> reason."""
    plan = ClaimPlan(period)
    by_key: dict[tuple, list[InvoiceRecord]] = {}
    for g in sorted(gstr2b, key=lambda x: x.period):
        if g.period <= period:
            by_key.setdefault(_key(g), []).append(g)
    used_2b: set[int] = set()
    for b in sorted(books, key=lambda x: (x.period, x.invoice_date, x.invoice_no)):
        if b.period > period or not b.db_id:
            continue
        found = next((g for g in by_key.get(_key(b), []) if id(g) not in used_2b), None)
        if found is not None:
            used_2b.add(id(found))
        if b.db_id in claimed:
            continue
        sign = -1 if b.doc_type == DocType.CREDIT_NOTE else 1
        deadline = None if b.doc_type == DocType.CREDIT_NOTE else itc_deadline(b.invoice_date)[0]
        ln = PlanLine(b, HOLD, _tax(b) * sign, found, deadline=deadline,
                      days_left=(deadline - as_of).days if deadline else None,
                      months_pending=max(_months(b.period, period), 0))
        if b.db_id in written_off:
            ln.bucket, ln.reason = WRITTEN_OFF, written_off[b.db_id]
        elif deadline is not None and as_of > deadline:
            ln.bucket = BARRED
            ln.reason = f"section 16(4) time limit was {deadline:%d-%m-%Y}"
        elif found is None:
            ln.reason = "not yet in GSTR-2B – supplier has not reported it"
            if ln.months_pending:
                ln.reason += f" ({ln.months_pending} month(s))"
            if ln.days_left is not None and ln.days_left <= NEAR_DAYS:
                ln.reason += f"; claim by {deadline:%d-%m-%Y} – follow up now"
        elif b.db_id in flags:
            ln.bucket, ln.reason = CHECK, f"review flag open: {flags[b.db_id]}"
        elif str(found.itc_availability or "").strip().upper() in ("N", "NO"):
            ln.bucket, ln.reason = CHECK, "GSTR-2B marks this ITC as not available"
        elif _tax(found) + tolerance < _tax(b):
            ln.bucket = CHECK
            ln.reason = (f"GSTR-2B shows tax ₹{_tax(found):,.2f} against ₹{_tax(b):,.2f} in the books – claim the "
                         "GSTR-2B figure or wait for the supplier's amendment")
        else:
            ln.bucket = CLAIM
            ln.reason = ("in GSTR-2B of this month" if found.period == period else
                         f"in GSTR-2B of {found.period}") + (
                " – carried forward from " + b.period if b.period < period else "")
            if unreviewed_periods and b.period in unreviewed_periods:
                ln.reason += " (month not reconciled – review flags not checked)"
        plan.lines.append(ln)
    books_keys = {_key(b) for b in books}
    plan.not_in_books = [g for gl in by_key.values() for g in gl
                         if _key(g) not in books_keys and g.period[:4] >= str(int(period[:4]) - 1)]
    plan.lines.sort(key=lambda ln: (ORDER.index(ln.bucket), ln.days_left if ln.days_left is not None else 99999,
                                    ln.doc.supplier_gstin, ln.doc.invoice_no))
    return plan
