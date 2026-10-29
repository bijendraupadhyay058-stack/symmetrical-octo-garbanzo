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
    if isinstance(data.get("invdata"), dict) or isinstance(data.get("imsdata"), dict):
        return "IMS"
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


def _other_itc(section: str, payload) -> list[dict]:
    """ISD credits and imports (bills of entry) from GSTR-2B – reported in GSTR-3B Table 4(A)(4)/4(A)(1)."""
    out = []

    def amt(d, *keys):
        for k in keys:
            if d.get(k) is not None:
                return parse_amount(d.get(k)) or ZERO
        return ZERO

    if section in ("isd", "isda"):
        for sup in payload:
            for d in sup.get("doclist", sup.get("docs", [])):
                out.append({"section": section.upper(), "party": sup.get("ctin", ""), "doc_type": d.get("doctyp", ""),
                            "doc_no": d.get("docnum", ""), "doc_date": d.get("docdt"), "taxable": ZERO,
                            "igst": amt(d, "igst"), "cgst": amt(d, "cgst"), "sgst": amt(d, "sgst"),
                            "cess": amt(d, "cess"), "itc_availability": str(d.get("itcelg", "")).upper()[:1]})
    elif section == "impg":
        for d in payload:
            out.append({"section": "IMPG", "party": d.get("portcode", ""), "doc_type": "BOE",
                        "doc_no": str(d.get("boenum", "")), "doc_date": d.get("boedt"), "taxable": amt(d, "txval"),
                        "igst": amt(d, "igst"), "cgst": ZERO, "sgst": ZERO, "cess": amt(d, "cess"),
                        "itc_availability": "Y"})
    elif section == "impgsez":
        for sup in payload:
            for d in sup.get("boe", []):
                out.append({"section": "IMPGSEZ", "party": sup.get("ctin", ""), "doc_type": "BOE",
                            "doc_no": str(d.get("boenum", "")), "doc_date": d.get("boedt"),
                            "taxable": amt(d, "txval"), "igst": amt(d, "igst"), "cgst": ZERO, "sgst": ZERO,
                            "cess": amt(d, "cess"), "itc_availability": "Y"})
    return out


OTHER_ITC_SECTIONS = {"isd", "isda", "impg", "impgsez"}


def flatten_gstr2b(js: dict) -> tuple[list[dict], str | None, list[str], list[dict]]:
    data = js.get("data", js)
    period = parse_period(data.get("rtnprd"))
    docdata = data.get("docdata", {})
    rows, warnings, other = [], [], []
    names = {"taxable_value": "txval", "igst": "igst", "cgst": "cgst", "sgst": "sgst", "cess": "cess"}
    for section, payload in docdata.items():
        if section in OTHER_ITC_SECTIONS and isinstance(payload, list):
            other.extend(_other_itc(section, payload))
            continue
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
    return rows, period, warnings, other


_IMS_SECTIONS = {
    "b2b": ("INV", False), "b2ba": ("INV", True), "cn": ("C", False), "cna": ("C", True), "dn": ("D", False),
    "dna": ("D", True), "b2bcn": ("C", False), "b2bdn": ("D", False), "ecom": ("INV", False),
    "ecoma": ("INV", True),
}


def flatten_ims(js: dict) -> tuple[list[dict], str | None, list[str]]:
    """IMS download (recipient view). Field names follow the portal's GSTN JSON conventions;
    common alternatives are accepted so exports from different tools also load."""
    data = js.get("data", js)
    inv = data.get("invdata") or data.get("imsdata") or {}
    period = parse_period(data.get("rtnprd") or data.get("ret_period"))
    rows, warnings = [], []
    for section, payload in inv.items():
        if not isinstance(payload, list):
            continue
        if section not in _IMS_SECTIONS:
            warnings.append(f"IMS section '{section}' ({len(payload)} records) is not compared in this version")
            continue
        doc_type, amendment = _IMS_SECTIONS[section]
        for i, d in enumerate(payload):
            rows.append({
                "supplier_gstin": d.get("stin") or d.get("ctin"), "supplier_name": d.get("trdnm", ""),
                "invoice_no": d.get("inum") or d.get("ntnum") or d.get("docnum"),
                "invoice_date": d.get("idt") or d.get("dt") or d.get("ntdt") or d.get("docdt"),
                "invoice_value": d.get("val"), "taxable_value": d.get("txval"),
                "igst": d.get("iamt", d.get("igst")), "cgst": d.get("camt", d.get("cgst")),
                "sgst": d.get("samt", d.get("sgst")), "cess": d.get("csamt", d.get("cess")),
                "place_of_supply": d.get("pos"), "doc_type": doc_type, "ims_action": d.get("action") or "N",
                "original_invoice_no": d.get("oinum") or d.get("ontnum"),
                "original_invoice_date": d.get("oidt") or d.get("ontdt"), "supplier_period": d.get("rtnprd"),
                "_amendment": amendment, "_sheet": section, "_row": f"{section}[{i}]",
            })
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
