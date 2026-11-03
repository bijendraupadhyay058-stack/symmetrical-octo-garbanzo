"""Electronic cash ledger and electronic credit ledger downloaded from the GST portal (Excel or CSV).

The portal's downloads have one or more heading rows: a group heading ("Amount debited / credited",
"Balance available") over the tax heads (IGST, CGST, SGST/UTGST, Cess), and in the cash ledger a third row with
Tax / Interest / Penalty / Fee / Others / Total. For each head the "Total" column is used when there is one,
otherwise the columns of the head are added up. Credits are kept positive and debits negative. Rows without a
date are not ledger lines and are skipped; each is reported, nothing is dropped silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, parse_amount
from .column_mapping import normalize_header
from .parsing import parse_date, parse_text
from .readers import RawTable, UnsupportedFileError, read_csv, read_excel

HEADS = ("igst", "cgst", "sgst", "cess")
_HEAD_WORDS = {"igst": ("igst", "integrated tax"), "cgst": ("cgst", "central tax"),
               "sgst": ("sgst", "utgst", "state tax", "state ut tax", "sgst utgst"), "cess": ("cess",)}
_BAL = re.compile(r"\bbalance\b")


@dataclass
class LedgerLine:
    row: str
    entry_date: date | None
    reference: str
    tax_period: str
    description: str
    txn: str  # CR / DR / BAL
    amounts: dict[str, Decimal]
    balance: dict[str, Decimal] | None = None


@dataclass
class LedgerFile:
    ledger: str  # CASH / CREDIT
    lines: list[LedgerLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def closing(self) -> dict[str, Decimal] | None:
        for line in reversed(self.lines):
            if line.balance is not None:
                return line.balance
        return None


def _date(v) -> date | None:
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        return None


def _text(t: RawTable, rows: int = 12) -> str:
    return " ".join(str(v) for _n, vals in t.rows[:rows] for v in vals if v).lower()


def ledger_kind(tables: list[RawTable], name: str = "") -> str | None:
    """CASH / CREDIT when the file is an electronic ledger, else None."""
    text = (name.lower() + " " + " ".join(t.name.lower() + " " + _text(t) for t in tables))
    if "cash ledger" in text or "cashledger" in text or ("cpin" in text and "deposit" in text):
        return "CASH"
    if "credit ledger" in text or "creditledger" in text or "itc ledger" in text:
        return "CREDIT"
    return None


def _head_of(path: str) -> str | None:
    for h, words in _HEAD_WORDS.items():
        if any(re.search(rf"\b{w}\b", path) for w in words):
            return h
    return None


def _locate(t: RawTable) -> tuple[int, list[str]] | None:
    """Index of the last heading row and the combined heading of every column."""
    rows = t.rows[:40]
    for i, (_n, vals) in enumerate(rows):
        names = [normalize_header(v) for v in vals]
        if not any("date" in x for x in names) or not any(
                x.startswith(("description", "reference", "particulars")) for x in names):
            continue
        heads = [names]
        j = i + 1
        while j < len(rows) and len(heads) < 3:
            nxt = [normalize_header(v) for v in rows[j][1]]
            if any(_date(v) for v in rows[j][1] if v not in (None, "")) or not any(
                    _head_of(x) or x in ("tax", "interest", "penalty", "fee", "others", "total") for x in nxt):
                break
            heads.append(nxt)
            j += 1
        width = max(len(h) for h in heads)
        filled = []
        for k, h in enumerate(heads):
            h = h + [""] * (width - len(h))
            if k < len(heads) - 1:  # group headings span the columns to their right
                last = ""
                for c in range(width):
                    last = h[c] or last
                    h[c] = last
            filled.append(h)
        paths = [" | ".join(x for x in (filled[k][c] for k in range(len(filled))) if x) for c in range(width)]
        return i + len(heads) - 1, paths
    return None


def _columns(paths: list[str], balance: bool) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for h in HEADS:
        cols = [c for c, p in enumerate(paths) if _head_of(p) == h and bool(_BAL.search(p)) == balance]
        totals = [c for c in cols if paths[c].split(" | ")[-1] == "total"]
        if totals:
            cols = totals[:1]
        if cols:
            out[h] = cols
    return out


def _find(paths: list[str], *words: str) -> int | None:
    for w in words:
        for c, p in enumerate(paths):
            if p.split(" | ")[0].startswith(w) or p == w:
                return c
    return None


def read_ledger(path: str | Path, kind: str | None = None) -> LedgerFile:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        tables = [read_csv(path, path.name)]
    elif suffix in (".xlsx", ".xlsm", ".xls"):
        tables = read_excel(path)
    else:
        raise UnsupportedFileError("Electronic ledger: use the portal's Excel or CSV download")
    ledger = kind or ledger_kind(tables, path.name)
    if ledger not in ("CASH", "CREDIT"):
        raise UnsupportedFileError(f"{path.name} is not an electronic cash or credit ledger")
    out = LedgerFile(ledger)
    found = False
    for t in tables:
        located = _locate(t)
        if not located:
            continue
        last, paths = located
        amt, bal = _columns(paths, False), _columns(paths, True)
        if not amt and not bal:
            continue
        found = True
        c_date = _find(paths, "date of deposit", "date")
        c_ref = _find(paths, "reference", "ref no", "cpin", "cin")
        c_period = _find(paths, "tax period", "period", "return period")
        c_desc = _find(paths, "description", "particulars")
        c_type = _find(paths, "transaction type", "type of transaction", "type", "debit credit", "cr dr")
        header_row = t.rows[last][0]
        for n, vals in t.rows:
            if n <= header_row:
                continue

            def cell(c):
                return vals[c] if c is not None and c < len(vals) else None

            def sum_of(cols):
                total = ZERO
                for c in cols:
                    total += parse_amount(cell(c)) or ZERO
                return total

            where = f"{t.name}!{n}"
            d = _date(cell(c_date))
            desc = parse_text(cell(c_desc))
            if d is None and not re.search(r"opening|closing", desc, re.I):
                if any(v not in (None, "") for v in vals):
                    out.skipped.append(f"{where}: no date – not a ledger line ({desc or parse_text(vals[0])[:40]})")
                continue
            amounts = {h: sum_of(amt.get(h, [])) for h in HEADS}
            balance = {h: sum_of(bal[h]) for h in HEADS if h in bal} if bal else None
            if balance is not None:
                balance = {h: balance.get(h, ZERO) for h in HEADS}
            kind_text = parse_text(cell(c_type)).lower()
            if re.search(r"opening|closing", desc, re.I) and not kind_text:
                txn = "BAL"
            elif re.search(r"\bdr\b|debit", kind_text):
                txn = "DR"
            elif re.search(r"\bcr\b|credit", kind_text):
                txn = "CR"
            else:
                txn = "DR" if any(v < 0 for v in amounts.values()) else "CR"
            if txn == "DR":
                amounts = {h: -abs(v) for h, v in amounts.items()}
            elif txn == "CR":
                amounts = {h: abs(v) for h, v in amounts.items()}
            out.lines.append(LedgerLine(where, d, parse_text(cell(c_ref))[:80], parse_text(cell(c_period))[:40],
                                        desc[:300], txn, amounts, balance))
    if not found:
        raise UnsupportedFileError(f"{path.name}: no ledger table found – it needs a date, a description and the "
                                   "IGST / CGST / SGST / Cess columns")
    return out
