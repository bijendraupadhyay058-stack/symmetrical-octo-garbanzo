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


def detect_json_kind(js: dict, hint: str | None = None) -> str | None:
    data = js.get("data", js) if isinstance(js, dict) else None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("itc_elg"), dict) or isinstance(data.get("sup_details"), dict):
        return "GSTR3B"
    if set(data) & GSTR1_ONLY_KEYS:
        return "GSTR1"
    if hint == "GSTR1" and isinstance(data.get("b2b"), list) and not any(
            "cfs" in s for s in data["b2b"] if isinstance(s, dict)):
        return "GSTR1"
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


# ---------------------------------------------------------------- GSTR-1
GSTR1_ONLY_KEYS = {"b2cs", "b2cl", "exp", "hsn", "nil", "doc_issue", "cdnur", "at", "txpd", "b2csa", "expa"}


def _items_total(doc: dict) -> dict[str, Decimal]:
    out = {"taxable": ZERO, "igst": ZERO, "cgst": ZERO, "sgst": ZERO, "cess": ZERO}
    for it in doc.get("itms", []) or [doc]:
        det = it.get("itm_det", it)
        for k, key in (("taxable", "txval"), ("igst", "iamt"), ("cgst", "camt"), ("sgst", "samt"),
                       ("cess", "csamt")):
            out[k] += parse_amount(det.get(key)) or ZERO
    return out


def flatten_gstr1(js: dict) -> tuple[list[dict], str | None, list[str], list[dict]]:
    """GSTR-1 (GSTN JSON). Returns invoice-level rows for registered recipients (B2B, CDNR and their
    amendments) and section summaries for every section (for the GSTR-1 vs GSTR-3B comparison)."""
    data = js.get("data", js)
    period = parse_period(data.get("fp") or data.get("ret_period"))
    rows, warnings = [], []
    summary: dict[tuple, dict] = {}

    def add(section, supply, vals, pos="", rate="", sign=1, docs=1):
        key = (section, supply, str(pos or ""), str(rate or ""))
        s = summary.setdefault(key, {"section": section, "supply": supply, "pos": str(pos or ""),
                                     "rate": str(rate or ""), "doc_count": 0, "taxable": ZERO, "igst": ZERO,
                                     "cgst": ZERO, "sgst": ZERO, "cess": ZERO})
        s["doc_count"] += docs
        for k in ("taxable", "igst", "cgst", "sgst", "cess"):
            s[k] += vals[k] * sign

    def b2b_supply(doc) -> str:
        if str(doc.get("rchrg", "N")).upper() == "Y":
            return "RCM"
        return "SEZ" if str(doc.get("inv_typ", "R")).upper() in ("SEWP", "SEWOP") else "REG"

    for section, payload in data.items():
        if section in ("gstin", "fp", "ret_period", "gt", "cur_gt", "hsn", "doc_issue", "fil_dt", "rtnprd"):
            continue
        if section in ("b2b", "b2ba"):
            for si, sup in enumerate(payload):
                for di, doc in enumerate(sup.get("inv", [])):
                    vals = _items_total(doc)
                    supply = b2b_supply(doc)
                    add(section.upper(), supply, vals, doc.get("pos"))
                    rows.append({"supplier_gstin": sup.get("ctin"), "invoice_no": doc.get("inum"),
                                 "invoice_date": doc.get("idt"), "invoice_value": doc.get("val"),
                                 "place_of_supply": doc.get("pos"), "reverse_charge": doc.get("rchrg"),
                                 "doc_type": "INV", "supply_type": {"SEZ": "SEZ", "RCM": "Reverse charge"}.get(
                                     supply, doc.get("inv_typ", "R")),
                                 "original_invoice_no": doc.get("oinum"), "original_invoice_date": doc.get("oidt"),
                                 "taxable_value": vals["taxable"], "igst": vals["igst"], "cgst": vals["cgst"],
                                 "sgst": vals["sgst"], "cess": vals["cess"], "_amendment": section == "b2ba",
                                 "_sheet": section, "_row": f"{section}[{si}].inv[{di}]"})
        elif section in ("cdnr", "cdnra"):
            for si, sup in enumerate(payload):
                for di, doc in enumerate(sup.get("nt", [])):
                    vals = _items_total(doc)
                    ntty = str(doc.get("ntty", "C")).upper()
                    add(section.upper(), b2b_supply(doc), vals, doc.get("pos"), sign=-1 if ntty == "C" else 1)
                    rows.append({"supplier_gstin": sup.get("ctin"), "invoice_no": doc.get("nt_num"),
                                 "invoice_date": doc.get("nt_dt"), "invoice_value": doc.get("val"),
                                 "place_of_supply": doc.get("pos"), "reverse_charge": doc.get("rchrg"),
                                 "doc_type": ntty, "supply_type": doc.get("inv_typ", "R"),
                                 "original_invoice_no": doc.get("ont_num"), "original_invoice_date": doc.get("ont_dt"),
                                 "taxable_value": vals["taxable"], "igst": vals["igst"], "cgst": vals["cgst"],
                                 "sgst": vals["sgst"], "cess": vals["cess"], "_amendment": section == "cdnra",
                                 "_sheet": section, "_row": f"{section}[{si}].nt[{di}]"})
        elif section in ("b2cl", "b2cla"):
            for grp in payload:
                for doc in grp.get("inv", []):
                    add(section.upper(), "INTER", _items_total(doc), grp.get("pos"))
        elif section in ("b2cs", "b2csa"):
            for d in payload:
                add(section.upper(), str(d.get("sply_ty", "")).upper(), _items_total(d), d.get("pos"), d.get("rt"))
        elif section in ("exp", "expa"):
            for grp in payload:
                for doc in grp.get("inv", []):
                    add(section.upper(), str(grp.get("exp_typ", "")).upper(), _items_total(doc))
        elif section in ("cdnur", "cdnura"):
            for d in payload:
                ntty = str(d.get("ntty", "C")).upper()
                add(section.upper(), str(d.get("typ", "")).upper(), _items_total(d), d.get("pos"),
                    sign=-1 if ntty == "C" else 1)
        elif section == "nil":
            for d in (payload.get("inv", []) if isinstance(payload, dict) else payload):
                for key, sec in (("nil_amt", "NIL"), ("expt_amt", "EXEMPT"), ("ngsup_amt", "NONGST")):
                    amt = parse_amount(d.get(key)) or ZERO
                    if amt:
                        add(sec, str(d.get("sply_ty", "")).upper(),
                            {"taxable": amt, "igst": ZERO, "cgst": ZERO, "sgst": ZERO, "cess": ZERO})
        elif isinstance(payload, list):
            warnings.append(f"GSTR-1 section '{section}' ({len(payload)} entries) is not compared in this version")
    return rows, period, warnings, list(summary.values())
