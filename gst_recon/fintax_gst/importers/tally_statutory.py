"""TallyPrime statutory reports, turned into ordinary register rows so that the normal import (validation,
preview, duplicate protection) applies.

* **GSTR-1** – the export in the GST Offline Tool Excel format (sheets b2b / b2cl / b2cs / cdnr / cdnur / exp /
  exemp …, rate and taxable value only – the tax is worked out: IGST when the place of supply is in another
  state, otherwise CGST + SGST) or as JSON (portal format). B2B, B2CL, export and note documents become sales
  documents; B2CS and nil / exempt / non-GST lines (reported as totals) become one summary line each.
* **GSTR-2A / 2B reconciliation** – the purchase-side report: rows Tally marks as available only on the portal
  (not in the books) are left out with the reason; the rest are read as the purchase register.
"""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from decimal import Decimal

from ..compliance.tax_checks import pos_code
from ..core.money import ZERO, parse_amount
from .parsing import parse_date, parse_text

SALES_HEADERS = ["GSTIN", "Customer Name", "Invoice No", "Invoice Date", "Document Type", "Taxable Value", "IGST",
                 "CGST", "SGST", "Cess", "Invoice Value", "Place of Supply", "Reverse Charge", "Type of Supply"]
OFFLINE_SHEETS = {"b2b,sez,de", "b2b", "b2cl", "b2cs", "cdnr", "cdnur", "exp", "exemp"}


def is_gstr1_offline(tables) -> bool:
    names = {t.name.strip().lower() for t in tables}
    return bool(names & {"b2b,sez,de"}) or {"b2b", "b2cs"} <= names


def _n(v) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/%() ]", " ", str(v or "").lower())).strip()


def _d(v) -> Decimal:
    return parse_amount(v) or ZERO


def _tax(taxable: Decimal, rate: Decimal, pos: str, own_state: str) -> tuple[Decimal, Decimal, Decimal]:
    t = (taxable * rate / 100).quantize(Decimal("0.01"))
    if pos and pos != own_state:
        return t, ZERO, ZERO
    half = (t / 2).quantize(Decimal("0.01"))
    return ZERO, half, t - half


