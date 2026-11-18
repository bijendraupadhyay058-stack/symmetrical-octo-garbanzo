"""Input tax ledgers exported from TallyPrime (Display → Account Books → Ledger → Input CGST … → Alt+E Excel), one
file per ledger or one workbook with a sheet per ledger, or any sheet with a *Ledger* column.

Columns read: Date, Particulars, Vch Type, Vch No, Debit, Credit (a single signed *Amount* column also works). The
tax head (IGST / CGST / SGST-UTGST / cess) comes from the ledger name – in a *Ledger* column, the title rows of the
export, the sheet name or the file name. Opening balance, totals and closing balance rows are kept apart from the
transactions (they are not vouchers). Amounts are kept exactly as exported: debit positive, credit negative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, AmountParseError, parse_amount
from .column_mapping import normalize_header
from .parsing import parse_date
from .readers import UnsupportedFileError, read_csv, read_excel

_HEADS = [("cess", re.compile(r"\bcess\b", re.I)), ("igst", re.compile(r"\bigst\b|integrated", re.I)),
          ("cgst", re.compile(r"\bcgst\b|central", re.I)), ("sgst", re.compile(r"\bsgst\b|\butgst\b|state", re.I))]
_COLS = {"date": ["date", "voucher date", "vch date"], "particulars": ["particulars", "party", "account", "narration"],
         "vtype": ["vch type", "voucher type", "type"], "vno": ["vch no", "voucher no", "voucher number", "vch no."],
         "debit": ["debit", "dr", "debit amount"], "credit": ["credit", "cr", "credit amount"],
         "amount": ["amount", "value"], "ledger": ["ledger", "ledger name", "tax ledger"]}
_OPENING = re.compile(r"^opening balance", re.I)
_CLOSING = re.compile(r"^(closing balance|current total|grand total|total)\b", re.I)


def head_of(text: str) -> str | None:
    for head, rx in _HEADS:
        if rx.search(text or ""):
            return head
    return None


@dataclass
class Posting:
    ledger: str
    head: str
    kind: str  # txn / opening / closing
    entry_date: date | None
    voucher_type: str
    voucher_no: str
    particulars: str
    amount: Decimal  # debit positive
    row: str


@dataclass
class TaxLedgerFile:
    postings: list[Posting] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ledgers(self) -> dict[str, str]:
        return {p.ledger: p.head for p in self.postings}

    def total(self, head: str | None = None, kind: str = "txn") -> Decimal:
        return sum((p.amount for p in self.postings if p.kind == kind and (head is None or p.head == head)), ZERO)


def _amt(v, where) -> Decimal:
    if v in (None, ""):
        return ZERO
    text = str(v).strip()
    sign = 1
    m = re.search(r"\b(dr|cr)\.?\s*$", text, re.I)
    if m:
        sign = -1 if m.group(1).lower() == "cr" else 1
        text = text[:m.start()]
    try:
        return (parse_amount(text) or ZERO) * sign
    except AmountParseError as exc:
        raise ValueError(f"{where}: {exc}") from exc


def _table(rows, sheet: str, fallback: str, out: TaxLedgerFile) -> bool:
    header_at, cols = None, {}
    title = ""
    for i, (_n, values) in enumerate(rows[:40]):
        names = [normalize_header(v) for v in values]
        found = {}
        for key, options in _COLS.items():
            for o in options:
                if o in names and names.index(o) not in found.values():
                    found[key] = names.index(o)
                    break
        if "particulars" in found and ("debit" in found or "amount" in found):
            header_at, cols = i, found
            break
        title += " " + " ".join(str(v) for v in values if v not in (None, ""))
    if header_at is None:
        return False
    default_ledger = next((t for t in (title, sheet, fallback) if head_of(t)), "")
    default_ledger = (re.search(r"(input\s*)?(cgst|sgst|utgst|igst|cess)[^,;\n]*", default_ledger, re.I).group(0).strip()
                      if default_ledger else "")
    last_date = None
    for n, values in rows[header_at + 1:]:
        def cell(k, values=values):
            i = cols.get(k)
            return values[i] if i is not None and i < len(values) else None

        part = str(cell("particulars") or "").strip()
        where = f"{sheet} row {n}"
        if "debit" in cols:
            amount = _amt(cell("debit"), where) - abs(_amt(cell("credit"), where))
        else:
            amount = _amt(cell("amount"), where)
        if not part and not amount:
            continue
        ledger = str(cell("ledger") or "").strip() or default_ledger
        head = head_of(ledger)
        if head is None:
            out.warnings.append(f"{where}: tax head not known (ledger '{ledger or sheet}') – skipped")
            continue
        raw_date = cell("date")
        d = None
        if raw_date not in (None, ""):
            try:
                d = raw_date if isinstance(raw_date, date) else parse_date(raw_date)
            except (ValueError, TypeError):
                d = None
        kind = "opening" if _OPENING.search(part) else "closing" if _CLOSING.search(part) else "txn"
        if kind == "txn" and d is None:
            d = last_date  # continuation line of the same voucher
        if kind == "txn":
            last_date = d
        if kind == "closing" and re.match(r"^current total", part, re.I):
            continue  # a total of the period, not a balance
        out.postings.append(Posting(ledger, head, kind, d, str(cell("vtype") or "").strip(),
                                    str(cell("vno") or "").strip(), part, amount, where))
    return True


def read_tax_ledgers(path: str | Path) -> TaxLedgerFile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".xls", ".csv"):
        raise UnsupportedFileError("Use the input tax ledger exported from TallyPrime as Excel or CSV")
    tables = [read_csv(path, path.name)] if suffix == ".csv" else read_excel(path)
    out = TaxLedgerFile()
    read_any = False
    for t in tables:
        read_any |= _table(t.rows, t.name, path.stem, out)
    if not read_any:
        raise UnsupportedFileError("No ledger voucher heading row (Date, Particulars, Vch Type, Vch No, Debit, Credit) "
                                   "found")
    if not any(p.kind == "txn" for p in out.postings):
        raise ValueError("No voucher lines found in the tax ledger")
    return out
