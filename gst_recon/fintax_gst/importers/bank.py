"""Bank statements (Excel or CSV as downloaded from net banking) and the GST payments in them.

The heading row is found by its words: a date, a narration / description / particulars column, and either
separate withdrawal (debit) and deposit (credit) columns or one amount column with a Dr / Cr column. A GST payment
is a debit whose narration mentions GST / CBIC / GSTN / CPIN, or carries a 14-digit CPIN.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, parse_amount
from .column_mapping import normalize_header
from .parsing import parse_date, parse_text
from .readers import UnsupportedFileError, read_csv, read_excel

COLS = {
    "date": ("txn date", "transaction date", "date", "value date", "tran date", "posting date"),
    "narration": ("narration", "description", "particulars", "remarks", "transaction details", "details",
                  "transaction remarks"),
    "reference": ("chq ref no", "chq no", "cheque no", "ref no", "reference no", "chq ref number", "utr no",
                  "transaction id", "reference"),
    "debit": ("withdrawal amt", "withdrawal amount", "withdrawals", "withdrawal", "debit amount", "debit", "dr amount",
              "debits"),
    "credit": ("deposit amt", "deposit amount", "deposits", "deposit", "credit amount", "credit", "cr amount",
               "credits"),
    "amount": ("amount", "transaction amount", "amount inr"),
    "drcr": ("dr cr", "cr dr", "type", "dr cr indicator", "debit credit"),
    "balance": ("closing balance", "balance", "running balance", "available balance"),
}
GST_WORDS = re.compile(r"\b(gst|cbic|gstn|cpin|gstin|igst|cgst|sgst|goods\s+and\s+services\s+tax)\b", re.I)
CPIN = re.compile(r"(?<!\d)(\d{14})(?!\d)")


@dataclass
class BankRow:
    row: str
    txn_date: date
    narration: str
    reference: str
    debit: Decimal
    credit: Decimal
    balance: Decimal | None

    @property
    def is_gst_payment(self) -> bool:
        return self.debit > 0 and bool(GST_WORDS.search(self.narration) or CPIN.search(self.narration + " " +
                                                                                       self.reference))

    @property
    def cpin(self) -> str:
        m = CPIN.search(f"{self.narration} {self.reference}")
        return m.group(1) if m else ""


def _amount(v) -> Decimal:
    try:
        return abs(parse_amount(v) or ZERO)
    except (ValueError, ArithmeticError):
        return ZERO


def read_statement(path: str | Path) -> tuple[list[BankRow], list[str]]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        tables = [read_csv(path, path.name)]
    elif suffix in (".xlsx", ".xls", ".xlsm"):
        tables = read_excel(path)
    else:
        raise UnsupportedFileError("Bank statement: use the Excel or CSV download from net banking")
    rows: list[BankRow] = []
    skipped: list[str] = []
    found = False
    for t in tables:
        cols = None
        for n, vals in t.rows:
            if cols is None:
                names = [normalize_header(v) for v in vals]
                c = {k: next((names.index(o) for o in opts if o in names), None) for k, opts in COLS.items()}
                if c["date"] is not None and c["narration"] is not None and (
                        (c["debit"] is not None and c["credit"] is not None) or c["amount"] is not None):
                    cols, found = c, True
                continue

            def cell(k, vals=vals):
                i = cols[k]
                return vals[i] if i is not None and i < len(vals) else None

            if not any(v not in (None, "") for v in vals):
                continue
            try:
                d = parse_date(cell("date"))
            except ValueError:
                d = None
            if d is None:
                text = " ".join(str(v) for v in vals if v not in (None, ""))[:60]
                if text and not re.search(r"opening|closing|total|statement|balance", text, re.I):
                    skipped.append(f"{t.name}!{n}: no date – not read ({text})")
                continue
            if cols["debit"] is not None:
                debit, credit = _amount(cell("debit")), _amount(cell("credit"))
            else:
                amt = _amount(cell("amount"))
                flag = parse_text(cell("drcr")).lower()
                is_debit = flag.startswith("d") or (not flag and str(cell("amount") or "").strip().startswith("-"))
                debit, credit = (amt, ZERO) if is_debit else (ZERO, amt)
            bal = cell("balance")
            try:
                balance = parse_amount(bal) if bal not in (None, "") else None
            except (ValueError, ArithmeticError):
                balance = None
            rows.append(BankRow(f"{t.name}!{n}", d, parse_text(cell("narration"))[:400],
                                parse_text(cell("reference"))[:80], debit, credit, balance))
    if not found:
        raise UnsupportedFileError(f"{path.name}: no bank statement found – it needs a date, a narration and the "
                                   "withdrawal / deposit (or amount) columns")
    return rows, skipped
