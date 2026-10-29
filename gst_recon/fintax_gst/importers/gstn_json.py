"""GST portal JSON layouts (GSTR-2B and GSTR-2A) flattened to canonical rows.

Documents are taken at document level. Where the JSON carries only item-wise
values, items are summed. Sections not reconciled in this version are
reported back as warnings with their document counts, never ignored silently.
"""
from __future__ import annotations

from decimal import Decimal

from ..core.money import ZERO, parse_amount
from .parsing import parse_period

_2B_SECTIONS = {
    "b2b": ("inv", "INV", False), "b2ba": ("inv", "INV", True),
    "cdnr": ("nt", None, False), "cdnra": ("nt", None, True),
}
_2A_SECTIONS = {
    "b2b": ("inv", "INV", False), "b2ba": ("inv", "INV", True),
    "cdn": ("nt", None, False), "cdna": ("nt", None, True),
}


def detect_json_kind(js: dict) -> str | None:
    data = js.get("data", js) if isinstance(js, dict) else None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("docdata"), dict):
        return "GSTR2B"
    for key in ("b2b", "cdn", "b2ba", "cdna"):
        if isinstance(data.get(key), list):
            return "GSTR2A"
    return None


def _sum_items(doc: dict, item_key: str, inner: str | None, names: dict[str, str]) -> dict[str, Decimal | None]:
    totals: dict[str, Decimal | None] = {}
    items = doc.get(item_key) or []
    for canonical, key in names.items():
        direct = doc.get(key)
        if direct is not None:
            totals[canonical] = parse_amount(direct)
            continue
        if not items:
            totals[canonical] = None
            continue
        acc = ZERO
        for item in items:
            det = item.get(inner, item) if inner else item
            v = parse_amount(det.get(key))
            acc += v or ZERO
        totals[canonical] = acc
    return totals


def flatten_gstr2b(js: dict) -> tuple[list[dict], str | None, list[str]]:
    data = js.get("data", js)
    period = parse_period(data.get("rtnprd"))
    docdata = data.get("docdata", {})
    rows, warnings = [], []
    names = {"taxable_value": "txval", "igst": "igst", "cgst": "cgst", "sgst": "sgst", "cess": "cess"}
    for section, payload in docdata.items():
        if section not in _2B_SECTIONS:
            count = sum(len(s.get("inv", s.get("nt", s.get("doclist", [])))) if isinstance(s, dict) else 1
                        for s in payload) if isinstance(payload, list) else 0
            warnings.append(f"GSTR-2B section '{section}' ({count} documents) is not reconciled in this version")
            continue
        doc_key, fixed_type, amendment = _2B_SECTIONS[section]
        for si, supplier in enumerate(payload):
            for di, doc in enumerate(supplier.get(doc_key, [])):
                amounts = _sum_items(doc, "items", None, names)
                row = {
                    "supplier_gstin": supplier.get("ctin"), "supplier_name": supplier.get("trdnm"),
                    "supplier_period": supplier.get("supprd"),
                    "invoice_no": doc.get("inum") or doc.get("ntnum"), "invoice_date": doc.get("dt"),
                    "invoice_value": doc.get("val"), "place_of_supply": doc.get("pos"),
                    "reverse_charge": doc.get("rev"), "itc_availability": doc.get("itcavl"),
                    "itc_reason": doc.get("rsn"), "doc_type": fixed_type or doc.get("typ"),
                    "supply_type": doc.get("suptyp") or doc.get("typ"),
                    "original_invoice_no": doc.get("oinum") or doc.get("ontnum"),
                    "original_invoice_date": doc.get("oidt") or doc.get("ontdt"),
                    "_amendment": amendment, "_sheet": section, "_row": f"{section}[{si}].{doc_key}[{di}]",
                    **amounts,
                }
                if fixed_type == "INV":
                    row["supply_type"] = doc.get("typ")
                rows.append(row)
    return rows, period, warnings


def flatten_gstr2a(js: dict) -> tuple[list[dict], str | None, list[str]]:
    data = js.get("data", js)
    period = parse_period(data.get("fp") or data.get("ret_period"))
    rows, warnings = [], []
    names = {"taxable_value": "txval", "igst": "iamt", "cgst": "camt", "sgst": "samt", "cess": "csamt"}
    for section, payload in data.items():
        if not isinstance(payload, list):
            continue
        if section not in _2A_SECTIONS:
            warnings.append(f"GSTR-2A section '{section}' ({len(payload)} suppliers) is not reconciled in this version")
            continue
        doc_key, fixed_type, amendment = _2A_SECTIONS[section]
        for si, supplier in enumerate(payload):
            for di, doc in enumerate(supplier.get(doc_key, [])):
                amounts = _sum_items(doc, "itms", "itm_det", names)
                rows.append({
                    "supplier_gstin": supplier.get("ctin"), "supplier_name": supplier.get("trdnm", ""),
                    "supplier_period": supplier.get("fldtr1") or "",
                    "invoice_no": doc.get("inum") or doc.get("nt_num"),
                    "invoice_date": doc.get("idt") or doc.get("nt_dt"),
                    "invoice_value": doc.get("val"), "place_of_supply": doc.get("pos"),
                    "reverse_charge": doc.get("rchrg"), "doc_type": fixed_type or doc.get("ntty"),
                    "supply_type": doc.get("inv_typ"),
                    "original_invoice_no": doc.get("oinum") or doc.get("ont_num"),
                    "original_invoice_date": doc.get("oidt") or doc.get("ont_dt"),
                    "_amendment": amendment, "_sheet": section, "_row": f"{section}[{si}].{doc_key}[{di}]",
                    **amounts,
                })
    return rows, period, warnings
