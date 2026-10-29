"""Section 16(4) time limit for availing input tax credit."""
from __future__ import annotations

from datetime import date


def itc_deadline(doc_date: date) -> tuple[date, str]:
    """Last date to avail ITC on an invoice or debit note dated ``doc_date``.

    * FY 2021-22 onwards: 30 November following the end of the financial year
      (Section 16(4) as amended by Finance Act 2022, w.e.f. 01-10-2022).
    * Earlier years: due date of the GSTR-3B for September following the end of
      the financial year (taken as 20 October); Section 16(5) relaxes FY 2017-18 to
      2020-21 for returns filed up to 30-11-2021.

    In both cases the date of furnishing the annual return applies if it is earlier.
    The time limit for a debit note runs from the debit note's own date.
    """
    fy_start = doc_date.year if doc_date.month >= 4 else doc_date.year - 1
    if fy_start >= 2021:
        return (date(fy_start + 1, 11, 30),
                "30 November following the end of the financial year (Section 16(4), as amended w.e.f. 01-10-2022), "
                "or the annual return date if earlier")
    return (date(fy_start + 1, 10, 20),
            "Due date of September GSTR-3B following the financial year (Section 16(4) before amendment); "
            "see Section 16(5) for FY 2017-18 to 2020-21")
