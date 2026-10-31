"""GSTR-9 Tables 15 and 16 – figures the application cannot derive, entered by the preparer.

* Table 15 – refunds and demands (from the refund and demand records of the year).
* Table 16 – supplies received from composition taxpayers, deemed supplies to job workers
  (section 143) and goods sent on approval and not returned.

Each figure is an item such as ``15E-I`` (Table 15E, integrated tax), stored with a note and
audited like the GSTR-9C inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal(0)
TABLE15 = [
    ("15A", "Total refund claimed"), ("15B", "Total refund sanctioned"), ("15C", "Total refund rejected"),
    ("15D", "Total refund pending"), ("15E", "Total demand of taxes"),
    ("15F", "Total taxes paid in respect of E above"), ("15G", "Total demands pending out of E above"),
]
TABLE15_COLUMNS = [("C", "Central tax"), ("S", "State / UT tax"), ("I", "Integrated tax"), ("X", "Cess"),
                   ("N", "Interest"), ("P", "Penalty"), ("L", "Late fee / others")]
TABLE16 = [
    ("16A", "Supplies received from composition taxpayers"),
    ("16B", "Deemed supply under section 143 (goods sent to job workers not returned in time)"),
    ("16C", "Goods sent on approval basis but not returned"),
]
TABLE16_COLUMNS = [("T", "Taxable value"), ("C", "Central tax"), ("S", "State / UT tax"), ("I", "Integrated tax"),
                   ("X", "Cess")]
ENTERED_ITEMS = [f"{code}-{col}" for code, _l in TABLE15 for col, _c in TABLE15_COLUMNS] + \
    [f"{code}-{col}" for code, _l in TABLE16 for col, _c in TABLE16_COLUMNS if code != "16A" or col == "T"]
ITEM_LABELS = {f"{code}-{col}": f"{label} – {cname}" for code, label in TABLE15 for col, cname in TABLE15_COLUMNS} | \
    {f"{code}-{col}": f"{label} – {cname}" for code, label in TABLE16 for col, cname in TABLE16_COLUMNS}


@dataclass
class EnteredRow:
    code: str
    label: str
    values: dict[str, Decimal] = field(default_factory=dict)  # column letter -> amount
    notes: list[str] = field(default_factory=list)


def entered_tables(inputs: dict[str, tuple[Decimal | None, str]]) -> tuple[list[EnteredRow], list[EnteredRow]]:
    def rows(table, columns):
        out = []
        for code, label in table:
            row = EnteredRow(code, label)
            for col, _c in columns:
                amount, note = inputs.get(f"{code}-{col}", (None, ""))
                if f"{code}-{col}" in ENTERED_ITEMS:
                    row.values[col] = amount if amount is not None else ZERO
                if note:
                    row.notes.append(note)
            out.append(row)
        return out

    return rows(TABLE15, TABLE15_COLUMNS), rows(TABLE16, TABLE16_COLUMNS)
