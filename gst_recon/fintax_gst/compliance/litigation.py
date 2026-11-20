"""Time limits and pre-deposit for GST disputes (CGST Act), used by the litigation tracker.

* Appeal to the Appellate Authority (section 107, APL-01): within 3 months of the order being communicated; the
  authority may allow one more month for sufficient cause. Pre-deposit: the tax admitted in full and 10 % of the
  remaining tax in dispute (maximum ₹20 crore, as amended in 2024).
* Appeal to the Appellate Tribunal (section 112, APL-05): within 3 months of the appellate order; a further 3
  months may be condoned. Pre-deposit: a further 10 % of the remaining tax in dispute (maximum ₹20 crore).
* Appeal to the High Court (section 117): within 180 days.
Penalty-only orders: pre-deposit of 10 % of the penalty (from 2025). The amounts and limits change by amendment –
the working shows the basis so it can be checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..core.money import ZERO

PAISA = Decimal("0.01")
CAP = Decimal("200000000")  # ₹20 crore
STAGES = {"SCN": "Show-cause notice", "ORDER": "Order received (appeal not yet filed)",
          "APPEAL": "Appeal before Appellate Authority", "TRIBUNAL": "Appeal before Tribunal",
          "COURT": "High Court / Supreme Court"}
STATUSES = ("OPEN", "WON", "LOST", "SETTLED", "WITHDRAWN")


def _add_months(d: date, months: int) -> date:
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


@dataclass
class Limitation:
    last_date: date
    condonable_to: date | None
    basis: str


def limitation(next_step: str, order_date: date) -> Limitation | None:
    """Last date to file the next appeal after an order communicated on ``order_date``."""
    if next_step == "APPEAL":
        return Limitation(_add_months(order_date, 3), _add_months(order_date, 4),
                          "section 107: 3 months from communication (+1 month on sufficient cause)")
    if next_step == "TRIBUNAL":
        return Limitation(_add_months(order_date, 3), _add_months(order_date, 6),
                          "section 112: 3 months from the appellate order (+3 months may be condoned)")
    if next_step == "COURT":
        return Limitation(order_date + timedelta(days=180), None, "section 117: 180 days")
    return None


def next_step(stage: str) -> str | None:
    return {"ORDER": "APPEAL", "APPEAL": "TRIBUNAL", "TRIBUNAL": "COURT"}.get(stage)


def pre_deposit(for_step: str, tax: Decimal, tax_admitted: Decimal = ZERO, penalty: Decimal = ZERO) -> tuple[Decimal,
                                                                                                              str]:
    disputed = max(tax - tax_admitted, ZERO)
    if for_step not in ("APPEAL", "TRIBUNAL"):
        return ZERO, "no statutory pre-deposit"
    if disputed == 0 and penalty > 0:
        amt = (penalty * Decimal("0.10")).quantize(PAISA, rounding=ROUND_HALF_UP)
        return amt, "10 % of the penalty (penalty-only order)"
    pct = (disputed * Decimal("0.10")).quantize(PAISA, rounding=ROUND_HALF_UP)
    capped = min(pct, CAP)
    total = capped + (tax_admitted if for_step == "APPEAL" else ZERO)
    basis = ("tax admitted in full + " if for_step == "APPEAL" and tax_admitted else "") + \
        f"10 % of the tax in dispute (₹{disputed:,.2f})" + (" – capped at ₹20 crore" if pct > CAP else "") + \
        (" – in addition to the 10 % paid for the first appeal" if for_step == "TRIBUNAL" else "")
    return total, basis
