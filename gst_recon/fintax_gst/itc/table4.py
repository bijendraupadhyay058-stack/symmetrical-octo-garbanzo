"""GSTR-3B Table 4 working and the classification of ITC differences.

For each tax period three views of Table 4 are put side by side:

* **GSTR-2B (auto)** – what the portal's auto-drafted Table 4 would derive from the
  imported GSTR-2B (B2B/CDNR/RCM/ISD/imports; ITC marked unavailable goes to 4(D)(2));
* **Books / review** – the claim register for the period if one exists, otherwise
  the books documents confirmed by reconciliation, less documents with open
  blocked-credit flags;
* **GSTR-3B filed** – the imported return.

Differences are then grouped as accounting differences, timing differences or
possible statutory discrepancies. This is a working paper for the professional,
not a computation of the amounts to be filed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.models import PAIRED_CATEGORIES, PARTIAL_CATEGORIES, Category, DocType, InvoiceRecord, ReconLine
from ..core.money import ZERO
from ..importers.gstr3b import TABLE4, Gstr3bValues
from .review import DocReview
from .rules import Rule, provisional_limit_pct

A_CODES = ("4A1", "4A2", "4A3", "4A4", "4A5")
B_CODES = ("4B1", "4B2")
BLOCKED_REFS = ("S17_5", "RULE_38", "RULE_42", "RULE_43", "CLIENT_BLOCKED")


def doc_values(r: InvoiceRecord) -> Gstr3bValues:
    return Gstr3bValues(r.signed("igst"), r.signed("cgst"), r.signed("sgst"), r.signed("cess"))


def _sum(values) -> Gstr3bValues:
    total = Gstr3bValues()
    for v in values:
        total = total + v
    return total


@dataclass
class Table4Row:
    code: str
    auto_2b: Gstr3bValues
    books: Gstr3bValues
    filed: Gstr3bValues | None

    @property
    def label(self) -> str:
        return TABLE4[self.code]

    @property
    def diff_filed_2b(self) -> Decimal | None:
        return None if self.filed is None else self.filed.total - self.auto_2b.total

    @property
    def diff_filed_books(self) -> Decimal | None:
        return None if self.filed is None else self.filed.total - self.books.total


@dataclass
class Finding:
    kind: str  # statutory | timing | accounting
    severity: str
    text: str
    amount: Decimal = ZERO


@dataclass
class PeriodWorking:
    period: str
    rows: list[Table4Row]
    findings: list[Finding] = field(default_factory=list)
    books_basis: str = ""
    provisional_pct: int | None = None

    def row(self, code: str) -> Table4Row:
        return next(r for r in self.rows if r.code == code)

    def total(self, kind: str) -> Decimal:
        return sum((f.amount for f in self.findings if f.kind == kind), ZERO)


@dataclass
class ClaimAction:
    invoice: InvoiceRecord
    action: str  # CLAIM | REVERSE | RECLAIM
    values: Gstr3bValues  # magnitudes
    rule_ref: str = ""


def build_period(period: str, gstr2b: list[InvoiceRecord], other_itc: list[dict], filed: dict | None,
                 claim_actions: list[ClaimAction], lines: list[ReconLine], reviews: list[DocReview],
                 rules: list[Rule], tolerance: Decimal = Decimal("1.00")) -> PeriodWorking:
    auto = {c: Gstr3bValues() for c in TABLE4}
    for r in gstr2b:
        v = doc_values(r)
        if r.itc_availability == "N":
            auto["4D2"] = auto["4D2"] + v
        elif r.reverse_charge:
            auto["4A3"] = auto["4A3"] + v
        else:
            auto["4A5"] = auto["4A5"] + v
    for o in other_itc:
        sign = -1 if str(o.get("doc_type", "")).upper().endswith("C") else 1
        v = Gstr3bValues(o["igst"] * sign, o["cgst"] * sign, o["sgst"] * sign, o["cess"] * sign)
        if o["section"] in ("IMPG", "IMPGSEZ"):
            auto["4A1"] = auto["4A1"] + v
        elif o.get("itc_availability", "Y") != "N":
            auto["4A4"] = auto["4A4"] + v
        else:
            auto["4D2"] = auto["4D2"] + v

    books = {c: Gstr3bValues() for c in TABLE4}
    books["4A1"], books["4A4"] = auto["4A1"], auto["4A4"]
    if claim_actions:
        basis = "Claim register for the period"
        for ca in claim_actions:
            sign = -1 if ca.invoice.doc_type == DocType.CREDIT_NOTE else 1
            v = Gstr3bValues(ca.values.igst * sign, ca.values.cgst * sign, ca.values.sgst * sign, ca.values.cess * sign)
            code_a = "4A3" if ca.invoice.reverse_charge else "4A5"
            if ca.action == "CLAIM":
                books[code_a] = books[code_a] + v
            elif ca.action == "RECLAIM":
                books[code_a] = books[code_a] + v
                books["4D1"] = books["4D1"] + v
            elif ca.action == "REVERSE":
                code_b = "4B1" if ca.rule_ref.startswith(BLOCKED_REFS) else "4B2"
                books[code_b] = books[code_b] + v
    else:
        basis = "Books documents matched to GSTR-2B (no claim register entries for the period)"
        blocked = {r.record.db_id for r in reviews if r.record.db_id and r.has("blocked")}
        for ln in lines:
            b = ln.books
            if b is None or ln.category not in PAIRED_CATEGORIES or b.db_id in blocked:
                continue
            if ln.gstr2b is not None and ln.gstr2b.period != period:
                continue
            code_a = "4A3" if (b.reverse_charge or ln.gstr2b.reverse_charge) else "4A5"
            books[code_a] = books[code_a] + doc_values(b)
    for target in (auto, books):
        target["4C"] = _sum(target[c] for c in A_CODES) - _sum(target[c] for c in B_CODES)

    filed_rows = filed or None
    rows = [Table4Row(c, auto[c], books[c], (filed_rows.get(c, Gstr3bValues()) if filed_rows else None))
            for c in TABLE4]
    w = PeriodWorking(period, rows, books_basis=basis)

    # ---------------------------------------------------------------- findings
    start = date(int(period[:4]), int(period[5:]), 1)
    r364 = next((r for r in rules if r.code == "R36_4"), None)
    w.provisional_pct = provisional_limit_pct(r364, start) if r364 else None
    if filed_rows:
        claimed = filed_rows.get("4A5", Gstr3bValues()).total
        allowed = auto["4A5"].total * (Decimal(100 + (w.provisional_pct or 0)) / Decimal(100))
        if claimed - allowed > tolerance:
            basis_text = (f"Rule 36(4) limit of {w.provisional_pct}% over GSTR-2A/2B" if w.provisional_pct
                          else "Section 16(2)(aa) – only ITC reflected in GSTR-2B")
            w.findings.append(Finding("statutory", "high", f"4(A)(5) claimed exceeds GSTR-2B by "
                                      f"₹{claimed - auto['4A5'].total:,.2f} ({basis_text})", claimed - allowed))
        inelig = filed_rows.get("4D2", Gstr3bValues()).total
        if auto["4D2"].total - inelig > tolerance:
            w.findings.append(Finding("statutory", "medium", "GSTR-2B ITC marked unavailable is not fully reported "
                                      "in 4(D)(2)", auto["4D2"].total - inelig))
    for rv in reviews:
        if rv.record.source.value != "BOOKS" or not rv.claim.is_claimed:
            continue
        if rv.has("blocked"):
            w.findings.append(Finding("statutory", "high", f"ITC claimed on {rv.record.invoice_no} "
                                      f"({rv.record.supplier_name}) carries an open Section 17(5) flag",
                                      rv.claim.net))
        if any(h.code == "IMS_REJECTED" and h.open for h in rv.hits):
            w.findings.append(Finding("statutory", "high", f"ITC claimed on {rv.record.invoice_no}, rejected in IMS",
                                      rv.claim.net))
    timing = {
        Category.MISSING_IN_2B: "Books ITC not yet in GSTR-2B (deferred until reflected)",
        Category.PREVIOUS_PERIOD: "Earlier-period bookings reflected in this GSTR-2B",
    }
    for cat, text in timing.items():
        amt = sum((ln.side("books", "itc") for ln in lines if ln.category == cat), ZERO)
        if cat == Category.PREVIOUS_PERIOD:
            amt = sum((ln.side("gstr2b", "itc") for ln in lines if ln.category == cat), ZERO)
        if amt:
            w.findings.append(Finding("timing", "info", text, amt))
    pending = [rv for rv in reviews if any(h.code == "IMS_PENDING" and h.open for h in rv.hits)]
    if pending:
        w.findings.append(Finding("timing", "info", f"{len(pending)} document(s) kept pending in IMS",
                                  sum((rv.itc for rv in pending), ZERO)))
    partial = sum((abs(ln.diff("itc")) for ln in lines if ln.category in PARTIAL_CATEGORIES), ZERO)
    if partial:
        w.findings.append(Finding("accounting", "medium", "Value differences on matched documents (absolute)",
                                  partial))
    dup = sum((ln.side("books", "itc") for ln in lines if ln.category == Category.DUPLICATE_IN_BOOKS), ZERO)
    if dup:
        w.findings.append(Finding("accounting", "high", "Duplicate entries in books", dup))
    not_booked = sum((ln.side("gstr2b", "itc") for ln in lines if ln.category == Category.MISSING_IN_BOOKS), ZERO)
    if not_booked:
        w.findings.append(Finding("accounting", "medium", "GSTR-2B documents not recorded in books", not_booked))
    return w
