"""Decimal-only money handling. Floats never enter a calculation."""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
PAISE = Decimal("0.01")

_STRIP = re.compile(r"(₹|INR|Rs\.?|\s|,)", re.IGNORECASE)
_DRCR = re.compile(r"(DR|CR)\.?$", re.IGNORECASE)


class AmountParseError(ValueError):
    pass


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() in ("", "-", "--", "nan", "NaN", "None"):
        return True
    return False


def parse_amount(value) -> Decimal | None:
    """Parse a money value from Excel/CSV/JSON into a Decimal.

    Returns None for blank cells. Accepts Indian grouping (1,23,456.50), a
    rupee prefix, accounting negatives "(1,234.00)" and a trailing minus.
    A trailing Dr/Cr marker is removed without changing the sign; register
    layouts that use Dr/Cr for sign are not supported implicitly.
    """
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise AmountParseError(f"boolean is not an amount: {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isinf(value):
            raise AmountParseError("infinite amount")
        # repr() gives the shortest round-tripping string, e.g. 1234.56
        return Decimal(repr(value))
    text = str(value).strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = _STRIP.sub("", text)
    text = _DRCR.sub("", text)
    if text.endswith("-"):
        negative, text = not negative, text[:-1]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    if text.startswith("+"):
        text = text[1:]
    if text == "":
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise AmountParseError(f"not a valid amount: {value!r}") from exc
    if not amount.is_finite():
        raise AmountParseError(f"not a valid amount: {value!r}")
    return -amount if negative else amount


def q2(amount: Decimal | None) -> Decimal:
    """Round half-up to paise for presentation."""
    if amount is None:
        return ZERO.quantize(PAISE)
    return amount.quantize(PAISE, rounding=ROUND_HALF_UP)


def dsum(values) -> Decimal:
    total = ZERO
    for v in values:
        if v is not None:
            total += v
    return total


def fmt_inr(amount: Decimal | None) -> str:
    """Format with Indian digit grouping: 12,34,567.89."""
    amount = q2(amount)
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"
