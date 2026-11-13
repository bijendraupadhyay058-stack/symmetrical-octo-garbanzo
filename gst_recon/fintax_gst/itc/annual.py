"""GSTR-9 Table 8 (ITC) working for a financial year.

* **8A** – ITC as per GSTR-2B for documents dated in the financial year (B2B, B2BA,
  CDNR, CDNRA; excluding reverse charge, ISD and imports and ITC marked
  unavailable). When the portal's *Table 8A document details* have been imported
  they are the basis (the portal is authoritative) and the figure computed from the
  imported GSTR-2B periods (April up to a configurable cut-off) is kept alongside for
  comparison, with the documents found on only one side.
* **8B** – ITC availed in GSTR-3B Table 4(A)(5) of the year's periods (stand-in for
  Table 6(B) + 6(H)).
* **8C** – ITC on the year's documents availed in the next year's periods up to the
  cut-off, from the claim register.
* **8D** – 8A − (8B + 8C): positive means ITC in GSTR-2B not availed (lapsing
  indicator); negative means more availed than reflected (verify).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..core.models import InvoiceRecord, fy_of
from ..core.money import ZERO
from ..importers.gstr3b import Gstr3bValues
from .table4 import ClaimAction, doc_values


def fy_months(fy: str) -> list[str]:
    start = int(fy[:4])
    return [f"{start}-{m:02d}" for m in range(4, 13)] + [f"{start + 1}-{m:02d}" for m in range(1, 4)]


def default_cutoff(fy: str) -> str:
    return f"{int(fy[:4]) + 1}-11"


@dataclass
class MonthLine:
    month: str
    books_itc: Decimal = ZERO
    gstr2b_itc: Decimal = ZERO
    filed_4a5: Decimal | None = None
    filed_4b: Decimal | None = None
    filed_4c: Decimal | None = None
    claimed_register: Decimal = ZERO


@dataclass
class Table8:
    fy: str
    cutoff: str
    a: Gstr3bValues
    b: Gstr3bValues
    c: Gstr3bValues
    portal_8a: Decimal | None = None
    months: list[MonthLine] = field(default_factory=list)
    basis: str = "computed"  # "portal" when the Table 8A document details are the basis of 8A
    a_computed: Gstr3bValues | None = None  # 8A computed from GSTR-2B (when the portal basis is used)
    portal_not_in_2b: list[InvoiceRecord] = field(default_factory=list)
    gstr2b_not_in_portal: list[InvoiceRecord] = field(default_factory=list)
    docs_8a_not_in_books: list[InvoiceRecord] = field(default_factory=list)
    books_not_in_8a: list[InvoiceRecord] = field(default_factory=list)
    b_periods_missing: list[str] = field(default_factory=list)

    @property
    def d(self) -> Gstr3bValues:
        return self.a - (self.b + self.c)

    def basis_notes(self) -> list[str]:
        """How 8A was arrived at and how it compares with the other figures available."""
        notes = []
        if self.basis == "portal":
            notes.append(f"8A is taken from the portal's Table 8A document details imported for FY {self.fy}.")
            if self.a_computed is not None:
                notes.append(f"8A computed from the imported GSTR-2B (up to {self.cutoff}): "
                             f"₹{self.a_computed.total:,.2f}; difference from the portal ₹"
                             f"{self.a.total - self.a_computed.total:,.2f} – {len(self.portal_not_in_2b)} "
                             f"document(s) only in 8A, {len(self.gstr2b_not_in_portal)} only in the imported "
                             "GSTR-2B.")
        else:
            notes.append(f"8A is computed from the GSTR-2B periods imported up to {self.cutoff}; import the "
                         "portal's Table 8A document details to use the authoritative figure.")
        if self.portal_8a is not None:
            notes.append(f"Portal Table 8A entered: ₹{self.portal_8a:,.2f}; 8A used here: ₹{self.a.total:,.2f}; "
                         f"difference ₹{self.a.total - self.portal_8a:,.2f}.")
        return notes


def _key(r: InvoiceRecord):
    return (r.supplier_gstin, r.doc_type, r.invoice_no_norm)


def gstr9_table8(fy: str, gstr2b: list[InvoiceRecord], books: list[InvoiceRecord],
                 filed: dict[str, dict[str, Gstr3bValues]], claims: list[tuple[str, ClaimAction]],
                 cutoff: str | None = None, portal_8a: Decimal | None = None,
                 portal_docs: list[InvoiceRecord] | None = None) -> Table8:
    cutoff = cutoff or default_cutoff(fy)
    months = fy_months(fy)
    computed = [r for r in gstr2b if fy_of(r.invoice_date) == fy and months[0] <= r.period <= cutoff
                and not r.reverse_charge and r.itc_availability != "N"]
    portal = [r for r in portal_docs or [] if fy_of(r.invoice_date) == fy and not r.reverse_charge
              and r.itc_availability != "N"]
    in_8a = portal if portal_docs else computed
    a = Gstr3bValues()
    for r in in_8a:
        a = a + doc_values(r)
    b = Gstr3bValues()
    missing = []
    for m in months:
        t = filed.get(m)
        if t is None:
            missing.append(m)
            continue
        b = b + t.get("4A5", Gstr3bValues())
    c = Gstr3bValues()
    for period, ca in claims:
        if months[-1] < period <= cutoff and fy_of(ca.invoice.invoice_date) == fy and ca.action in ("CLAIM", "RECLAIM"):
            sign = -1 if ca.invoice.doc_type.value == "CRN" else 1
            c = c + Gstr3bValues(ca.values.igst * sign, ca.values.cgst * sign, ca.values.sgst * sign,
                                 ca.values.cess * sign)
    books_fy = [r for r in books if fy_of(r.invoice_date) == fy]
    bkeys = {_key(r) for r in books_fy}
    akeys = {_key(r) for r in in_8a}
    t = Table8(fy, cutoff, a, b, c, portal_8a, b_periods_missing=missing,
               docs_8a_not_in_books=[r for r in in_8a if _key(r) not in bkeys],
               books_not_in_8a=[r for r in books_fy if _key(r) not in akeys])
    if portal_docs:
        t.basis = "portal"
        t.a_computed = Gstr3bValues()
        for r in computed:
            t.a_computed = t.a_computed + doc_values(r)
        ckeys = {_key(r) for r in computed}
        t.portal_not_in_2b = [r for r in portal if _key(r) not in ckeys]
        t.gstr2b_not_in_portal = [r for r in computed if _key(r) not in akeys]
    lines = {m: MonthLine(m) for m in months}
    for r in books:
        if r.period in lines:
            lines[r.period].books_itc += r.signed("itc")
    for r in gstr2b:
        if r.period in lines:
            lines[r.period].gstr2b_itc += r.signed("itc")
    for m, ln in lines.items():
        f = filed.get(m)
        if f:
            ln.filed_4a5 = f.get("4A5", Gstr3bValues()).total
            ln.filed_4b = (f.get("4B1", Gstr3bValues()) + f.get("4B2", Gstr3bValues())).total
            ln.filed_4c = f.get("4C", Gstr3bValues()).total
    for period, ca in claims:
        if period in lines and ca.action in ("CLAIM", "RECLAIM"):
            sign = -1 if ca.invoice.doc_type.value == "CRN" else 1
            lines[period].claimed_register += ca.values.total * sign
    t.months = [lines[m] for m in months]
    return t
