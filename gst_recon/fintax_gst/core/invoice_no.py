"""Invoice-number normalisation.

Two derived keys are produced; the original text is never modified.

* ``normalize_invoice_no`` – upper case, separators removed.
  ``INV/001/26``, ``inv-001-26`` and ``INV 001 26`` all become ``INV00126``.
* ``loose_invoice_no`` – additionally drops leading zeros of each digit run
  so ``INV-1-26`` and ``INV/001/26`` meet (``INV126``). Used only in the
  second matching pass and always reported as an invoice-number variation.
"""
from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s\-/\\._,#:'\"|]+")
_DIGITS = re.compile(r"\d+")


def clean_raw_invoice_no(value) -> str:
    """Text form of the source value. Excel often stores numeric invoice
    numbers as floats (1234.0); render those without the trailing .0."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_invoice_no(raw: str) -> str:
    return _SEPARATORS.sub("", raw or "").upper()


def loose_invoice_no(raw: str) -> str:
    return _DIGITS.sub(lambda m: str(int(m.group())), normalize_invoice_no(raw))


def same_text(a: str, b: str) -> bool:
    """True when two invoice numbers are textually identical apart from
    surrounding whitespace and letter case."""
    return (a or "").strip().upper() == (b or "").strip().upper()
