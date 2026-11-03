"""Interest under section 50 and late fees under section 47 of the CGST Act.

**Interest (18% p.a.).**

* *Late GSTR-3B* (section 50(1) proviso, rule 88B(1)): interest only on the tax paid
  in cash. It runs from the day after the due date to the date of filing; the cash is
  debited when the return is filed.
* *Tax not paid* (section 50(1)): for example GSTR-1 tax above GSTR-3B. Interest runs
  on the whole amount, from the day after the GSTR-3B due date to the date of payment
  (DRC-03), or to the working's *as of* date while unpaid.
* *ITC wrongly availed and utilised* (section 50(3), rule 88B(3)): interest runs from
  the date of utilisation to the date of reversal or payment. Utilisation happens when
  the credit-ledger balance falls below the wrongly availed amount. Ledger balances are
  not imported, so the working assumes utilisation when the period's GSTR-3B was filed.
  That makes the figure an **upper limit**, and it is labelled as one.

Interest = amount × 18% × days / 365, where days = end date − due date (the first day
counted is the day after the due date).

**Late fees, per day of delay and per tax head (CGST, and SGST/UTGST).**

GSTR-1 and GSTR-3B (Notifications 19/2021 and 20/2021-CT, as amended), for tax periods
from June 2021:

| Case | Per day (each head) | Maximum (each head) |
|---|---|---|
| Nil return | ₹10 | ₹250 |
| AATO up to ₹1.5 crore | ₹25 | ₹1,000 |
| AATO ₹1.5–5 crore | ₹25 | ₹2,500 |
| AATO above ₹5 crore | ₹25 | ₹5,000 |

Earlier periods carried amnesties and waivers that vary by period, so they are not
computed.

GSTR-9 (Notification 07/2023-CT), from FY 2022-23:

| AATO | Per day (each head) | Maximum (each head) |
|---|---|---|
| up to ₹5 crore | ₹25 | 0.02% of the turnover in the state |
| ₹5–20 crore | ₹50 | 0.02% of the turnover in the state |
| above ₹20 crore | ₹100 | 0.25% of the turnover in the state |

GSTR-9 is optional up to ₹2 crore of AATO, so no late fee is computed below that.

When the AATO has not been entered, the highest slab is used and the working says so.
The figures are a working for the professional; the amounts the portal levies are the
ones to pay.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

RATE = Decimal("18")
CRORE = Decimal("10000000")
LATE_FEE_FROM = "2021-06"
GSTR9_LATE_FEE_FROM = "2022-23"


def interest(amount: Decimal, due: date, end: date, rate: Decimal = RATE) -> tuple[int, Decimal]:
    """(days, interest) on ``amount`` for payment on ``end`` against a due date ``due``."""
    days = max((end - due).days, 0)
    if amount <= 0 or not days:
        return days, Decimal("0.00")
    return days, (amount * rate / Decimal(100) * days / Decimal(365)).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass
class LateFee:
    days: int
    cgst: Decimal
    sgst: Decimal
    basis: str  # how the cap was chosen

    @property
    def total(self) -> Decimal:
        return self.cgst + self.sgst


def _slab(aato: Decimal | None, nil: bool) -> tuple[Decimal, Decimal, str]:
    if nil:
        return Decimal(10), Decimal(250), "nil return"
    if aato is None:
        return Decimal(25), Decimal(5000), "AATO not entered – highest cap used"
    if aato <= Decimal("1.5") * CRORE:
        return Decimal(25), Decimal(1000), "AATO up to ₹1.5 crore"
    if aato <= 5 * CRORE:
        return Decimal(25), Decimal(2500), "AATO ₹1.5–5 crore"
    return Decimal(25), Decimal(5000), "AATO above ₹5 crore"


def late_fee(period: str, due: date, filed: date, nil: bool, aato: Decimal | None) -> LateFee | None:
    """GSTR-1 / GSTR-3B late fee; ``None`` for periods before June 2021 (not computed)."""
    if period < LATE_FEE_FROM:
        return None
    days = max((filed - due).days, 0)
    per_day, cap, basis = _slab(aato, nil)
    each = min(per_day * days, cap)
    return LateFee(days, each, each, basis)


def gstr9_late_fee(fy: str, due: date, filed: date, aato: Decimal | None,
                   turnover: Decimal) -> LateFee | None:
    """GSTR-9 late fee; ``None`` before FY 2022-23 or when GSTR-9 is optional (AATO up to ₹2 crore)."""
    if fy < GSTR9_LATE_FEE_FROM or (aato is not None and aato <= 2 * CRORE):
        return None
    days = max((filed - due).days, 0)
    if aato is not None and aato <= 5 * CRORE:
        per_day, pct, basis = Decimal(25), Decimal("0.02"), "AATO up to ₹5 crore"
    elif aato is not None and aato <= 20 * CRORE:
        per_day, pct, basis = Decimal(50), Decimal("0.02"), "AATO ₹5–20 crore"
    else:
        per_day, pct, basis = Decimal(100), Decimal("0.25"), (
            "AATO above ₹20 crore" if aato is not None else "AATO not entered – highest slab used")
    cap = (max(turnover, Decimal(0)) * pct / Decimal(100)).quantize(Decimal("1"), ROUND_HALF_UP)
    each = min(per_day * days, cap)
    return LateFee(days, each, each, f"{basis}; cap {pct}% of turnover ₹{turnover:,.0f}")
