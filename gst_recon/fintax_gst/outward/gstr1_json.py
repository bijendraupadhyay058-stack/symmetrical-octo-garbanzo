"""GSTR-1 JSON from the client's sales register (for the GST portal / GST Offline Tool).

Each sales document is placed in its GSTR-1 table:

* **B2B** (Table 4) – customer GSTIN; SEZ supplies with ``inv_typ`` SEWP / SEWOP, deemed exports DE;
  reverse-charge supplies with ``rchrg`` Y.
* **B2CL** (Table 5) – unregistered customer, inter-state, invoice value above ₹1,00,000 (₹2,50,000 before
  1 August 2024).
* **B2CS** (Table 7) – other unregistered supplies, summed by type, place of supply and rate; credit and
  debit notes to unregistered customers below the B2CL limit are netted here.
* **CDNR / CDNUR** (Table 9B) – credit and debit notes to registered customers / for B2CL and exports.
* **EXP** (Table 6A) – exports with (WPAY) or without (WOPAY) payment of IGST.
* **NIL** (Table 8) – nil-rated, exempt and non-GST supplies by inter / intra-state and B2B / B2C.
* **HSN** (Table 12) – from the HSN lines of the register, split B2B / B2C.
* **DOC_ISSUE** (Table 13) – invoice and credit / debit note series with the numbers in between counted as
  issued; gaps are reported (they are taken as cancelled – check them).

Every item gets a GST rate worked out from its tax. A document that does not fit a rate, or that misses
what its table needs, is left out and listed with the reason – nothing is guessed silently. The file is a
draft: open it in the GST Offline Tool (or upload it) and check it before filing.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..compliance.tax_checks import EXPORT, fits_rate, pos_code
from ..core.gstin import validate_gstin
from ..core.money import ZERO, q2

B2CL_LIMIT_OLD, B2CL_LIMIT = Decimal("250000"), Decimal("100000")
B2CL_FROM = date(2024, 8, 1)
DOC_NATURE = {"INV": (1, "Invoices for outward supply"), "DBN": (4, "Debit Note"), "CRN": (5, "Credit Note")}


@dataclass
class SaleDoc:
    id: int
    gstin: str  # customer's ('' for unregistered)
    name: str
    doc_type: str  # INV / CRN / DBN (as issued by the client)
    number: str
    date: date
    taxable: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    value: Decimal | None = None
    place_of_supply: str = ""
    supply_type: str = ""
    reverse_charge: bool = False
    hsn_lines: list = field(default_factory=list)  # dicts: hsn, uqc, qty, taxable, igst, cgst, sgst, cess


@dataclass
class Gstr1Issue:
    doc: SaleDoc | None
    severity: str  # error (left out) / warning
    message: str


@dataclass
class Gstr1Draft:
    payload: dict
    issues: list[Gstr1Issue]
    counts: dict[str, int]
    totals: dict[str, dict[str, Decimal]]


def _f(v: Decimal) -> float:
    return float(q2(v))


def _invoice_value(d: SaleDoc) -> Decimal:
    return d.value if d.value else d.taxable + d.igst + d.cgst + d.sgst + d.cess


def _item(d: SaleDoc, rate: Decimal, num: int = 1, taxable=None, igst=None, cgst=None, sgst=None, cess=None) -> dict:
    t = {"txval": _f(taxable if taxable is not None else d.taxable), "rt": float(rate)}
    i, c, s, cs = (igst if igst is not None else d.igst, cgst if cgst is not None else d.cgst,
                   sgst if sgst is not None else d.sgst, cess if cess is not None else d.cess)
    if i:
        t["iamt"] = _f(i)
    else:
        t["camt"], t["samt"] = _f(c), _f(s)
    t["csamt"] = _f(cs)
    return {"num": num, "itm_det": t}


def _items(d: SaleDoc) -> tuple[list[dict], str]:
    """GSTR-1 items (one per rate) and an error text when the tax fits no GST rate."""
    lines = [(Decimal(str(h.get("taxable") or 0)), Decimal(str(h.get("igst") or 0)), Decimal(str(h.get("cgst") or 0)),
              Decimal(str(h.get("sgst") or 0)), Decimal(str(h.get("cess") or 0))) for h in d.hsn_lines]
    if len(lines) <= 1:
        lines = [(d.taxable, d.igst, d.cgst, d.sgst, d.cess)]
    by_rate: dict[Decimal, list[Decimal]] = {}
    for tx, i, c, s, cs in lines:
        rate = fits_rate(tx, i, c, s)
        if rate is None:
            pct = ((i + c + s) * 100 / tx).quantize(Decimal("0.01")) if tx else ZERO
            return [], f"tax is {pct} % of the taxable value – not a GST rate (give HSN lines per rate)"
        rate = ZERO if (i + c + s) == 0 else rate
        acc = by_rate.setdefault(rate, [ZERO] * 5)
        for k, v in enumerate((tx, i, c, s, cs)):
            acc[k] += v
    return [_item(d, r, n, *vals) for n, (r, vals) in enumerate(sorted(by_rate.items()), start=1)], ""


def _kind(d: SaleDoc, client_state: str) -> str:
    text = f"{d.supply_type} {d.place_of_supply}"
    if re.search(r"non.?gst", text, re.I):
        return "NONGST"
    if (d.igst + d.cgst + d.sgst) == 0 and re.search(r"nil", text, re.I):
        return "NIL"
    if (d.igst + d.cgst + d.sgst) == 0 and re.search(r"exempt", text, re.I):
        return "EXEMPT"
    if re.search(r"sez", d.supply_type, re.I):
        return "SEZ"
    if re.search(r"deemed", d.supply_type, re.I):
        return "DE"
    if EXPORT.search(d.supply_type or "") or (pos_code(d.place_of_supply) or "") in ("96", "97"):
        return "EXP"
    return "B2B" if d.gstin else "B2C"


def build_gstr1(gstin: str, period: str, docs: list[SaleDoc], client_state: str | None = None) -> Gstr1Draft:
    client_state = client_state or gstin[:2]
    issues: list[Gstr1Issue] = []
    b2b: dict[str, list] = defaultdict(list)
    cdnr: dict[str, list] = defaultdict(list)
    b2cl: dict[str, list] = defaultdict(list)
    b2cs: dict[tuple, dict] = {}
    cdnur, nil = [], defaultdict(lambda: {"expt_amt": ZERO, "nil_amt": ZERO, "ngsup_amt": ZERO})
    exp: dict[str, list] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))

    def tally(section: str, d: SaleDoc, sign: int = 1) -> None:
        counts[section] += 1
        for k in ("taxable", "igst", "cgst", "sgst", "cess"):
            totals[section][k] += sign * getattr(d, k)

    for d in sorted(docs, key=lambda x: (x.date, x.number)):
        kind = _kind(d, client_state)
        if d.gstin and kind not in ("EXP",):
            ok, problem = validate_gstin(d.gstin)
            if not ok or problem:  # the portal rejects the whole file for one invalid GSTIN
                issues.append(Gstr1Issue(d, "error", f"customer GSTIN {d.gstin}: {problem} – left out"))
                continue
        if kind in ("NIL", "EXEMPT", "NONGST"):
            inter = (pos_code(d.place_of_supply) or (d.gstin[:2] if d.gstin else client_state)) != client_state
            key = f"{'INTR' if inter else 'INTRA'}{'B2B' if d.gstin else 'B2C'}"
            sign = -1 if d.doc_type == "CRN" else 1
            nil[key][{"NIL": "nil_amt", "EXEMPT": "expt_amt", "NONGST": "ngsup_amt"}[kind]] += sign * d.taxable
            tally("NIL", d, sign)
            continue
        items, problem = _items(d)
        if problem:
            issues.append(Gstr1Issue(d, "error", f"{problem} – left out"))
            continue
        val = _invoice_value(d)
        pos = pos_code(d.place_of_supply) or (d.gstin[:2] if d.gstin and kind != "EXP" else client_state)
        rchrg = "Y" if d.reverse_charge else "N"
        is_note = d.doc_type in ("CRN", "DBN")
        if kind == "EXP":
            exp_typ = "WPAY" if d.igst > 0 else "WOPAY"
            if d.cgst or d.sgst:
                issues.append(Gstr1Issue(d, "error", "export with CGST/SGST – IGST (or LUT) was due; left out"))
                continue
            if is_note:
                cdnur.append({"typ": f"EXP{exp_typ}", "ntty": "C" if d.doc_type == "CRN" else "D", "nt_num": d.number,
                              "nt_dt": f"{d.date:%d-%m-%Y}", "val": _f(val), "itms": items})
                tally("CDNUR", d, -1 if d.doc_type == "CRN" else 1)
            else:
                exp[exp_typ].append({"inum": d.number, "idt": f"{d.date:%d-%m-%Y}", "val": _f(val), "itms": [
                    {"txval": it["itm_det"]["txval"], "rt": it["itm_det"]["rt"], "iamt": it["itm_det"].get("iamt", 0.0),
                     "csamt": it["itm_det"]["csamt"]} for it in items]})
                tally("EXP", d)
                issues.append(Gstr1Issue(d, "warning", "export: add the shipping bill number, date and port code in "
                                                       "the Offline Tool if available"))
            continue
        if kind in ("B2B", "SEZ", "DE"):
            inv_typ = {"B2B": "R", "SEZ": "SEWP" if d.igst > 0 else "SEWOP", "DE": "DE"}[kind]
            doc = {"val": _f(val), "pos": pos, "rchrg": rchrg, "inv_typ": inv_typ, "itms": items}
            if is_note:
                cdnr[d.gstin].append({"ntty": "C" if d.doc_type == "CRN" else "D", "nt_num": d.number,
                                      "nt_dt": f"{d.date:%d-%m-%Y}", **doc})
                tally("CDNR", d, -1 if d.doc_type == "CRN" else 1)
            else:
                b2b[d.gstin].append({"inum": d.number, "idt": f"{d.date:%d-%m-%Y}", **doc})
                tally("B2B", d)
            continue
        # unregistered customers
        inter = pos != client_state
        limit = B2CL_LIMIT if d.date >= B2CL_FROM else B2CL_LIMIT_OLD
        if inter and val > limit:
            if is_note:
                cdnur.append({"typ": "B2CL", "ntty": "C" if d.doc_type == "CRN" else "D", "nt_num": d.number,
                              "nt_dt": f"{d.date:%d-%m-%Y}", "val": _f(val), "pos": pos, "itms": items})
                tally("CDNUR", d, -1 if d.doc_type == "CRN" else 1)
            else:
                b2cl[pos].append({"inum": d.number, "idt": f"{d.date:%d-%m-%Y}", "val": _f(val), "itms": items})
                tally("B2CL", d)
            continue
        sign = -1 if d.doc_type == "CRN" else 1
        for it in items:
            t = it["itm_det"]
            key = ("INTER" if inter else "INTRA", pos, t["rt"])
            row = b2cs.setdefault(key, {"txval": ZERO, "iamt": ZERO, "camt": ZERO, "samt": ZERO, "csamt": ZERO})
            for k in row:
                row[k] += sign * Decimal(str(t.get(k, 0)))
        tally("B2CS", d, sign)

    payload: dict = {"gstin": gstin, "fp": f"{period[5:]}{period[:4]}"}
    if b2b:
        payload["b2b"] = [{"ctin": g, "inv": inv} for g, inv in sorted(b2b.items())]
    if b2cl:
        payload["b2cl"] = [{"pos": p, "inv": inv} for p, inv in sorted(b2cl.items())]
    if b2cs:
        payload["b2cs"] = [{"sply_ty": st, "pos": p, "typ": "OE", "rt": rt,
                            **{k: _f(v) for k, v in vals.items() if not (st == "INTRA" and k == "iamt")
                               and not (st == "INTER" and k in ("camt", "samt"))}}
                           for (st, p, rt), vals in sorted(b2cs.items())]
    if cdnr:
        payload["cdnr"] = [{"ctin": g, "nt": nt} for g, nt in sorted(cdnr.items())]
    if cdnur:
        payload["cdnur"] = cdnur
    if exp:
        payload["exp"] = [{"exp_typ": t, "inv": inv} for t, inv in sorted(exp.items())]
    if nil:
        payload["nil"] = {"inv": [{"sply_ty": k, **{a: _f(b) for a, b in v.items()}} for k, v in sorted(nil.items())]}
    hsn, hsn_issues = _hsn(docs, client_state)
    issues += hsn_issues
    if hsn:
        payload["hsn"] = hsn
    doc_issue, doc_issues = _doc_issue(docs)
    issues += doc_issues
    if doc_issue:
        payload["doc_issue"] = {"doc_det": doc_issue}
    return Gstr1Draft(payload, issues, dict(counts), {k: dict(v) for k, v in totals.items()})


def _hsn(docs: list[SaleDoc], client_state: str) -> tuple[dict, list[Gstr1Issue]]:
    groups: dict[str, dict[tuple, dict]] = {"hsn_b2b": {}, "hsn_b2c": {}}
    issues, missing = [], 0
    for d in docs:
        if not d.hsn_lines:
            missing += 1
            continue
        sign = -1 if d.doc_type == "CRN" else 1
        seg = "hsn_b2b" if d.gstin else "hsn_b2c"
        for h in d.hsn_lines:
            vals = {k: Decimal(str(h.get(k) or 0)) for k in ("taxable", "igst", "cgst", "sgst", "cess", "qty")}
            rate = fits_rate(vals["taxable"], vals["igst"], vals["cgst"], vals["sgst"])
            code = str(h.get("hsn") or "")
            uqc = "NA" if code.startswith("99") else (str(h.get("uqc") or "").upper() or "OTH")
            key = (code, uqc, float(rate if rate is not None and (vals["igst"] + vals["cgst"] + vals["sgst"]) else 0))
            g = groups[seg].setdefault(key, {k: ZERO for k in vals})
            for k, v in vals.items():
                g[k] += sign * v
    if missing:
        issues.append(Gstr1Issue(None, "warning", f"{missing} document(s) have no HSN lines in the sales register – "
                                                  "Table 12 (HSN summary) covers only the others"))
    out = {}
    for seg, rows in groups.items():
        if rows:
            out[seg] = [{"num": n, "hsn_sc": code, "uqc": uqc, "rt": rt, "qty": _f(v["qty"]), "txval": _f(v["taxable"]),
                         "iamt": _f(v["igst"]), "camt": _f(v["cgst"]), "samt": _f(v["sgst"]), "csamt": _f(v["cess"])}
                        for n, ((code, uqc, rt), v) in enumerate(sorted(rows.items()), start=1)]
    return out, issues


_SERIES = re.compile(r"^(.*?)(\d+)(\D*)$")


def _doc_issue(docs: list[SaleDoc]) -> tuple[list[dict], list[Gstr1Issue]]:
    issues, out = [], []
    for doc_type, (doc_num, label) in DOC_NATURE.items():
        series: dict[tuple, list[tuple[int, str]]] = defaultdict(list)
        for d in docs:
            if d.doc_type != doc_type:
                continue
            m = _SERIES.match(d.number.strip())
            if not m:
                issues.append(Gstr1Issue(d, "warning", f"{label} number '{d.number}' has no running number – not in "
                                                       "Table 13"))
                continue
            series[(m.group(1), m.group(3), len(m.group(2)))].append((int(m.group(2)), d.number))
        rows = []
        for n, ((_pre, _suf, _w), nums) in enumerate(sorted(series.items()), start=1):
            nums.sort()
            first, last = nums[0], nums[-1]
            total = last[0] - first[0] + 1
            cancelled = total - len({x for x, _ in nums})
            if cancelled:
                issues.append(Gstr1Issue(None, "warning", f"{label}: {cancelled} number(s) between {first[1]} and "
                                                          f"{last[1]} are not in the sales register – counted as "
                                                          "cancelled in Table 13; check them"))
            rows.append({"num": n, "from": first[1], "to": last[1], "totnum": total, "cancel": cancelled,
                         "net_issue": total - cancelled})
        if rows:
            out.append({"doc_num": doc_num, "doc_typ": label, "docs": rows})
    return out, issues