def _period_end(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{calendar.monthrange(y, m)[1]:02d}-{m:02d}-{y:04d}"


def _row(gstin="", name="", no="", dt="", doc="Invoice", taxable=ZERO, igst=ZERO, cgst=ZERO, sgst=ZERO, cess=ZERO,
         value=None, pos="", rc="N", supply="Regular") -> list:
    return [gstin, name, no, dt, doc, str(taxable), str(igst), str(cgst), str(sgst), str(cess),
            "" if value is None else str(value), pos, rc, supply]


def _table_rows(t) -> list[dict]:
    """Rows of an offline-tool sheet as {heading: value}, the heading row being the one with most known words."""
    header_at, header = None, None
    for i, (_n_, cells) in enumerate(t.rows[:12]):
        names = [_n(c) for c in cells]
        if sum(1 for x in names if x in ("invoice number", "note number", "gstin/uin of recipient", "rate",
                                         "taxable value", "type", "place of supply", "description", "nil rated supplies",
                                         "non gst supplies")) >= 2:
            header_at, header = i, names
    if header is None:
        return []
    out = []
    for n, cells in t.rows[header_at + 1:]:
        if not any(c not in (None, "") for c in cells):
            continue
        out.append({"_row": n, **{h: (cells[j] if j < len(cells) else None) for j, h in enumerate(header) if h}})
    return out


def gstr1_offline_rows(tables, own_state: str, period: str) -> tuple[list[list], list[str]]:
    """Sales rows (SALES_HEADERS order) from a GSTR-1 export in the Offline Tool Excel format."""
    rows, warnings = [], []
    docs: dict[tuple, list] = {}
    summary: dict[tuple, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO, ZERO])
    for t in tables:
        sheet = t.name.strip().lower()
        if sheet not in OFFLINE_SHEETS:
            continue
        for r in _table_rows(t):
            rate = _d(r.get("rate"))
            taxable = _d(r.get("taxable value"))
            cess = _d(r.get("cess amount"))
            pos = pos_code(parse_text(r.get("place of supply"))) or own_state
            if sheet in ("b2b,sez,de", "b2b", "cdnr"):
                gstin = parse_text(r.get("gstin/uin of recipient")).upper()
                note = sheet == "cdnr"
                no = parse_text(r.get("note number" if note else "invoice number"))
                dt = parse_date(r.get("note date" if note else "invoice date"))
                inv_type = parse_text(r.get("invoice type") or r.get("note supply type")).lower()
                supply = ("SEZ with payment" if "sez" in inv_type and "with payment" in inv_type else
                          "SEZ without payment" if "sez" in inv_type else
                          "Deemed export" if "deemed" in inv_type else "Regular")
                doc = ("Credit Note" if parse_text(r.get("note type")).upper().startswith("C") else "Debit Note") \
                    if note else "Invoice"
                igst, cgst, sgst = _tax(taxable, rate, pos, own_state)
                if supply.startswith("SEZ"):  # SEZ supplies are inter-state
                    igst, cgst, sgst = (taxable * rate / 100).quantize(Decimal("0.01")), ZERO, ZERO
                key = (gstin, no, doc)
                value = _d(r.get("note value" if note else "invoice value")) or None
                prev = docs.get(key)
                if prev is None:
                    docs[key] = [gstin, parse_text(r.get("receiver name")), no, dt, doc, taxable, igst, cgst, sgst,
                                 cess, value, pos, "Y" if parse_text(r.get("reverse charge")).upper() == "Y" else "N",
                                 supply]
                else:  # one row per rate of the same document
                    for k, v in ((5, taxable), (6, igst), (7, cgst), (8, sgst), (9, cess)):
                        prev[k] += v
            elif sheet in ("b2cl", "exp", "cdnur"):
                export = sheet == "exp" or "exp" in parse_text(r.get("ur type")).lower()
                note = sheet == "cdnur"
                no = parse_text(r.get("note number" if note else "invoice number"))
                dt = parse_date(r.get("note date" if note else "invoice date"))
                with_pay = "wpay" in parse_text(r.get("export type") or r.get("ur type")).lower()
                if export:
                    igst = (taxable * rate / 100).quantize(Decimal("0.01")) if with_pay else ZERO
                    cgst = sgst = ZERO
                    pos, supply = "96", "Export with payment" if with_pay else "Export (LUT)"
                else:
                    igst, cgst, sgst = _tax(taxable, rate, pos, own_state)
                    supply = "Regular"
                doc = ("Credit Note" if parse_text(r.get("note type")).upper().startswith("C") else "Debit Note") \
                    if note else "Invoice"
                key = ("", no, doc)
                value = _d(r.get("note value" if note else "invoice value")) or None
                prev = docs.get(key)
                if prev is None:
                    docs[key] = ["", "Export customer" if export else "B2C large", no, dt, doc, taxable, igst, cgst,
                                 sgst, cess, value, pos, "N", supply]
                else:
                    for k, v in ((5, taxable), (6, igst), (7, cgst), (8, sgst), (9, cess)):
                        prev[k] += v
            elif sheet == "b2cs":
                igst, cgst, sgst = _tax(taxable, rate, pos, own_state)
                acc = summary[("B2CS", pos, rate)]
                for k, v in enumerate((taxable, igst, cgst, sgst, cess)):
                    acc[k] += v
            elif sheet == "exemp":
                desc = parse_text(r.get("description")).lower()
                b2b = "registered" in desc and "unregistered" not in desc
                inter = "inter" in desc
                pos_x = "" if not inter else "inter"
                for col, supply in (("nil rated supplies", "Nil rated"),
                                    ("exempted (other than nil rated/non gst supply)", "Exempt"),
                                    ("non gst supplies", "Non-GST")):
                    amt = _d(next((v for k, v in r.items() if k.startswith(col.split(" (")[0])), None))
                    if amt:
                        summary[(supply, pos_x, "B2B" if b2b else "B2C")][0] += amt
    for d in docs.values():
        if d[3] is None:
            warnings.append(f"{d[2]}: no date – left out")
            continue
        d[3] = f"{d[3]:%d-%m-%Y}"
        rows.append(_row(*d))
    end = _period_end(period)
    for key, (taxable, igst, cgst, sgst, cess) in sorted(summary.items(), key=lambda x: str(x[0])):
        if key[0] == "B2CS":
            _k, pos, rate = key
            rows.append(_row("", "B2C (summary)", f"B2CS {pos}-{rate.normalize()}%", end, "Invoice", taxable, igst,
                             cgst, sgst, cess, None, pos, "N", "Regular"))
        else:
            supply, inter, seg = key
            rows.append(_row("", f"{supply} ({seg})", f"{supply.upper()} {seg} {inter or 'intra'}", end, "Invoice",
                             taxable, pos="99" if inter else own_state, supply=supply))
    return rows, warnings


_PORTAL_ONLY = re.compile(r"(only\s+in\s+(portal|gstr|2a|2b))|(not\s+in\s+books)|(portal\s+only)|"
                          r"(available\s+in\s+(portal|gstr-?2[ab])\s+only)|(missing\s+in\s+books)", re.I)


def recon_report_rows(tables) -> tuple[list[str], list[list], list[tuple[int, str]]]:
    """(headings, kept rows, ignored (row, reason)) of a TallyPrime GSTR-2A / 2B reconciliation export."""
    best = None
    for t in tables:
        for i, (_n_, cells) in enumerate(t.rows[:15]):
            names = [_n(c) for c in cells]
            if any("gstin" in x for x in names) and any("status" in x or "remark" in x for x in names):
                best = (t, i, cells)
                break
        if best:
            break
    if best is None:
        return [], [], []
    t, i, cells = best
    headings = [str(c or "") for c in cells]
    status_cols = [j for j, c in enumerate(headings) if "status" in c.lower() or "remark" in c.lower()]
    kept, ignored = [], []
    for n, row in t.rows[i + 1:]:
        if not any(c not in (None, "") for c in row):
            continue
        status = " ".join(str(row[j]) for j in status_cols if j < len(row) and row[j] not in (None, ""))
        if _PORTAL_ONLY.search(status):
            ignored.append((n, f"'{status}' – on the portal only, not in the books (not a purchase entry)"))
            continue
        kept.append(list(row) + [None] * (len(headings) - len(row)))
    return headings, kept, ignored


