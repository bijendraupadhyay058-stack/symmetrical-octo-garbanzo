"""Tax type and rate checks on the client's own purchase and sales documents.

* **Tax type** – IGST is due on inter-state supplies, CGST + SGST on intra-state supplies (IGST Act ss. 7–8).
  Purchases: supplier's state (GSTIN) against the place of supply (the document's, else the client's state).
  Sales: the client's state against the place of supply (the document's, else the customer's GSTIN state).
  Exports and SEZ supplies are inter-state (IGST or zero-rated under LUT).
* **Other state's tax** – a purchase taxed as intra-state in a state other than the client's (typically a
  hotel or event elsewhere): that CGST/SGST is not ITC of this registration.
* **Rate** – the tax should be the taxable value × a GST rate (0.1 % … 40 %), within rounding. A document
  that fits no rate has a calculation error – or combines items at different rates, which is said too.

Every finding is advice for review; nothing is changed in the data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..core.gstin import STATE_CODES

RATES = (Decimal("0.1"), Decimal("0.25"), Decimal("1"), Decimal("1.5"), Decimal("3"), Decimal("5"), Decimal("6"),
         Decimal("7.5"), Decimal("12"), Decimal("18"), Decimal("28"), Decimal("40"))
EXPORT = re.compile(r"exp|sez|lut|wpay|wopay|zero", re.IGNORECASE)
_NAMES = sorted(((name.lower(), code) for code, name in STATE_CODES.items()), key=lambda x: -len(x[0]))
_ALIASES = {"orissa": "21", "pondicherry": "34", "tamilnadu": "33", "j&k": "01", "new delhi": "07",
            "andhra pradesh": "37", "dadra and nagar haveli": "26", "daman": "26", "uttaranchal": "05"}
ZERO = Decimal(0)

KINDS = {"tax_type": "Wrong tax type", "other_state": "Tax of another state", "rate": "Tax ≠ taxable × GST rate"}


def pos_code(text: str | None) -> str | None:
    """State code of a place of supply written as '27', '27-Maharashtra', 'Maharashtra' or 'Karnataka (29)'."""
    t = (text or "").strip().lower()
    if not t:
        return None
    m = re.search(r"(?<!\d)(\d{2})(?!\d)", t)
    if m and m.group(1) in STATE_CODES:
        return m.group(1)
    for alias, code in _ALIASES.items():
        if alias in t:
            return code
    return next((code for name, code in _NAMES if name in t), None)


@dataclass
class Doc:
    """The fields a check needs (an imported purchase or sales document)."""

    id: int
    source: str  # BOOKS or SALES
    gstin: str  # supplier (purchases) / customer (sales)
    party: str
    invoice_no: str
    invoice_date: date
    taxable: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    place_of_supply: str = ""
    supply_type: str = ""
    reverse_charge: bool = False
    lines: tuple = ()  # (taxable, igst, cgst, sgst) per HSN line, when the register gave them


@dataclass
class TaxIssue:
    doc: Doc
    kind: str
    message: str


def _charged(d) -> str | None:
    if d.igst > 0 and (d.cgst > 0 or d.sgst > 0):
        return "both"
    if d.igst > 0:
        return "inter"
    if d.cgst > 0 or d.sgst > 0:
        return "intra"
    return None


def _state(code: str | None) -> str:
    return f"{STATE_CODES.get(code, code)} ({code})" if code else "?"


def fits_rate(taxable: Decimal, igst: Decimal, cgst: Decimal, sgst: Decimal) -> Decimal | None:
    """The GST rate the tax corresponds to (within rounding), or None."""
    tax = igst + cgst + sgst
    if taxable <= 0 or tax <= 0:
        return RATES[0] if tax == 0 else None
    heads = 1 if igst > 0 else 2
    tolerance = max(Decimal("1.00") * heads, taxable * Decimal("0.001"))
    best = min(RATES, key=lambda r: abs(tax - taxable * r / 100))
    return best if abs(tax - taxable * best / 100) <= tolerance else None


def check(doc: Doc, client_state: str) -> list[TaxIssue]:
    out: list[TaxIssue] = []
    charged = _charged(doc)
    if doc.source == "BOOKS":
        supplier = doc.gstin[:2] if len(doc.gstin) == 15 else None
        given = pos_code(doc.place_of_supply)
        pos = given or client_state
        if not given and charged == "intra" and supplier not in (None, client_state) and not doc.reverse_charge:
            # no place of supply in the books: a hotel / event in the supplier's state, or a wrong tax head
            out.append(TaxIssue(doc, "other_state", (
                f"CGST + SGST charged by a supplier in {_state(supplier)}: either the place of supply is there "
                f"(e.g. hotel or event – then not ITC of your registration in {_state(client_state)}), or IGST "
                "was due.")))
        elif supplier in STATE_CODES and supplier not in ("96", "97", "99") and charged in ("inter", "intra") \
                and not doc.reverse_charge:
            expected = "intra" if supplier == pos else "inter"
            if charged != expected:
                out.append(TaxIssue(doc, "tax_type", (
                    f"IGST charged, but supplier and place of supply are both in {_state(pos)} – CGST + SGST "
                    "was due. Ask the supplier for a corrected invoice (tax paid under the wrong head is not "
                    "ITC as charged)." if expected == "intra" else
                    f"CGST + SGST charged, but the supplier is in {_state(supplier)} and the place of supply is "
                    f"{_state(pos)} – IGST was due. Ask the supplier for a corrected invoice.")))
            elif charged == "intra" and pos != client_state:
                out.append(TaxIssue(doc, "other_state", (
                    f"CGST + SGST of {_state(pos)} charged (e.g. hotel or event there) – not ITC of your "
                    f"registration in {_state(client_state)}.")))
    else:  # own sales
        customer = doc.gstin[:2] if len(doc.gstin) == 15 else None
        export = bool(EXPORT.search(doc.supply_type or "")) or (pos_code(doc.place_of_supply) or "") in ("96", "97")
        pos = pos_code(doc.place_of_supply) or customer or client_state
        if charged in ("inter", "intra"):
            expected = "inter" if export or pos != client_state else "intra"
            if charged != expected:
                out.append(TaxIssue(doc, "tax_type", (
                    "CGST + SGST charged on an export / SEZ supply – IGST (or zero-rated under LUT) was due."
                    if export else
                    f"CGST + SGST charged, but the place of supply is {_state(pos)} and you are in "
                    f"{_state(client_state)} – IGST was due." if expected == "inter" else
                    f"IGST charged, but you and the place of supply are both in {_state(pos)} – CGST + SGST "
                    "was due.")))
    if charged == "both":
        out.append(TaxIssue(doc, "tax_type", "Both IGST and CGST/SGST charged on one document."))
    lines = doc.lines if len(doc.lines) > 1 else ((doc.taxable, doc.igst, doc.cgst, doc.sgst),)
    bad = [ln for ln in lines if fits_rate(*ln) is None]
    if bad:
        tax = doc.igst + doc.cgst + doc.sgst
        pct = (tax * 100 / doc.taxable).quantize(Decimal("0.01")) if doc.taxable else ZERO
        mixed = " (or items at different rates combined in one bill)" if len(doc.lines) <= 1 else ""
        out.append(TaxIssue(doc, "rate", f"Tax is {pct} % of the taxable value – not a GST rate{mixed}. Check the "
                                         "tax calculation."))
    return out
