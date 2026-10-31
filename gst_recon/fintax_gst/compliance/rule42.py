"""Reversal of common input tax credit – Rules 42 (inputs and input services) and 43 (capital goods), CGST
Rules 2017.

Rule 42, for a tax period:

* C1 = ITC of the period after blocked credit (section 17(5)) – the Table 4 working;
* T1 = ITC used exclusively for non-business purposes, T2 = exclusively for exempt supplies (both not
  credited), T4 = exclusively for taxable supplies (incl. zero-rated) – entered by the user;
* C2 = C1 − T1 − T2 − T4: common credit;
* D1 = E ÷ F × C2, with E the exempt turnover (exempt, nil-rated and non-GST supplies) and F the total
  turnover of the period; when the period has no turnover, E and F of the last period that had one are used;
* D2 = 5 % of C2 when the common inputs are also used for non-business purposes;
* D1 + D2 (and T1 + T2 if they were claimed) are reversed – GSTR-3B Table 4(B)(1).

After the year (by the September return, rule 42(2)) D1 and D2 are worked out again with the year's turnover
and common credit: a shortfall is reversed with interest from 1 April of the next year, an excess is claimed
again.

Rule 43: the ITC of each common capital good is spread over 60 months (Tm = Tc ÷ 60) from the month of
purchase; every month Te = E ÷ F × Tr, with Tr the sum of Tm of the goods still within their 60 months, is
reversed.

Tax heads: reversals are shared among IGST / CGST / SGST / cess in the proportion of the common credit (or of
the capital goods' ITC). All figures are a working for the professional's review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
HEADS = ("igst", "cgst", "sgst", "cess")
NON_BUSINESS_RATE = Decimal("0.05")
LIFE_MONTHS = 60


def q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def months_since(start: date, period: str) -> int:
    """0 for the month of ``start``, 1 for the next month, …"""
    y, m = int(period[:4]), int(period[5:])
    return (y - start.year) * 12 + (m - start.month)


def _split(total: Decimal, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    base = sum(weights.values(), ZERO)
    if base <= 0 or total == 0:
        return {h: ZERO for h in HEADS}
    out = {h: q2(total * weights[h] / base) for h in HEADS}
    biggest = max(HEADS, key=lambda h: weights[h])
    out[biggest] += total - sum(out.values(), ZERO)  # rounding difference on the largest head
    return out


@dataclass
class Rule42Month:
    period: str
    c1: dict[str, Decimal]  # ITC after blocked credit, per head
    t1: Decimal = ZERO
    t2: Decimal = ZERO
    t4: Decimal = ZERO
    exempt: Decimal = ZERO  # E
    turnover: Decimal = ZERO  # F
    ratio_from: str = ""  # period whose turnover gave E / F (when not this one)
    non_business: bool = False
    capital_goods: list[tuple[str, dict[str, Decimal]]] = field(default_factory=list)  # (description, Tm per head)

    @property
    def c1_total(self) -> Decimal:
        return sum(self.c1.values(), ZERO)

    @property
    def c2(self) -> Decimal:
        return max(self.c1_total - self.t1 - self.t2 - self.t4, ZERO)

    @property
    def ratio(self) -> Decimal:
        return self.exempt / self.turnover if self.turnover else ZERO

    @property
    def d1(self) -> Decimal:
        return q2(self.ratio * self.c2)

    @property
    def d2(self) -> Decimal:
        return q2(self.c2 * NON_BUSINESS_RATE) if self.non_business else ZERO

    @property
    def te(self) -> dict[str, Decimal]:
        """Rule 43 reversal of the month, per head."""
        tr = {h: sum((tm[h] for _d, tm in self.capital_goods), ZERO) for h in HEADS}
        return {h: q2(self.ratio * tr[h]) for h in HEADS}

    @property
    def reversal(self) -> dict[str, Decimal]:
        """Rule 42 (D1 + D2) and Rule 43 (Te) reversals per head – GSTR-3B 4(B)(1)."""
        r42 = _split(self.d1 + self.d2, self.c1)
        te = self.te
        return {h: r42[h] + te[h] for h in HEADS}

    @property
    def total(self) -> Decimal:
        return sum(self.reversal.values(), ZERO)


def capital_good_tm(itc: dict[str, Decimal], bought: date, period: str) -> dict[str, Decimal] | None:
    """Tm of a capital good in ``period`` – None when the period is before the purchase or after 60 months."""
    n = months_since(bought, period)
    if n < 0 or n >= LIFE_MONTHS:
        return None
    return {h: q2(itc.get(h, ZERO) / LIFE_MONTHS) for h in HEADS}


@dataclass
class Rule42Year:
    fy: str
    months: list[Rule42Month]
    exempt: Decimal  # E of the year
    turnover: Decimal  # F of the year

    @property
    def c2(self) -> Decimal:
        return sum((m.c2 for m in self.months), ZERO)

    @property
    def d1(self) -> Decimal:
        return q2(self.exempt / self.turnover * self.c2) if self.turnover else ZERO

    @property
    def d2(self) -> Decimal:
        return q2(sum((m.c2 * NON_BUSINESS_RATE for m in self.months if m.non_business), ZERO))

    @property
    def reversed_monthly(self) -> Decimal:
        return sum((m.d1 + m.d2 for m in self.months), ZERO)

    @property
    def difference(self) -> Decimal:
        """Positive: more to reverse (with interest from 1 April); negative: to claim again."""
        return self.d1 + self.d2 - self.reversed_monthly

    def interest(self, paid_on: date) -> Decimal:
        """18 % a year on a shortfall, from 1 April after the year to ``paid_on`` (rule 42(2)(a))."""
        if self.difference <= 0:
            return ZERO
        start = date(int(self.fy[:4]) + 1, 4, 1)
        days = max((paid_on - start).days, 0)
        return q2(self.difference * Decimal("0.18") * days / 365)