def _itms(doc: dict) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    tx = ig = cg = sg = cs = ZERO
    for it in doc.get("itms", []) or [doc]:
        d = it.get("itm_det", it)
        tx += _d(d.get("txval"))
        ig += _d(d.get("iamt"))
        cg += _d(d.get("camt"))
        sg += _d(d.get("samt"))
        cs += _d(d.get("csamt"))
    return tx, ig, cg, sg, cs


def gstr1_json_rows(js: dict, own_state: str, period: str) -> list[list]:
    """Sales rows from a GSTR-1 JSON (TallyPrime's export uses the portal layout)."""
    data = js.get("data", js)
    rows, end = [], _period_end(period)

    def date_of(text):
        d = parse_date(text)
        return f"{d:%d-%m-%Y}" if d else end

    for sup in data.get("b2b", []):
        for inv in sup.get("inv", []):
            tx, ig, cg, sg, cs = _itms(inv)
            typ = str(inv.get("inv_typ", "R")).upper()
            supply = {"SEWP": "SEZ with payment", "SEWOP": "SEZ without payment", "DE": "Deemed export"}.get(typ,
                                                                                                         "Regular")
            rows.append(_row(sup.get("ctin", ""), "", inv.get("inum", ""), date_of(inv.get("idt")), "Invoice", tx, ig,
                             cg, sg, cs, inv.get("val"), str(inv.get("pos", "")), inv.get("rchrg", "N"), supply))
    for sup in data.get("cdnr", []):
        for nt in sup.get("nt", []):
            tx, ig, cg, sg, cs = _itms(nt)
            doc = "Credit Note" if str(nt.get("ntty", "C")).upper() == "C" else "Debit Note"
            rows.append(_row(sup.get("ctin", ""), "", nt.get("nt_num", ""), date_of(nt.get("nt_dt")), doc, tx, ig, cg,
                             sg, cs, nt.get("val"), str(nt.get("pos", "")), nt.get("rchrg", "N")))
    for grp in data.get("b2cl", []):
        for inv in grp.get("inv", []):
            tx, ig, cg, sg, cs = _itms(inv)
            rows.append(_row("", "B2C large", inv.get("inum", ""), date_of(inv.get("idt")), "Invoice", tx, ig, cg, sg,
                             cs, inv.get("val"), str(grp.get("pos", ""))))
    for grp in data.get("exp", []):
        with_pay = str(grp.get("exp_typ", "")).upper() == "WPAY"
        for inv in grp.get("inv", []):
            tx, ig, cg, sg, cs = _itms(inv)
            rows.append(_row("", "Export customer", inv.get("inum", ""), date_of(inv.get("idt")), "Invoice", tx, ig,
                             ZERO, ZERO, cs, inv.get("val"), "96", "N",
                             "Export with payment" if with_pay else "Export (LUT)"))
    for nt in data.get("cdnur", []):
        tx, ig, cg, sg, cs = _itms(nt)
        export = str(nt.get("typ", "")).upper().startswith("EXP")
        doc = "Credit Note" if str(nt.get("ntty", "C")).upper() == "C" else "Debit Note"
        rows.append(_row("", "Unregistered", nt.get("nt_num", ""), date_of(nt.get("nt_dt")), doc, tx, ig, cg, sg, cs,
                         nt.get("val"), "96" if export else str(nt.get("pos", "")), "N",
                         "Export (LUT)" if export else "Regular"))
    for d in data.get("b2cs", []):
        tx, ig, cg, sg, cs = _itms(d)
        pos = str(d.get("pos", own_state))
        rows.append(_row("", "B2C (summary)", f"B2CS {pos}-{d.get('rt', '')}%", end, "Invoice", tx, ig, cg, sg, cs,
                         None, pos))
    nil = data.get("nil", {})
    for d in (nil.get("inv", []) if isinstance(nil, dict) else nil):
        sply = str(d.get("sply_ty", ""))
        for key, supply in (("nil_amt", "Nil rated"), ("expt_amt", "Exempt"), ("ngsup_amt", "Non-GST")):
            amt = _d(d.get(key))
            if amt:
                rows.append(_row("", f"{supply} ({sply})", f"{supply.upper()} {sply}", end, "Invoice", amt,
                                 pos="99" if sply.startswith("INTR") and not sply.startswith("INTRA") else own_state,
                                 supply=supply))
    return rows
