"""Vouchers of ledgers, for splitting a trial-balance ledger voucher by voucher.

Accepted:

* **Tally XML** – the Day Book (or any voucher export) as XML, or the file saved by *From TallyPrime*: every
  voucher's ledger entries. Each entry of a ledger that is not the party, a GST duty ledger or round-off becomes a
  line of that ledger. When the voucher has exactly one such ledger, the voucher's GST belongs to it and is kept
  with the line; with several ledgers in one voucher the GST cannot be told per ledger and is left blank (noted).
* **Excel / CSV** – Tally's *Ledger Vouchers* export of a ledger (Date, Particulars, Vch Type, Vch No, Debit,
  Credit), one sheet per ledger; the ledger name is taken from a *Ledger* column, the title rows, or the sheet name.
  These carry no GST.

Amounts are kept as in the books: debit positive, credit negative. Cancelled and optional vouchers are skipped
(and counted).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, AmountParseError, parse_amount
from .column_mapping import normalize_header
from .parsing import parse_date
from .readers import UnsupportedFileError, read_csv, read_excel

_COLS = {"date": ["date", "voucher date", "vch date"], "particulars": ["particulars", "party", "account"],
         "vtype": ["vch type", "voucher type", "type"], "vno": ["vch no", "voucher no", "voucher number", "vch no."],
         "debit": ["debit", "dr", "debit amount"], "credit": ["credit", "cr", "credit amount"],
         "amount": ["amount", "value"], "ledger": ["ledger", "ledger name"], "narration": ["narration"]}
_SKIP = re.compile(r"^(opening balance|closing balance|current total|grand total|total)\b", re.I)


@dataclass
class VLine:
    ledger: str
    entry_date: date | None
    voucher_type: str
    voucher_no: str
    party: str
    amount: Decimal  # debit positive
    gstin: str = ""
    reference: str = ""
    narration: str = ""
    tax: dict[str, Decimal] | None = None
    tax_note: str = ""
    row: str = ""


@dataclass
class VoucherFile:
    lines: list[VLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    layout: str = ""

    @property
    def ledgers(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ln in self.lines:
            out[ln.ledger] = out.get(ln.ledger, 0) + 1
        return out


def _from_xml(data: bytes, out: VoucherFile) -> None:
    from .tally_xml import _DUTY_HEADS, _ROUND, _TAX, _amount, _date, _ledger_entries, _t, duty_heads_from, \
        parse_xml, party_gstins_from

    root = parse_xml(data)
    duty = {k.lower(): v for k, v in duty_heads_from(root).items()}
    gstins = party_gstins_from(root)
    _ = _DUTY_HEADS
    vouchers = list(root.iter("VOUCHER"))
    if not vouchers:
        raise UnsupportedFileError("No vouchers in this XML – export the Day Book (or vouchers) from TallyPrime as XML")
    for n, v in enumerate(vouchers, start=1):
        vtype = _t(v, "VOUCHERTYPENAME") or v.get("VCHTYPE", "")
        vno = _t(v, "VOUCHERNUMBER")
        ref = f"{vtype} {vno}".strip() or f"voucher {n}"
        if _t(v, "ISCANCELLED").lower() == "yes" or _t(v, "ISOPTIONAL").lower() == "yes":
            out.skipped.append(f"{ref}: cancelled / optional")
            continue
        party = _t(v, "PARTYLEDGERNAME")
        vdate = _date(_t(v, "DATE"))
        tax = {h: ZERO for h in ("igst", "cgst", "sgst", "cess")}
        books: dict[str, Decimal] = {}
        entries = list(_ledger_entries(v))
        for inv in v.findall("ALLINVENTORYENTRIES.LIST") + v.findall("INVENTORYENTRIES.LIST"):
            entries += inv.findall("ACCOUNTINGALLOCATIONS.LIST")
        for e in entries:
            name = _t(e, "LEDGERNAME")
            if not name:
                continue
            amount = -_amount(_t(e, "AMOUNT"))  # Tally: debit negative → debit positive here
            if _t(e, "ISPARTYLEDGER").lower() == "yes" or (party and name == party):
                continue
            head = duty.get(name.lower()) or next((h for h, rx in _TAX if rx.search(name)), None)
            if head:
                tax[head] += amount
                continue
            if _ROUND.search(name):
                continue
            books[name] = books.get(name, ZERO) + amount
        if not books:
            continue
        single = len(books) == 1
        for name, amount in books.items():
            out.lines.append(VLine(name, vdate, vtype, vno, party, amount,
                                   _t(v, "PARTYGSTIN") or gstins.get(party.lower(), ""), _t(v, "REFERENCE"),
                                   _t(v, "NARRATION"), dict(tax) if single and any(tax.values()) else
                                   ({h: ZERO for h in tax} if single else None),
                                   "" if single else f"voucher has {len(books)} ledgers – GST not split per ledger",
                                   f"XML {ref}"))
    out.layout = "Tally XML vouchers"


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


def _from_table(rows, sheet: str, fallback: str, out: VoucherFile) -> bool:
    header_at, cols, title = None, {}, []
    for i, (_n, values) in enumerate(rows[:40]):
        names = [normalize_header(v) for v in values]
        found = {}
        for key, options in _COLS.items():
            for o in options:
                if o in names and names.index(o) not in found.values():
                    found[key] = names.index(o)
                    break
        if "particulars" in found and ("debit" in found or "amount" in found) and ("vno" in found or "date" in found):
            header_at, cols = i, found
            break
        title += [str(x) for x in values if x not in (None, "")]
    if header_at is None:
        return False
    default = next((re.sub(r"\s*[-–]?\s*ledger account.*$", "", t, flags=re.I).strip() for t in title
                    if re.search(r"ledger account|ledger:", t, re.I)), "") or \
        re.sub(r"\.(csv|xlsx|xlsm|xls)$", "", sheet or "", flags=re.I) or fallback
    default = re.sub(r"^ledger:\s*", "", default, flags=re.I)
    last = None
    for n, values in rows[header_at + 1:]:
        def cell(k, values=values):
            i = cols.get(k)
            return values[i] if i is not None and i < len(values) else None

        part = str(cell("particulars") or "").strip()
        where = f"{sheet} row {n}"
        amount = (_amt(cell("debit"), where) - abs(_amt(cell("credit"), where))) if "debit" in cols else \
            _amt(cell("amount"), where)
        if (not part and not amount) or _SKIP.search(part):
            continue
        d = cell("date")
        try:
            d = d if isinstance(d, date) else (parse_date(d) if d not in (None, "") else None)
        except (ValueError, TypeError):
            d = None
        if isinstance(d, datetime):
            d = d.date()
        d = d or last
        last = d
        out.lines.append(VLine(str(cell("ledger") or "").strip() or default, d, str(cell("vtype") or "").strip(),
                               str(cell("vno") or "").strip(), part, amount, narration=str(cell("narration") or ""),
                               tax=None, tax_note="ledger voucher list – no GST in the export", row=where))
    return True


def read_vouchers(path: str | Path) -> VoucherFile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    out = VoucherFile()
    suffix = path.suffix.lower()
    if suffix == ".xml":
        _from_xml(path.read_bytes(), out)
    elif suffix in (".xlsx", ".xlsm", ".xls", ".csv"):
        tables = [read_csv(path, path.name)] if suffix == ".csv" else read_excel(path)
        if not any(_from_table(t.rows, t.name, path.stem, out) for t in tables):
            raise UnsupportedFileError("No ledger voucher heading row (Date, Particulars, Vch Type, Vch No, Debit, "
                                       "Credit) found")
        out.layout = "Ledger vouchers (Excel)" if suffix != ".csv" else "Ledger vouchers (CSV)"
    else:
        raise UnsupportedFileError("Use the Day Book / vouchers as Tally XML, or a ledger's vouchers as Excel / CSV")
    if not out.lines:
        raise ValueError("No voucher lines of purchase / expense / asset ledgers found")
    return out
