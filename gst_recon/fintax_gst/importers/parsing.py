"""Cell-level parsers for dates, document types and flags."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ..core.models import DocType
from ..core.money import is_blank

_DATE_FORMATS = (
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d-%B-%Y",
    "%d %B %Y", "%d/%b/%Y", "%d-%m-%y", "%d/%m/%y", "%Y/%m/%d", "%d%m%Y",
)
_EXCEL_EPOCH = date(1899, 12, 30)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}


class DateParseError(ValueError):
    pass


def parse_date(value) -> date | None:
    """Parse a date. Text dates are read day-first, as is the Indian convention."""
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):  # pandas Timestamp
        return value.to_pydatetime().date()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20000 <= value <= 80000:  # Excel serial date
            return _EXCEL_EPOCH + timedelta(days=int(value))
        text = str(int(value)) if float(value).is_integer() else str(value)
    else:
        text = str(value).strip()
    text = re.sub(r"\s+00:00(:00)?$", "", text)
    text = text.replace("T00:00:00", "")
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if 1990 <= parsed.year <= 2100:
            return parsed
    raise DateParseError(f"unrecognised date: {value!r}")


def parse_period(value) -> str | None:
    """Accept 2025-04, 04-2025, 042025 (GSTN rtnprd), 'April 2025', 'Apr-25'."""
    if is_blank(value):
        return None
    text = str(value).strip()
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    elif (m := re.fullmatch(r"(\d{1,2})[-/](\d{4})", text)):
        mo, y = int(m.group(1)), int(m.group(2))
    elif (m := re.fullmatch(r"(\d{2})(\d{4})", text)):
        mo, y = int(m.group(1)), int(m.group(2))
    elif (m := re.fullmatch(r"([A-Za-z]+)[\s\-'/,]*(\d{2,4})", text)):
        name = m.group(1).lower()
        match = [n for k, n in MONTHS.items() if k.startswith(name[:3])]
        if not match:
            return None
        mo, y = match[0], int(m.group(2))
        if y < 100:
            y += 2000
    else:
        return None
    if not 1 <= mo <= 12:
        return None
    return f"{y:04d}-{mo:02d}"


def parse_doc_type(value) -> DocType | None:
    """Document type as reported by the supplier (GSTR-2B convention)."""
    if is_blank(value):
        return None
    text = re.sub(r"[^a-z]", "", str(value).lower())
    if text in ("c", "cn", "crn", "cr", "creditnote", "credit", "cdnrc"):
        return DocType.CREDIT_NOTE
    if text in ("d", "dn", "dbn", "dr", "debitnote", "debit"):
        return DocType.DEBIT_NOTE
    if text in ("i", "inv", "invoice", "taxinvoice", "r", "regular", "b2b", "bill", "purchase", "purchaseinvoice"):
        return DocType.INVOICE
    if "credit" in text:
        return DocType.CREDIT_NOTE
    if "debit" in text:
        return DocType.DEBIT_NOTE
    if "invoice" in text or "regular" in text or "sez" in text or "deemed" in text:
        return DocType.INVOICE
    return None


def tally_voucher_doc_type(value) -> DocType | None:
    """Map a TallyPrime voucher type (buyer's books) to the supplier's document type.

    A purchase return is entered by the buyer as a *Debit Note* voucher and
    appears in GSTR-2B as the supplier's *Credit Note*, and vice versa.
    """
    if is_blank(value):
        return None
    text = str(value).strip().lower()
    if "debit" in text:
        return DocType.CREDIT_NOTE
    if "credit" in text:
        return DocType.DEBIT_NOTE
    if "purchase" in text or "journal" in text or "invoice" in text:
        return DocType.INVOICE
    return None


def parse_bool(value) -> bool:
    if is_blank(value):
        return False
    return str(value).strip().lower() in ("y", "yes", "true", "1")


def parse_text(value) -> str:
    if is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
