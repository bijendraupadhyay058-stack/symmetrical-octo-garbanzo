"""Draft GSTR-9 JSON for the GST offline tool, with a mapping of every figure.

The draft is built from the GSTR-9 working and the Table 8 working only. Nothing is
guessed:

* a figure the data cannot split the way the return asks is left out, and the
  mapping says *enter in the offline tool*. Examples are inputs / capital goods /
  input services in 6B and 6E, registered / unregistered in 6C / 6D, rules 37–43 and
  section 17(5) in 7A–7G, and the ITC used for each tax head in Table 9;
* sub-totals and differences (4H, 4M, 4N, 5G, 5L–5N, 6I, 6J, 7I, 7J, 8D) are left to
  the offline tool, which computes them.

The key names follow the GSTR-9 JSON published by GSTN, as understood when this module
was written. The file is a **draft for review**: import it into the offline tool, which
validates it, check every table there, and upload only what the tool produces. This
software never files anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..importers.gstr3b import Gstr3bValues
from ..itc.annual import Table8
from .working import LABELS, Gstr9Working

STATUS_INCLUDED = "included"
STATUS_COMPUTED = "computed by the offline tool"
STATUS_MANUAL = "enter in the offline tool"

TABLE4_KEYS = {"4A": "b2c", "4B": "b2b", "4C": "exp", "4D": "sez", "4E": "deemed", "4F": "at", "4G": "rchrg",
               "4I": "cr_nt", "4J": "dr_nt", "4K": "amd_pos", "4L": "amd_neg"}
TABLE5_KEYS = {"5A": "zero_rtd", "5B": "sez", "5C": "rchrg", "5D": "exmt", "5E": "nil", "5F": "non_gst",
               "5H": "cr_nt", "5I": "dr_nt", "5J": "amd_pos", "5K": "amd_neg"}
TABLE6_KEYS = {"6A": "itc_3b", "6F": "ios", "6G": "isd", "6H": "itc_clmd"}
TABLE10_KEYS = {"10": "dbn_amd", "11": "cdn_amd", "12": "itc_rvsl", "13": "itc_availd"}
TABLE15_KEYS = {"15A": "rfd_clmd", "15B": "rfd_sanc", "15C": "rfd_rejt", "15D": "rfd_pend", "15E": "tax_dmnd",
                "15F": "tax_paid", "15G": "dmnd_pend"}
TABLE15_COLS = {"C": "camt", "S": "samt", "I": "iamt", "X": "csamt", "N": "intr", "P": "pen", "L": "fee"}
TABLE16_KEYS = {"16A": "comp_supp", "16B": "deemed_supp", "16C": "not_returned"}
TABLE16_COLS = {"T": "txval", "C": "camt", "S": "samt", "I": "iamt", "X": "csamt"}
SUBTOTALS = ["4H", "4M", "4N", "5G", "5L", "5M", "5N", "6I", "6J", "7I", "7J", "8D"]
MANUAL = [
    ("6B", "Inward supplies other than imports and reverse charge – split into inputs, capital goods and input "
           "services", "GSTR-3B 4(A)(5) is one figure"),
    ("6C / 6D", "Inward supplies liable to reverse charge – from unregistered / registered persons, split by "
                "inputs, capital goods and input services", "GSTR-3B 4(A)(3) is one figure"),
    ("6E", "Import of goods – split into inputs and capital goods", "GSTR-3B 4(A)(1) is one figure"),
    ("6K–6M", "Transition credit (TRAN-I / TRAN-II) and any other ITC", "not in the imported data"),
    ("7A–7G", "Reversals under rules 37, 39, 42, 43 and section 17(5), TRAN-I / TRAN-II",
     "GSTR-3B 4(B)(1) is one figure"),
    ("8E–8K", "ITC not availed / ineligible, IGST on imports and ITC availed on it", "not derived by this software"),
    ("9", "Tax paid through ITC, by the credit used for each tax head", "GSTR-3B 6.1 is stored by liability head only"),
    ("14", "Differential tax paid on account of Tables 10 and 11", "payment is through the next year's GSTR-3B or "
                                                                   "DRC-03 and is not split out"),
]


def _round(v: Decimal) -> float:
    return float(v.quantize(Decimal("0.01")))


def _tax(v: Gstr3bValues, taxable: bool = True) -> dict:
    out = {"txval": _round(v.taxable)} if taxable else {}
    out.update(iamt=_round(v.igst), camt=_round(v.cgst), samt=_round(v.sgst), csamt=_round(v.cess))
    return out


@dataclass
class MappingRow:
    table: str
    description: str
    json_path: str
    value: str
    status: str
    note: str = ""


def build_draft(w: Gstr9Working, t8: Table8 | None, gstin: str, fy: str) -> tuple[dict, list[MappingRow]]:
    rows: list[MappingRow] = []

    def put(section: dict, table: str, key: str, path: str, payload, label: str | None = None, note: str = ""):
        section[key] = payload
        total = payload.get("txval") if isinstance(payload, dict) else None
        heads = [v for k, v in payload.items() if k in ("iamt", "camt", "samt", "csamt")]
        tax = sum(heads) if heads else None
        value = "; ".join(x for x in (f"taxable {total:,.2f}" if total is not None else "",
                                      f"tax {tax:,.2f}" if tax is not None else "") if x)
        rows.append(MappingRow(table, label or LABELS.get(table, table), f"{path}.{key}", value or "see JSON",
                               STATUS_INCLUDED, note))

    payload: dict = {"gstin": gstin, "fp": f"03{int(fy[:4]) + 1}"}
    rows.append(MappingRow("–", "GSTIN and financial year (return period March of the year's end)", "gstin, fp",
                           f"{gstin}, 03{int(fy[:4]) + 1}", STATUS_INCLUDED))

    t4: dict = {}
    by_code = {r.code: r for r in w.table4}
    for code, key in TABLE4_KEYS.items():
        r = by_code.get(code)
        if r is not None and r.gstr1 is not None:
            put(t4, code, key, "table4", _tax(r.gstr1), note=r.note)
    payload["table4"] = t4
    t5: dict = {}
    by_code = {r.code: r for r in w.table5}
    for code, key in TABLE5_KEYS.items():
        r = by_code.get(code)
        if r is not None and r.gstr1 is not None:
            put(t5, code, key, "table5", {"txval": _round(r.gstr1.taxable)}, note=r.note)
    payload["table5"] = t5

    t6: dict = {}
    by_code = {r.code: r for r in w.table6}
    for code, key in TABLE6_KEYS.items():
        r = by_code.get(code)
        if r is not None and r.gstr1 is not None:
            put(t6, code, key, "table6", _tax(r.gstr1, taxable=False), note=r.note)
    payload["table6"] = t6
    t7: dict = {}
    other = next((r for r in w.table7 if r.code == "7H"), None)
    if other is not None and other.gstr1 is not None and other.gstr1.total:
        t7["other"] = [{"desc": "Other reversals (GSTR-3B 4(B)(2))", **_tax(other.gstr1, taxable=False)}]
        rows.append(MappingRow("7H", LABELS["7H"], "table7.other[0]", f"tax {other.gstr1.total:,.2f}",
                               STATUS_INCLUDED, other.note))
    payload["table7"] = t7

    if t8 is not None:
        t8d: dict = {}
        put(t8d, "8A", "itc_2a", "table8", _tax(t8.a, taxable=False), "ITC as per GSTR-2B (Table 8A)",
            "; ".join(t8.basis_notes()))
        put(t8d, "8B", "itc_tot", "table8", _tax(t8.b, taxable=False), "ITC as per 6B and 6H")
        put(t8d, "8C", "itc_inwd_supp", "table8", _tax(t8.c, taxable=False),
            "ITC on inward supplies of the year availed in the next year (up to the cut-off)")
        payload["table8"] = t8d
    else:
        rows.append(MappingRow("8A–8C", "ITC as per GSTR-2B and as availed", "table8", "", STATUS_MANUAL,
                               "Table 8 working not available"))

    t9: dict = {}
    for t in w.table9:
        key = {"igst": "iamt", "cgst": "camt", "sgst": "samt", "cess": "csamt"}[t.head.lower()]
        entry = {"txpyble": _round(t.payable)}
        if t.paid_cash is not None:
            entry["txpaid_cash"] = _round(t.paid_cash)
        t9[key] = entry
        rows.append(MappingRow("9", f"Tax payable / paid in cash – {t.head.upper()}", f"table9.{key}",
                               f"payable {t.payable:,.2f}; cash "
                               + (f"{t.paid_cash:,.2f}" if t.paid_cash is not None else "not imported"),
                               STATUS_INCLUDED, "paid through ITC: enter in the offline tool"))
    for key, amount, label in (("intr", w.interest_paid, "Interest paid in cash"),
                               ("fee", w.late_fee_paid, "Late fee paid in cash")):
        if amount is not None:
            t9[key] = {"txpaid_cash": _round(amount)}
            rows.append(MappingRow("9", label, f"table9.{key}", f"{amount:,.2f}", STATUS_INCLUDED,
                                   "amount payable: enter in the offline tool"))
    payload["table9"] = t9

    t10: dict = {}
    by_code = {r.code: r for r in w.table10_14}
    for code, key in TABLE10_KEYS.items():
        r = by_code.get(code)
        if r is not None and r.gstr1 is not None:
            put(t10, code, key, "table10", _tax(r.gstr1, taxable=code in ("10", "11")), note=r.note)
    payload["table10"] = t10

    def entered(table, keys, cols, name):
        out = {}
        for r in table:
            vals = {cols[c]: _round(v) for c, v in r.values.items() if c in cols}
            if any(vals.values()):
                out[keys[r.code]] = vals
                rows.append(MappingRow(r.code, r.label, f"{name}.{keys[r.code]}",
                                       "; ".join(f"{k} {v:,.2f}" for k, v in vals.items() if v), STATUS_INCLUDED,
                                       "; ".join(r.notes)))
        if out:
            payload[name] = out

    entered(w.table15, TABLE15_KEYS, TABLE15_COLS, "table15")
    entered(w.table16, TABLE16_KEYS, TABLE16_COLS, "table16")
    if not any(k in payload for k in ("table15", "table16")):
        rows.append(MappingRow("15–16", "Refunds and demands; composition, deemed and approval supplies",
                               "table15, table16", "", STATUS_MANUAL, "nothing entered for the year"))

    def hsn_items(items):
        out = []
        for g in items:
            item = {"hsn_sc": g["hsn"], "uqc": g.get("uqc") or "NA", "desc": (g.get("description") or "")[:30],
                    "isconcesstional": "N", "qty": _round(Decimal(str(g.get("qty") or 0))),
                    "txval": _round(g["taxable"]), "iamt": _round(g["igst"]), "camt": _round(g["cgst"]),
                    "samt": _round(g["sgst"]), "csamt": _round(g["cess"])}
            if g.get("rate") not in (None, ""):
                item["rt"] = float(Decimal(str(g["rate"])))
            out.append(item)
        return out

    for name, items, code in (("table17", w.table17, "17"), ("table18", w.table18, "18")):
        if items:
            payload[name] = {"items": hsn_items(items)}
            rows.append(MappingRow(code, f"HSN-wise summary ({'outward' if code == '17' else 'inward'})",
                                   f"{name}.items", f"{len(items)} line(s)", STATUS_INCLUDED))
        else:
            rows.append(MappingRow(code, f"HSN-wise summary ({'outward' if code == '17' else 'inward'})",
                                   f"{name}.items", "", STATUS_MANUAL, "no HSN data imported"))

    for code in SUBTOTALS:
        rows.append(MappingRow(code, LABELS.get(code, "Difference (A − (B + C))" if code == "8D" else code), "",
                               "", STATUS_COMPUTED))
    for code, label, why in MANUAL:
        rows.append(MappingRow(code, label, "", "", STATUS_MANUAL, why))
    for n in w.notes:
        rows.append(MappingRow("note", n, "", "", "check"))
    return payload, rows
