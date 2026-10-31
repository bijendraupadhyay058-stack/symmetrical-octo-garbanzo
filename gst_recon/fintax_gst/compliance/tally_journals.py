"""Journal vouchers for ITC reversals and re-claims, as a TallyPrime XML import file.

A reversal debits the 'ITC reversed' ledger (an expense, or the supplier when the credit is to be recovered)
and credits the input tax ledgers; a re-claim is the opposite entry. The file is imported in TallyPrime with
*Import → Vouchers*; the ledgers must exist there with exactly the names used.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

ZERO = Decimal(0)
HEADS = ("igst", "cgst", "sgst", "cess")
DEFAULT_LEDGERS = {"igst": "Input IGST", "cgst": "Input CGST", "sgst": "Input SGST", "cess": "Input Cess",
                   "reversed": "ITC Reversed"}
LEDGER_LABELS = {"igst": "IGST input ledger", "cgst": "CGST input ledger", "sgst": "SGST input ledger",
                 "cess": "Cess input ledger", "reversed": "Ledger debited on reversal (expense)"}


def month_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:])
    return date(y, m, calendar.monthrange(y, m)[1])


@dataclass
class JournalEntry:
    on: date
    narration: str
    lines: list[tuple[str, Decimal]] = field(default_factory=list)  # (ledger, amount): debit > 0, credit < 0
    reference: str = ""

    @property
    def total(self) -> Decimal:
        return sum((a for _l, a in self.lines if a > 0), ZERO)

    def balanced(self) -> bool:
        return sum((a for _l, a in self.lines), ZERO) == 0


def entry(action: str, on: date, amounts: dict[str, Decimal], ledgers: dict[str, str], narration: str,
          reference: str = "") -> JournalEntry | None:
    """A reversal ('REVERSE') or re-claim ('RECLAIM') journal for the given tax amounts (None when all zero)."""
    taxes = [(ledgers[h], amounts.get(h, ZERO)) for h in HEADS if amounts.get(h, ZERO) > 0]
    if not taxes:
        return None
    total = sum((a for _l, a in taxes), ZERO)
    if action == "REVERSE":
        lines = [(ledgers["reversed"], total)] + [(name, -a) for name, a in taxes]
    else:
        lines = [(name, a) for name, a in taxes] + [(ledgers["reversed"], -total)]
    return JournalEntry(on, narration, lines, reference)


def to_tally_xml(entries: list[JournalEntry], company: str = "", voucher_type: str = "Journal") -> bytes:
    """TallyPrime 'Import Data – Vouchers' envelope. In Tally XML a debit is negative with ISDEEMEDPOSITIVE Yes."""
    out = ["<ENVELOPE>", "<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>", "<BODY><IMPORTDATA>",
           "<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>"]
    if company:
        out.append(f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES>")
    out += ["</REQUESTDESC>", "<REQUESTDATA>"]
    for e in entries:
        if not e.balanced():
            raise ValueError(f"Journal '{e.narration}' does not balance")
        out += ['<TALLYMESSAGE xmlns:UDF="TallyUDF">',
                f'<VOUCHER VCHTYPE="{escape(voucher_type)}" ACTION="Create" OBJVIEW="Accounting Voucher View">',
                f"<DATE>{e.on:%Y%m%d}</DATE>", f"<EFFECTIVEDATE>{e.on:%Y%m%d}</EFFECTIVEDATE>",
                f"<VOUCHERTYPENAME>{escape(voucher_type)}</VOUCHERTYPENAME>",
                f"<NARRATION>{escape(e.narration)}</NARRATION>"]
        if e.reference:
            out.append(f"<REFERENCE>{escape(e.reference)}</REFERENCE>")
        for ledger, amount in e.lines:
            debit = amount > 0
            out += ["<ALLLEDGERENTRIES.LIST>", f"<LEDGERNAME>{escape(ledger)}</LEDGERNAME>",
                    f"<ISDEEMEDPOSITIVE>{'Yes' if debit else 'No'}</ISDEEMEDPOSITIVE>",
                    f"<AMOUNT>{-amount if debit else abs(amount)}</AMOUNT>", "</ALLLEDGERENTRIES.LIST>"]
        out += ["</VOUCHER>", "</TALLYMESSAGE>"]
    out += ["</REQUESTDATA>", "</IMPORTDATA></BODY>", "</ENVELOPE>"]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(out) + "\n").encode("utf-8")
