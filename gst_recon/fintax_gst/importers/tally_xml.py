"""TallyPrime / Tally.ERP 9 vouchers in Tally's XML format – from a file or straight from Tally.

**Two ways in:**

* **A file.** An XML export of the Day Book or a voucher register (*Export → XML*).
* **Live from Tally.** TallyPrime answers XML requests over HTTP when *Connectivity →
  TallyPrime acts as Server* (or *Both*) is enabled, by default on port 9000.
  :class:`TallyClient` asks it for the company list and for the vouchers of one company
  over a date range. Every response is saved as an ``.xml`` file and imported like any
  other file, so it stays traceable.

**Reading a voucher.** Each ``<VOUCHER>`` becomes one register row:

| Field | Source |
|---|---|
| Party | ``PARTYLEDGERNAME`` and ``PARTYGSTIN`` |
| Invoice number | for a purchase, the supplier's bill number (``REFERENCE``), else the voucher number with a warning; for a sale, the voucher number |
| Dates | voucher date ``DATE``; supplier invoice date ``REFERENCEDATE``, if present |
| Tax | ledger entries whose ledger is a GST duty ledger. They are recognised by the duty head in the ledger master when it was fetched, otherwise by the ledger name (CGST / SGST / UTGST / IGST / Cess) |
| Invoice value | the party ledger's amount |
| Taxable value | the other ledger entries and the inventory entries, except round-off |
| HSN | ``GSTHSNNAME`` / ``HSNCODE`` of inventory entries, where present |

Cancelled and optional vouchers, and voucher types other than purchase, sales, debit and
credit notes, are listed as *ignored*, never dropped silently. Amounts keep Tally's sign
convention: debits are negative, credits positive. Magnitudes are used, and notes keep
their document type.

The parser follows Tally's documented XML layout and is tested against a simulated Tally
server. Check one month against the register in Tally before relying on a new company.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib import request as urlrequest
from xml.etree import ElementTree as ET

from ..core.money import ZERO
from .readers import UnsupportedFileError

DEFAULT_URL = "http://localhost:9000"
_INVALID_REF = re.compile(rb"&#(?:[0-8]|1[1-2]|1[4-9]|2[0-9]|3[01]);")  # control characters Tally emits
_TAX = (("igst", re.compile(r"\bigst\b|integrated\s+tax", re.I)),
        ("cgst", re.compile(r"\bcgst\b|central\s+tax", re.I)),
        ("sgst", re.compile(r"\b(sgst|utgst)\b|state\s*(/\s*ut\s*)?tax|\but\s+tax", re.I)),
        ("cess", re.compile(r"\bcess\b", re.I)))
_DUTY_HEADS = {"integrated tax": "igst", "central tax": "cgst", "state tax": "sgst", "ut tax": "sgst",
               "cess": "cess"}
_ROUND = re.compile(r"round", re.I)


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
    return text


def parse_xml(data: bytes) -> ET.Element:
    """Parse Tally XML, refusing DTDs and entity declarations (no external or expanding entities)."""
    data = _INVALID_REF.sub(b"", data)
    text = _decode(data)
    if re.search(r"<!(DOCTYPE|ENTITY)", text[:5000], re.I):
        raise UnsupportedFileError("XML with a DOCTYPE or entity declarations is not accepted")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise UnsupportedFileError(f"Not readable as Tally XML: {exc}") from None


def is_tally_xml(data: bytes) -> bool:
    head = _decode(data[:4000]).upper()
    return "<ENVELOPE" in head and ("TALLY" in head or "<VOUCHER" in head or "<BODY" in head)


def _t(el: ET.Element, tag: str) -> str:
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def _date(text: str) -> date | None:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text.strip())
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _amount(text: str) -> Decimal:
    text = (text or "").replace(",", "").strip()
    m = re.match(r"^-?\d+(\.\d+)?", text)  # "-1180.00" or "1180.00/Nos" style suffixes
    return Decimal(m.group(0)) if m else ZERO


def voucher_kind(vtype: str) -> str | None:
    """Which register a voucher type belongs to: 'purchase', 'sales', 'journal' or None (not imported)."""
    t = vtype.lower()
    if "journal" in t:
        return "journal"  # read with the purchase register when it is a supplier's bill (see _journal_row)
    if "purchase" in t or "debit" in t:
        return "purchase"  # a debit note is a purchase return in the buyer's books
    if "sale" in t or "credit" in t:
        return "sales"
    return None


@dataclass
class TallyVoucherRows:
    rows: list[dict]
    ignored: list[tuple[str, str]]  # (reference, reason)
    company: str


def _ledger_entries(v: ET.Element) -> list[ET.Element]:
    return [e for tag in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST") for e in v.findall(tag)]


def duty_heads_from(root: ET.Element) -> dict[str, str]:
    """GST duty ledgers from ledger masters in the document (live fetches and exports with masters)."""
    out = {}
    for led in root.iter("LEDGER"):
        name = (led.get("NAME") or _t(led, "NAME")).strip()
        head = _DUTY_HEADS.get(_t(led, "GSTDUTYHEAD").lower())
        if name and head and _t(led, "TAXTYPE").upper() in ("GST", ""):
            out[name] = head
    return out


def flatten_vouchers(root: ET.Element, register: str, duty_heads: dict[str, str] | None = None) -> TallyVoucherRows:
    """Rows for the purchase ('purchase') or sales ('sales') register from all ``VOUCHER`` elements."""
    duty_heads = {k.lower(): v for k, v in (duty_heads if duty_heads is not None else duty_heads_from(root)).items()}
    company = next((x.text.strip() for x in root.iter("SVCURRENTCOMPANY") if x.text), "")
    rows, ignored = [], []
    for n, v in enumerate(root.iter("VOUCHER"), start=1):
        vtype = _t(v, "VOUCHERTYPENAME") or v.get("VCHTYPE", "")
        number = _t(v, "VOUCHERNUMBER")
        ref = f"{vtype} {number}".strip() or f"voucher {n}"
        kind = voucher_kind(vtype)
        if kind == "journal" and register == "purchase":
            if _t(v, "ISCANCELLED").lower() == "yes" or _t(v, "ISOPTIONAL").lower() == "yes":
                ignored.append((ref, "cancelled or optional voucher"))
                continue
            row, reason = _journal_row(v, vtype, number, ref, duty_heads)
            if row is None:
                ignored.append((ref, reason))
            else:
                rows.append(row)
            continue
        if kind != register:
            if kind is None or kind == "journal":
                ignored.append((ref, f"voucher type '{vtype}' is not a purchase / sales / note voucher"))
            continue
        if _t(v, "ISCANCELLED").lower() == "yes":
            ignored.append((ref, "cancelled voucher"))
            continue
        if _t(v, "ISOPTIONAL").lower() == "yes":
            ignored.append((ref, "optional (memorandum) voucher"))
            continue
        party = _t(v, "PARTYLEDGERNAME")
        taxes = {"igst": ZERO, "cgst": ZERO, "sgst": ZERO, "cess": ZERO}
        taxable, invoice_value = ZERO, None
        for e in _ledger_entries(v):
            name = _t(e, "LEDGERNAME")
            amount = abs(_amount(_t(e, "AMOUNT")))
            if _t(e, "ISPARTYLEDGER").lower() == "yes" or (party and name == party and invoice_value is None):
                invoice_value = amount
                continue
            head = duty_heads.get(name.lower()) or next((h for h, rx in _TAX if rx.search(name)), None)
            if head:
                taxes[head] += amount
            elif not _ROUND.search(name):
                taxable += amount
        # Invoice-mode vouchers carry the purchase / sales ledger in the inventory entries' accounting
        # allocations (not in the ledger list); an entry without allocations counts at its own amount.
        hsn_lines = []
        for inv in v.findall("ALLINVENTORYENTRIES.LIST") + v.findall("INVENTORYENTRIES.LIST"):
            allocations = inv.findall("ACCOUNTINGALLOCATIONS.LIST")
            if allocations:
                taxable += sum((abs(_amount(_t(a, "AMOUNT"))) for a in allocations
                                if not _ROUND.search(_t(a, "LEDGERNAME"))), ZERO)
            else:
                taxable += abs(_amount(_t(inv, "AMOUNT")))
            hsn = _t(inv, "GSTHSNNAME") or _t(inv, "HSNCODE")
            if hsn:
                hsn_lines.append({"hsn": hsn, "qty": _t(inv, "ACTUALQTY") or _t(inv, "BILLEDQTY")})
        vdate = _date(_t(v, "DATE"))
        supplier_no = _t(v, "REFERENCE") if register == "purchase" else ""
        row = {
            "supplier_gstin": _t(v, "PARTYGSTIN") or _t(v, "GSTIN") or None,
            "supplier_name": party,
            "invoice_no": supplier_no or number,
            "invoice_date": (_date(_t(v, "REFERENCEDATE")) if supplier_no else None) or vdate,
            "voucher_date": vdate,
            "voucher_type": vtype,
            "taxable_value": str(taxable),
            "invoice_value": str(invoice_value) if invoice_value is not None else None,
            "place_of_supply": _t(v, "PLACEOFSUPPLY") or None,
            "description": _t(v, "NARRATION") or None,
            "_row": ref,
            **{k: str(val) for k, val in taxes.items()},
        }
        if len(hsn_lines) == 1:
            row["hsn"], row["quantity"] = hsn_lines[0]["hsn"], hsn_lines[0]["qty"] or None
        if register == "purchase" and not supplier_no:
            row["_warning"] = "No supplier invoice number (Reference) – the voucher number is used"
        rows.append(row)
    return TallyVoucherRows(rows, ignored, company)


def _journal_row(v: ET.Element, vtype: str, number: str, ref: str, duty_heads: dict[str, str]):
    """A journal voucher booking a supplier's bill (expense and input tax debited, party credited) as a
    purchase-register row – or None and the reason when it is no bill (no GST, ITC reversal, no GSTIN).
    In Tally XML a negative amount is a debit."""
    taxes = {"igst": ZERO, "cgst": ZERO, "sgst": ZERO, "cess": ZERO}
    taxable, credits, reversal = ZERO, [], False
    party_name = _t(v, "PARTYLEDGERNAME")
    party_amount = None
    for e in _ledger_entries(v):
        name = _t(e, "LEDGERNAME")
        amount = _amount(_t(e, "AMOUNT"))
        head = duty_heads.get(name.lower()) or next((h for h, rx in _TAX if rx.search(name)), None)
        if head:
            if amount > 0:
                reversal = True  # a GST ledger credited
            taxes[head] += abs(amount)
        elif _t(e, "ISPARTYLEDGER").lower() == "yes" or (party_name and name == party_name):
            party_name, party_amount = name, abs(amount)
        elif _ROUND.search(name):
            continue
        elif amount < 0:
            taxable += -amount
        else:
            credits.append((amount, name))
    if not any(taxes.values()):
        return None, "journal without GST – not a supplier's bill (e.g. depreciation, provision, TDS)"
    if reversal:
        return None, "journal credits a GST ledger (ITC reversal or adjustment) – not a supplier's bill"
    if party_amount is None and credits:
        party_amount, party_name = max(credits)
    gstin = _t(v, "PARTYGSTIN") or _t(v, "GSTIN")
    if not gstin:
        return None, ("journal without supplier GSTIN (e.g. reverse charge from an unregistered supplier) – not "
                      "compared with GSTR-2B")
    vdate = _date(_t(v, "DATE"))
    supplier_no = _t(v, "REFERENCE")
    row = {"supplier_gstin": gstin, "supplier_name": party_name, "invoice_no": supplier_no or number,
           "invoice_date": (_date(_t(v, "REFERENCEDATE")) if supplier_no else None) or vdate, "voucher_date": vdate,
           "voucher_type": vtype, "taxable_value": str(taxable),
           "invoice_value": str(party_amount) if party_amount is not None else None,
           "place_of_supply": _t(v, "PLACEOFSUPPLY") or None, "description": _t(v, "NARRATION") or None,
           "_row": ref, **{k: str(val) for k, val in taxes.items()}}
    if not supplier_no:
        row["_warning"] = "No supplier invoice number (Reference) – the voucher number is used"
    return row, ""


# --------------------------------------------------------------------------- live
def _envelope(request_id: str, tdl: str, statics: str = "") -> bytes:
    return (f"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>"
            f"<ID>{request_id}</ID></HEADER><BODY><DESC><STATICVARIABLES>"
            f"<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{statics}</STATICVARIABLES>"
            f"<TDL><TDLMESSAGE>{tdl}</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>").encode("utf-8")


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TallyClient:
    """Minimal client for TallyPrime's XML-over-HTTP interface (local network only)."""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 60):
        if not re.match(r"^https?://", url):
            url = f"http://{url}"
        self.url, self.timeout = url.rstrip("/"), timeout

    def _post(self, body: bytes) -> bytes:
        req = urlrequest.Request(self.url, data=body, headers={"Content-Type": "text/xml; charset=utf-8"})
        try:
            # Tally is on this PC or the office network: never through a proxy
            opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
            with opener.open(req, timeout=self.timeout) as resp:
                data = resp.read()
        except OSError as exc:
            raise ConnectionError(f"Tally did not answer at {self.url} ({exc}). In TallyPrime enable "
                                  "F1 Help → Settings → Connectivity → 'TallyPrime acts as: Server' (port 9000) and "
                                  "keep the company open.") from None
        errors = [e.text.strip() for e in parse_xml(data).iter("LINEERROR") if e.text and e.text.strip()]
        if errors:
            raise ValueError("Tally: " + "; ".join(errors) + " – check that the company is open in Tally and named "
                             "exactly as there")
        return data

    def companies(self) -> list[str]:
        tdl = ('<COLLECTION NAME="FinTaxCompanies" ISMODIFY="No"><TYPE>Company</TYPE>'
               "<FETCH>NAME</FETCH></COLLECTION>")
        root = parse_xml(self._post(_envelope("FinTaxCompanies", tdl)))
        names = [(c.get("NAME") or _t(c, "NAME")).strip() for c in root.iter("COMPANY")]
        return [n for n in dict.fromkeys(names) if n]

    def duty_heads(self, company: str) -> dict[str, str]:
        """GST duty ledgers of the company: ledger name -> igst/cgst/sgst/cess."""
        return duty_heads_from(parse_xml(self._ledger_xml(company)))

    def _ledger_xml(self, company: str) -> bytes:
        tdl = ('<COLLECTION NAME="FinTaxLedgers" ISMODIFY="No"><TYPE>Ledger</TYPE>'
               "<FETCH>NAME, TAXTYPE, GSTDUTYHEAD</FETCH></COLLECTION>")
        return self._post(_envelope("FinTaxLedgers", tdl,
                                    f"<SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>"))

    def fetch(self, company: str, start: date, end: date) -> bytes:
        """One XML document with the company's GST duty ledgers and its vouchers for the range – saved and
        imported as a file."""
        ledgers = _decode(_INVALID_REF.sub(b"", self._ledger_xml(company)))
        vouchers = _decode(_INVALID_REF.sub(b"", self.vouchers(company, start, end)))
        strip = lambda t: re.sub(r"^\s*<\?xml[^>]*\?>", "", t)  # noqa: E731
        return (f'<?xml version="1.0" encoding="utf-8"?>\n<ENVELOPE><HEADER><TALLYREQUEST>FinTaxFetch</TALLYREQUEST>'
                f"</HEADER><BODY><DESC><STATICVARIABLES><SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>"
                f"<SVFROMDATE>{start:%Y%m%d}</SVFROMDATE><SVTODATE>{end:%Y%m%d}</SVTODATE></STATICVARIABLES></DESC>"
                f"<DATA>{strip(ledgers)}{strip(vouchers)}</DATA></BODY></ENVELOPE>").encode("utf-8")

    def vouchers(self, company: str, start: date, end: date) -> bytes:
        tdl = ('<COLLECTION NAME="FinTaxVouchers" ISMODIFY="No"><TYPE>Voucher</TYPE>'
               "<FETCH>DATE, VOUCHERTYPENAME, VOUCHERNUMBER, REFERENCE, REFERENCEDATE, PARTYLEDGERNAME, PARTYGSTIN, "
               "PLACEOFSUPPLY, NARRATION, ISCANCELLED, ISOPTIONAL, ALLLEDGERENTRIES.LIST, LEDGERENTRIES.LIST, "
               "ALLINVENTORYENTRIES.LIST, INVENTORYENTRIES.LIST</FETCH></COLLECTION>")
        statics = (f"<SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>"
                   f"<SVFROMDATE TYPE=\"Date\">{start:%d-%b-%Y}</SVFROMDATE>"
                   f"<SVTODATE TYPE=\"Date\">{end:%d-%b-%Y}</SVTODATE>")
        return self._post(_envelope("FinTaxVouchers", tdl, statics))
