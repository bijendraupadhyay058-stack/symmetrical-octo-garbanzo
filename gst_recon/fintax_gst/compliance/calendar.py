"""GST return due dates: monthly filers and the QRMP scheme, with recorded extensions.

Standard dates (CGST Act / Rules as amended):

* Monthly filers – GSTR-1 by the 11th and GSTR-3B by the 20th of the next month.
* QRMP (quarterly) – IFF (optional) by the 13th for the first two months of a quarter,
  tax by PMT-06 by the 25th for those months, GSTR-1 by the 13th and GSTR-3B by the
  22nd or 24th of the month after the quarter, depending on the state (Notification
  76/2020-CT, as amended).
* GSTR-9 and GSTR-9C – 31 December after the financial year.

Extensions are notified by CBIC from time to time, sometimes for some states or
districts only. They are never guessed: the user records them (``DueOverride``) with
the notification reference, and they then replace the standard date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

#: States/UTs whose QRMP GSTR-3B is due on the 22nd; all others on the 24th.
QRMP_22ND_STATES = frozenset({"22", "23", "24", "25", "26", "27", "29", "30", "31", "32", "33", "34", "35", "36", "37"})
RETURN_TYPES = ("GSTR-1", "IFF", "GSTR-3B", "PMT-06", "GSTR-9", "GSTR-9C")


@dataclass(frozen=True)
class DueOverride:
    return_type: str
    period: str  # YYYY-MM (for quarterly returns the last month of the quarter; for GSTR-9 the FY, e.g. 2025-26)
    due: date
    reference: str  # notification / circular number
    state_codes: frozenset[str] = frozenset()  # empty = all states

    def applies(self, return_type: str, period: str, state_code: str) -> bool:
        return (self.return_type == return_type and self.period == period
                and (not self.state_codes or state_code in self.state_codes))


@dataclass(frozen=True)
class DueItem:
    return_type: str
    period: str
    due: date
    basis: str  # "standard" or the extension reference
    optional: bool = False

    @property
    def extended(self) -> bool:
        return self.basis != "standard"


def is_quarterly(frequency: str) -> bool:
    return frequency.strip().lower().startswith(("quarter", "qrmp"))


def _next_month(period: str, day: int) -> date:
    y, m = int(period[:4]), int(period[5:])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(y, m, day)


def quarter_end(period: str) -> bool:
    return int(period[5:]) in (3, 6, 9, 12)


def due_items(period: str, frequency: str = "Monthly", state_code: str = "",
              overrides: tuple[DueOverride, ...] | list[DueOverride] = ()) -> list[DueItem]:
    """Returns due for the tax period ``period`` (YYYY-MM)."""
    items: list[tuple[str, date, bool]] = []
    if is_quarterly(frequency):
        if quarter_end(period):
            items += [("GSTR-1", _next_month(period, 13), False),
                      ("GSTR-3B", _next_month(period, 22 if state_code in QRMP_22ND_STATES else 24), False)]
        else:
            items += [("IFF", _next_month(period, 13), True), ("PMT-06", _next_month(period, 25), False)]
    else:
        items += [("GSTR-1", _next_month(period, 11), False), ("GSTR-3B", _next_month(period, 20), False)]
    out = []
    for rtype, due, optional in items:
        ov = next((o for o in overrides if o.applies(rtype, period, state_code)), None)
        out.append(DueItem(rtype, period, ov.due if ov else due, ov.reference if ov else "standard", optional))
    return out


def annual_items(fy: str, state_code: str = "", overrides=()) -> list[DueItem]:
    due = date(int(fy[:4]) + 1, 12, 31)
    out = []
    for rtype in ("GSTR-9", "GSTR-9C"):
        ov = next((o for o in overrides if o.applies(rtype, fy, state_code)), None)
        out.append(DueItem(rtype, fy, ov.due if ov else due, ov.reference if ov else "standard",
                           optional=rtype == "GSTR-9C"))
    return out


def due_of(items: list[DueItem], return_type: str) -> DueItem | None:
    return next((i for i in items if i.return_type == return_type), None)
