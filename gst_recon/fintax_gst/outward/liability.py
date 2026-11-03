"""GSTR-1 vs GSTR-3B Table 3.1 (and the sales register) – output tax liability working.

GSTR-1 section totals are mapped to the GSTR-3B Table 3.1 rows:

* 3.1(a) – B2B regular and deemed exports, B2CL, B2CS, credit/debit notes on them;
* 3.1(b) – exports and SEZ supplies (with or without payment) and notes on them;
* 3.1(c) – nil rated and exempted;  3.1(e) – non-GST.

Supplies on which the recipient pays tax under reverse charge are shown separately
(the supplier pays no tax on them). Amendment sections (B2BA, CDNRA, B2CSA, …) carry
the *revised* values of earlier periods; the difference from the original cannot be
derived from one return, so they are listed for manual adjustment, never added.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.models import InvoiceRecord
from ..core.money import ZERO
from ..importers.gstr3b import TABLE31, Gstr3bValues
from ..itc.rules import Rule, intimation_threshold
from ..itc.table4 import Finding, doc_values

AMENDMENT_SECTIONS = {"B2BA", "CDNRA", "B2CLA", "B2CSA", "EXPA", "CDNURA", "ATA", "TXPDA"}
ADVANCE_SECTIONS = {"AT", "TXPD"}  # tax on advances received (+) and adjusted (−), part of 3.1(a)
EXPORT_TEXT = re.compile(r"exp|sez|zero|wpay|wopay|lut", re.IGNORECASE)
COMPARED = ("31A", "31B", "31C", "31E")


def summary_code(section: str, supply: str) -> str | None:
    """GSTR-3B 3.1 row for a GSTR-1 section total (None = not part of the comparison)."""
    section, supply = section.upper(), supply.upper()
    if section in AMENDMENT_SECTIONS:
        return None
    if section in ("B2B", "CDNR"):
        return {"REG": "31A", "SEZ": "31B"}.get(supply)  # RCM: tax payable by the recipient
    if section in ("B2CL", "B2CS") or section in ADVANCE_SECTIONS:
        return "31A"
    if section == "CDNUR":
        return "31B" if supply.startswith("EXP") else "31A"
    if section == "EXP":
        return "31B"
    if section in ("NIL", "EXEMPT"):
        return "31C"
    if section == "NONGST":
        return "31E"
    return None


def sales_code(r: InvoiceRecord) -> str:
    text = f"{r.supply_type} {r.place_of_supply}"
    if EXPORT_TEXT.search(r.supply_type or "") or r.place_of_supply.strip().startswith(("96", "97")):
        return "31B"
    if re.search(r"non.?gst", text, re.IGNORECASE):
        return "31E"
    if r.total_tax == 0 and re.search(r"nil|exempt", text, re.IGNORECASE):
        return "31C"
    return "31A"


@dataclass
class LiabilityRow:
    code: str
    gstr1: Gstr3bValues
    sales: Gstr3bValues
    filed: Gstr3bValues | None

    @property
    def label(self) -> str:
        return TABLE31[self.code]

    @property
    def diff_filed_gstr1(self) -> Decimal | None:
        return None if self.filed is None else self.filed.total - self.gstr1.total

    @property
    def diff_sales_gstr1(self) -> Decimal:
        return self.sales.total - self.gstr1.total


@dataclass
class SegmentRow:
    segment: str
    sales: Gstr3bValues
    gstr1: Gstr3bValues

    @property
    def diff(self) -> Decimal:
        return self.sales.total - self.gstr1.total


@dataclass
class LiabilityWorking:
    period: str
    rows: list[LiabilityRow]
    segments: list[SegmentRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    amendments: list[dict] = field(default_factory=list)
    rcm_outward: Gstr3bValues = field(default_factory=Gstr3bValues)

    def row(self, code: str) -> LiabilityRow:
        return next(r for r in self.rows if r.code == code)


def _vals(d: dict) -> Gstr3bValues:
    return Gstr3bValues(d["igst"], d["cgst"], d["sgst"], d["cess"], d["taxable"])


def _sales_segment(r: InvoiceRecord) -> str:
    if sales_code(r) == "31B":
        return "Exports / SEZ"
    if r.supply_type and re.search(r"nil|exempt|non.?gst", r.supply_type, re.IGNORECASE):
        return "Nil / exempt / non-GST"
    return "B2B (registered)" if r.supplier_gstin else "B2C (unregistered)"


def _gstr1_segment(section: str, supply: str) -> str | None:
    section = section.upper()
    if section in AMENDMENT_SECTIONS:
        return None
    if section in ("B2B", "CDNR"):
        return {"REG": "B2B (registered)", "SEZ": "Exports / SEZ"}.get(supply.upper())
    if section in ("B2CL", "B2CS"):
        return "B2C (unregistered)"
    if section == "CDNUR":
        return "Exports / SEZ" if supply.upper().startswith("EXP") else "B2C (unregistered)"
    if section == "EXP":
        return "Exports / SEZ"
    if section in ADVANCE_SECTIONS:
        return None  # advances have no sales register counterpart
    return "Nil / exempt / non-GST"


def build_liability(period: str, summaries: list[dict], sales: list[InvoiceRecord], filed: dict | None,
                    rules: list[Rule], tolerance: Decimal = Decimal("1.00")) -> LiabilityWorking:
    g1 = {c: Gstr3bValues() for c in TABLE31}
    sl = {c: Gstr3bValues() for c in TABLE31}
    seg_g: dict[str, Gstr3bValues] = {}
    seg_s: dict[str, Gstr3bValues] = {}
    w = LiabilityWorking(period, [])
    for s in summaries:
        code = summary_code(s["section"], s.get("supply", ""))
        seg = _gstr1_segment(s["section"], s.get("supply", ""))
        if s["section"].upper() in AMENDMENT_SECTIONS:
            w.amendments.append(s)
            continue
        if s["section"].upper() in ("B2B", "CDNR") and s.get("supply", "").upper() == "RCM":
            w.rcm_outward = w.rcm_outward + _vals(s)
            continue
        if code:
            g1[code] = g1[code] + _vals(s)
        if seg:
            seg_g[seg] = seg_g.get(seg, Gstr3bValues()) + _vals(s)
    for r in sales:
        if r.reverse_charge:
            continue
        v = doc_values(r)
        v.taxable = r.signed("taxable")
        sl[sales_code(r)] = sl[sales_code(r)] + v
        seg = _sales_segment(r)
        seg_s[seg] = seg_s.get(seg, Gstr3bValues()) + v
    w.rows = [LiabilityRow(c, g1[c], sl[c], (filed.get(c, Gstr3bValues()) if filed else None)) for c in TABLE31
              if c != "31D"]
    w.segments = [SegmentRow(name, seg_s.get(name, Gstr3bValues()), seg_g.get(name, Gstr3bValues()))
                  for name in ("B2B (registered)", "B2C (unregistered)", "Exports / SEZ", "Nil / exempt / non-GST")]

    start = date(int(period[:4]), int(period[5:]), 1)
    g1_tax = g1["31A"].total + g1["31B"].total
    if filed:
        paid = filed.get("31A", Gstr3bValues()).total + filed.get("31B", Gstr3bValues()).total
        gap = g1_tax - paid
        if gap > tolerance:
            w.findings.append(Finding("statutory", "high", f"Tax liability in GSTR-1 exceeds GSTR-3B 3.1(a)+(b) by "
                                      f"₹{gap:,.2f} – possible short payment (interest under Section 50)", gap))
            limit = intimation_threshold(next((r for r in rules if r.code == "R88C"), None), g1_tax, start)
            if limit is not None and gap > limit:
                w.findings.append(Finding("statutory", "high", f"Difference above the Rule 88C limit of ₹{limit:,.2f} "
                                          "– DRC-01B intimation expected", gap))
        elif gap < -tolerance:
            w.findings.append(Finding("statutory", "medium", f"GSTR-3B liability exceeds GSTR-1 by ₹{-gap:,.2f} – "
                                      "invoices missing from GSTR-1, or excess tax paid", -gap))
        for c in ("31B", "31C", "31E"):
            f, g = filed.get(c, Gstr3bValues()), g1[c]
            if abs(f.taxable - g.taxable) > tolerance:
                w.findings.append(Finding("timing" if c != "31B" else "statutory", "medium",
                                          f"{TABLE31[c][:6]} taxable value: GSTR-3B ₹{f.taxable:,.2f} vs GSTR-1 "
                                          f"₹{g.taxable:,.2f}", abs(f.taxable - g.taxable)))
    for seg in w.segments:
        if abs(seg.diff) > tolerance:
            w.findings.append(Finding("accounting", "medium", f"{seg.segment}: sales register tax differs from "
                                      f"GSTR-1 by ₹{seg.diff:,.2f}", seg.diff))
    if w.amendments:
        revised = sum((_vals(a).total for a in w.amendments), ZERO)
        w.findings.append(Finding("timing", "info", f"{len(w.amendments)} amendment total(s) of earlier periods "
                                  f"(revised tax ₹{revised:,.2f}) – adjust the difference from the original manually",
                                  revised))
    if w.rcm_outward.taxable:
        w.findings.append(Finding("info", "info", "Supplies on which the recipient pays tax under reverse charge "
                                  "(not part of the supplier's liability)", w.rcm_outward.taxable))
    return w

