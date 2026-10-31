"""GSTR-9C Table 14 – ITC availed on expenses, and the expense-ledger import that fills it.

An expense ledger is a list of ledger heads with their value for the year and the ITC
on them (Tally "Group Summary" or any Excel/CSV with *Ledger/Expense head*, *Amount/Value*
and *ITC / Eligible ITC* columns). Each head is placed in a Table 14 row by keywords in its
name; heads that match nothing go to 14N (other miscellaneous expenses). The preview lists
every head with the row chosen, so the preparer can correct a row before saving.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, parse_amount
from ..importers.column_mapping import normalize_header
from ..importers.readers import UnsupportedFileError, read_csv, read_excel

TABLE14 = [
    ("14A", "Purchases"), ("14B", "Freight / carriage"), ("14C", "Power and fuel"), ("14D", "Imported material"),
    ("14E", "Rent and insurance"),
    ("14F", "Goods lost, stolen, destroyed, written off or disposed of by way of gift or free samples"),
    ("14G", "Royalties"), ("14H", "Employees' cost (salaries, wages, bonus etc.)"), ("14I", "Conveyance charges"),
    ("14J", "Bank charges"), ("14K", "Entertainment charges"), ("14L", "Stationery expenses (including postage)"),
    ("14M", "Repair and maintenance"), ("14N", "Other miscellaneous expenses"), ("14O", "Capital goods"),
    ("14P", "Any other expense 1"), ("14Q", "Any other expense 2"),
]
#: Input items per row: value (V), total ITC (T), eligible ITC availed (E), e.g. "14A-V".
TABLE14_INPUTS = [f"{code}-{part}" for code, _l in TABLE14 for part in ("V", "T", "E")]
KEYWORDS = [
    ("14D", r"import"), ("14M", r"repair|maintenance|upkeep"),
    ("14O", r"capital|machinery|plant|equipment|computer|furniture|vehicle|fixed asset"),
    ("14F", r"lost|stolen|destroy|written off|write off|free sample|gift"),
    ("14A", r"purchase|raw material|stock|consumable|packing material"),
    ("14B", r"freight|carriage|cartage|transport|logistic"),
    ("14C", r"power|fuel|electricity|diesel|petrol"), ("14E", r"rent|insurance|lease"), ("14G", r"royalt"),
    ("14H", r"salar|wage|bonus|staff|employee|payroll"), ("14I", r"conveyance|travel|taxi|cab"),
    ("14J", r"bank"), ("14K", r"entertain|hospitality|refreshment|food|catering"),
    ("14L", r"stationer|postage|printing|courier"),
]
_HEAD = ("ledger", "expense head", "particulars", "account", "head", "ledger name", "expense")
_VALUE = ("amount", "value", "debit", "closing balance", "expense value", "taxable value")
_ITC = ("itc", "gst credit", "input tax credit", "total itc", "itc total")
_ELIGIBLE = ("eligible itc", "itc availed", "eligible itc availed", "itc claimed")


def row_for(head: str) -> str:
    text = head.lower()
    for code, pattern in KEYWORDS:
        if re.search(pattern, text):
            return code
    return "14N"


@dataclass
class ExpenseLine:
    row: int
    head: str
    value: Decimal
    itc_total: Decimal
    itc_eligible: Decimal
    table_row: str


def read_expense_ledger(path: str | Path) -> list[ExpenseLine]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        tables = [read_csv(path, path.name)]
    elif suffix in (".xlsx", ".xlsm"):
        tables = read_excel(path)
    else:
        raise UnsupportedFileError("Use an Excel (.xlsx) or CSV expense ledger")
    for t in tables:
        for i, (_n, values) in enumerate(t.rows[:30]):
            names = [normalize_header(v) for v in values]

            def col(options):
                return next((names.index(o) for o in options if o in names), None)

            head, value = col(_HEAD), col(_VALUE)
            if head is None or value is None:
                continue
            itc, eligible = col(_ITC), col(_ELIGIBLE)
            out = []
            for n, vals in t.rows[i + 1:]:
                name = str(vals[head] if head < len(vals) else "").strip()
                if not name or name.lower().startswith(("total", "grand total")):
                    continue

                def amt(c):
                    return (parse_amount(vals[c]) or ZERO) if c is not None and c < len(vals) else ZERO

                total = amt(itc)
                out.append(ExpenseLine(n, name, amt(value), total, amt(eligible) if eligible is not None else total,
                                       row_for(name)))
            return out
    raise UnsupportedFileError("No heading row with a ledger/expense head and an amount column found")


def totals_by_row(lines: list[ExpenseLine]) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    out: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for x in lines:
        v, t, e = out.get(x.table_row, (ZERO, ZERO, ZERO))
        out[x.table_row] = (v + x.value, t + x.itc_total, e + x.itc_eligible)
    return out
