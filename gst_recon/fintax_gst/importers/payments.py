"""Payment register: payments made to suppliers (TallyPrime payment register, Excel/CSV, or Tally XML).

Each payment row gives the party, the date, the amount paid and – when the export has bill-wise details –
the bill it settles ("Agst Ref" / bill reference = the supplier's invoice number). The rows are used to
find purchase invoices not paid within 180 days (CGST Rule 37).

Rows that are no payment to a party (totals, opening balances, contra entries between cash and bank) are
listed as not imported with the reason.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.gstin import normalize_gstin, validate_gstin
from ..core.money import AmountParseError, parse_amount
from .parsing import DateParseError, is_blank, parse_date, parse_text
from .readers import UnsupportedFileError, read_csv, read_excel

HEADERS = {
    "pay_date": ("date", "payment date", "voucher date", "vch date", "paid on", "date of payment"),
    "party": ("particulars", "party", "party name", "party ledger", "ledger", "ledger name", "supplier",
              "supplier name", "vendor", "vendor name", "paid to", "payee", "account"),
    "amount": ("debit amount", "debit", "amount paid", "payment amount", "paid amount", "amount", "dr amount",
               "value"),
    "gstin": ("gstin/uin", "gstin", "supplier gstin", "party gstin", "gst no", "gstin of supplier"),
    "bill_ref": ("bill ref", "bill reference", "agst ref", "against ref", "agst ref no", "bill no",
                 "invoice no", "supplier invoice no", "reference no", "ref no", "bill wise details"),
    "voucher_type": ("voucher type", "vch type"),
    "voucher_no": ("voucher no", "vch no", "voucher number", "voucher no."),
}
_NOT_PARTY = re.compile(r"^(grand\s+)?total\b|^opening balance|^closing balance|^carried|^brought", re.I)
_CASHBANK = re.compile(r"\b(cash|bank|hdfc|icici|sbi|axis|kotak|petty)\b", re.I)


def party_key(name: str) -> str:
    """Name normalised for matching a payment's party with the supplier names of the purchase register."""
    t = re.sub(r"\bm/?s\.?\b", " ", (name or "").lower())
    t = re.sub(r"\b(private|pvt|limited|ltd|llp|co|company|and|the)\b", " ", t.replace("&", " and "))
    return re.sub(r"[^a-z0-9]+", "", t)


@dataclass
class PaymentRow:
    row: str
    party: str
    pay_date: date
    amount: Decimal
    gstin: str = ""
    bill_ref: str = ""
    voucher_no: str = ""


@dataclass
class PaymentFile:
    rows: list[PaymentRow] = field(default_factory=list)
    ignored: list[tuple[str, str]] = field(default_factory=list)  # (row, reason)

    @property
    def total(self) -> Decimal:
        return sum((r.amount for r in self.rows), Decimal(0))


def _norm(cell) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]", " ", str(cell or "").lower())).strip()


def _columns(cells: list) -> dict[str, int] | None:
    names = [_norm(c) for c in cells]
    found: dict[str, int] = {}
    for field_name, options in HEADERS.items():
        for opt in options:  # the first (most specific) heading wins
            if opt in names and names.index(opt) not in found.values():
                found[field_name] = names.index(opt)
                break
    return found if {"pay_date", "party", "amount"} <= set(found) else None


def _table_rows(tables) -> PaymentFile:
    out = PaymentFile()
    for t in tables:
        cols = None
        for n, cells in t.rows:
            if cols is None:
                cols = _columns(cells)
                continue
            get = {k: (cells[i] if i < len(cells) else None) for k, i in cols.items()}
            ref = f"{t.name}:{n}" if len(tables) > 1 else str(n)
            party = parse_text(get.get("party"))
            if not any(not is_blank(c) for c in cells):
                continue
            texts = [parse_text(c) for c in cells if isinstance(c, str)]
            if not party or _NOT_PARTY.search(party) or any(_NOT_PARTY.search(x) for x in texts):
                out.ignored.append((ref, "total / opening balance line" if party or texts else "no party"))
                continue
            vtype = parse_text(get.get("voucher_type")).lower()
            if vtype and "payment" not in vtype and "journal" not in vtype:
                out.ignored.append((ref, f"voucher type '{get.get('voucher_type')}' is not a payment"))
                continue
            if _CASHBANK.search(party) and not get.get("gstin"):
                out.ignored.append((ref, f"'{party}' is a cash / bank account (contra entry), not a supplier"))
                continue
            try:
                when = parse_date(get.get("pay_date"))
                amount = parse_amount(get.get("amount"))
            except (DateParseError, AmountParseError) as exc:
                out.ignored.append((ref, f"not read: {exc}"))
                continue
            if when is None or not amount or amount <= 0:
                out.ignored.append((ref, "no date or no amount paid"))
                continue
            g = normalize_gstin(parse_text(get.get("gstin")))
            out.rows.append(PaymentRow(ref, party, when, amount, g if g and validate_gstin(g)[0] else "",
                                       parse_text(get.get("bill_ref")), parse_text(get.get("voucher_no"))))
    return out


def _xml_rows(data: bytes) -> PaymentFile:
    from .tally_xml import _amount, _date, _ledger_entries, _t, parse_xml

    out = PaymentFile()
    for n, v in enumerate(parse_xml(data).iter("VOUCHER"), start=1):
        vtype = _t(v, "VOUCHERTYPENAME") or v.get("VCHTYPE", "")
        number = _t(v, "VOUCHERNUMBER")
        ref = f"{vtype} {number}".strip() or f"voucher {n}"
        if "payment" not in vtype.lower():
            continue  # other vouchers of a day book export are not payments
        if _t(v, "ISCANCELLED").lower() == "yes" or _t(v, "ISOPTIONAL").lower() == "yes":
            out.ignored.append((ref, "cancelled or optional voucher"))
            continue
        when = _date(_t(v, "DATE"))
        gstin = _t(v, "PARTYGSTIN")
        paid = False
        for e in _ledger_entries(v):
            name, amount = _t(e, "LEDGERNAME"), _amount(_t(e, "AMOUNT"))
            if amount >= 0 or _CASHBANK.search(name):
                continue  # in Tally XML a debit is negative; the party is debited, cash / bank credited
            bills = e.findall("BILLALLOCATIONS.LIST")
            if bills:
                for b in bills:
                    out.rows.append(PaymentRow(ref, name, when, abs(_amount(_t(b, "AMOUNT"))), gstin,
                                               _t(b, "NAME"), number))
            else:
                out.rows.append(PaymentRow(ref, name, when, abs(amount), gstin, "", number))
            paid = True
        if not paid:
            out.ignored.append((ref, "no party debited"))
    return out


def read_payments(path: str | Path) -> PaymentFile:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        result = _table_rows(read_excel(path))
    elif suffix == ".csv":
        result = _table_rows([read_csv(path, path.name)])
    elif suffix == ".xml":
        result = _xml_rows(path.read_bytes())
    else:
        raise UnsupportedFileError(f"{path.name}: use the payment register as Excel (.xlsx), CSV or Tally XML")
    if not result.rows:
        raise UnsupportedFileError(f"{path.name}: no payments found – the payment register needs columns for the "
                                   "date, the party (Particulars) and the amount paid (Debit Amount)")
    return result
