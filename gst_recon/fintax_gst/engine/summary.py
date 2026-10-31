"""Summaries computed strictly from reconciliation lines.

Each record is counted on its own side exactly once, so matched pairs are
never double-counted. Prior-period books records that were matched in this
run are reported separately and excluded from current-period books totals.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from ..core.models import (
    AMOUNT_FIELDS, CATEGORY_ORDER, CLOSED_STATUSES, PAIRED_CATEGORIES, PARTIAL_CATEGORIES, Category,
    Flag, InvoiceRecord, ReconLine,
)
from ..core.money import ZERO


@dataclass
class Totals:
    count: int = 0
    taxable: Decimal = ZERO
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO

    @property
    def itc(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def add(self, r: InvoiceRecord) -> None:
        self.count += 1
        for f in AMOUNT_FIELDS:
            setattr(self, f, getattr(self, f) + r.signed(f))


def current_books(line: ReconLine) -> InvoiceRecord | None:
    return line.books if line.books is not None and not line.books.is_prior_period else None


def itc_at_risk(line: ReconLine) -> Decimal:
    """Books ITC not yet supported by a confirmed GSTR-2B document.

    * books-only / duplicate / probable lines: the positive books ITC;
    * paired lines: the excess of books ITC over GSTR-2B ITC;
    * paired lines where GSTR-2B marks ITC unavailable: the full books ITC.
    This is an exposure indicator for review, not a legal conclusion.
    """
    b = current_books(line)
    if b is None:
        return ZERO
    books_itc = b.signed("itc")
    if line.is_paired:
        if Flag.ITC_NOT_AVAILABLE.value in line.flags:
            return max(books_itc, ZERO)
        return max(books_itc - line.gstr2b.signed("itc"), ZERO)
    return max(books_itc, ZERO)


def is_pending(line: ReconLine) -> bool:
    return line.status not in CLOSED_STATUSES


def side_totals(lines: list[ReconLine]) -> tuple[Totals, Totals, Totals]:
    """(current books, GSTR-2B, prior-period books matched in this run)."""
    books, g2b, prior = Totals(), Totals(), Totals()
    for ln in lines:
        if ln.books is not None:
            (prior if ln.books.is_prior_period else books).add(ln.books)
        if ln.gstr2b is not None:
            g2b.add(ln.gstr2b)
    return books, g2b, prior


@dataclass
class CategoryRow:
    category: Category
    lines: int = 0
    books: Totals = field(default_factory=Totals)
    gstr2b: Totals = field(default_factory=Totals)
    itc_at_risk: Decimal = ZERO

    @property
    def itc_difference(self) -> Decimal:
        return self.books.itc - self.gstr2b.itc


def category_summary(lines: list[ReconLine]) -> list[CategoryRow]:
    rows = {c: CategoryRow(c) for c in CATEGORY_ORDER}
    for ln in lines:
        row = rows[ln.category]
        row.lines += 1
        b = current_books(ln)
        if b is not None:
            row.books.add(b)
        if ln.gstr2b is not None:
            row.gstr2b.add(ln.gstr2b)
        row.itc_at_risk += itc_at_risk(ln)
    return [rows[c] for c in CATEGORY_ORDER]


def dashboard(lines: list[ReconLine]) -> dict:
    books, g2b, prior = side_totals(lines)
    by_cat = defaultdict(int)
    for ln in lines:
        by_cat[ln.category] += 1
    missing_2b = Totals()
    missing_books = Totals()
    for ln in lines:
        if ln.category == Category.MISSING_IN_2B and current_books(ln):
            missing_2b.add(ln.books)
        elif ln.category == Category.MISSING_IN_BOOKS:
            missing_books.add(ln.gstr2b)
    total = len(lines)
    paired = sum(1 for ln in lines if ln.category in PAIRED_CATEGORIES)
    return {
        "total_purchase_invoices": books.count,
        "purchase_taxable_value": books.taxable,
        "itc_as_per_books": books.itc,
        "itc_as_per_gstr2b": g2b.itc,
        "fully_matched": by_cat[Category.FULLY_MATCHED],
        "partially_matched": sum(by_cat[c] for c in PARTIAL_CATEGORIES),
        "missing_in_gstr2b": missing_2b.count,
        "missing_in_gstr2b_itc": missing_2b.itc,
        "missing_in_books": missing_books.count,
        "missing_in_books_itc": missing_books.itc,
        "itc_difference": books.itc - g2b.itc,
        "itc_at_risk": sum((itc_at_risk(ln) for ln in lines), ZERO),
        "duplicates": by_cat[Category.DUPLICATE_IN_BOOKS] + by_cat[Category.DUPLICATE_IN_2B],
        "probable_matches": by_cat[Category.PROBABLE],
        "pending_cases": sum(1 for ln in lines if is_pending(ln)),
        "gstr2b_documents": g2b.count,
        "prior_period_books_matched": prior.count,
        "prior_period_itc": prior.itc,
        "match_percentage": (Decimal(paired * 100) / Decimal(total)).quantize(Decimal("0.1")) if total else ZERO,
        "total_lines": total,
    }


DASHBOARD_LABELS = [
    ("total_purchase_invoices", "Total Purchase Invoices (books documents)", "count"),
    ("purchase_taxable_value", "Purchase Taxable Value", "money"),
    ("itc_as_per_books", "Input Tax Credit as per Books", "money"),
    ("itc_as_per_gstr2b", "ITC as per GSTR-2B", "money"),
    ("fully_matched", "Fully Matched Invoices", "count"),
    ("partially_matched", "Partially Matched Invoices", "count"),
    ("missing_in_gstr2b", "Invoices Missing in GSTR-2B", "count"),
    ("missing_in_books", "Invoices Missing in Books", "count"),
    ("itc_difference", "ITC Difference (Books − GSTR-2B)", "money"),
    ("itc_at_risk", "Potential ITC at Risk", "money"),
    ("duplicates", "Duplicate Invoices", "count"),
    ("pending_cases", "Pending Reconciliation Cases", "count"),
]


@dataclass
class SupplierRow:
    gstin: str
    name: str = ""
    books: Totals = field(default_factory=Totals)
    gstr2b: Totals = field(default_factory=Totals)
    missing_in_2b: int = 0
    missing_in_books: int = 0
    duplicates: int = 0
    probable: int = 0
    unresolved: int = 0
    itc_at_risk: Decimal = ZERO

    @property
    def itc_difference(self) -> Decimal:
        return self.books.itc - self.gstr2b.itc


def supplier_summary(lines: list[ReconLine], sort_by: str = "itc_difference") -> list[SupplierRow]:
    rows: dict[str, SupplierRow] = {}

    def row(gstin: str, name: str) -> SupplierRow:
        r = rows.get(gstin)
        if r is None:
            r = rows[gstin] = SupplierRow(gstin)
        if name and not r.name:
            r.name = name
        return r

    for ln in lines:
        b = current_books(ln)
        if b is not None:
            row(b.supplier_gstin, b.supplier_name).books.add(b)
        if ln.gstr2b is not None:
            row(ln.gstr2b.supplier_gstin, ln.gstr2b.supplier_name).gstr2b.add(ln.gstr2b)
        r = row(ln.supplier_gstin, ln.supplier_name)
        if ln.category == Category.MISSING_IN_2B:
            r.missing_in_2b += 1
        elif ln.category == Category.MISSING_IN_BOOKS:
            r.missing_in_books += 1
        elif ln.category in (Category.DUPLICATE_IN_BOOKS, Category.DUPLICATE_IN_2B):
            r.duplicates += 1
        elif ln.category == Category.PROBABLE:
            r.probable += 1
        if is_pending(ln):
            r.unresolved += 1
        r.itc_at_risk += itc_at_risk(ln)
    keys = {
        "itc_difference": lambda r: (-abs(r.itc_difference), r.gstin),
        "taxable": lambda r: (-max(abs(r.books.taxable), abs(r.gstr2b.taxable)), r.gstin),
        "missing": lambda r: (-(r.missing_in_2b + r.missing_in_books), r.gstin),
        "exposure": lambda r: (-r.itc_at_risk, r.gstin),
        "name": lambda r: (r.name.upper(), r.gstin),
    }
    return sorted(rows.values(), key=keys[sort_by])


@dataclass
class MonthRow:
    month: str
    books: Totals = field(default_factory=Totals)
    gstr2b: Totals = field(default_factory=Totals)
    matched_books_itc: Decimal = ZERO
    unmatched_books_itc: Decimal = ZERO

    @property
    def itc_difference(self) -> Decimal:
        return self.books.itc - self.gstr2b.itc


def month_summary(lines: list[ReconLine]) -> list[MonthRow]:
    """Books grouped by booking period; GSTR-2B grouped by return period."""
    rows: dict[str, MonthRow] = {}
    for ln in lines:
        b = current_books(ln)
        if b is not None:
            m = rows.setdefault(b.period, MonthRow(b.period))
            m.books.add(b)
            if ln.category in PAIRED_CATEGORIES:
                m.matched_books_itc += b.signed("itc")
            else:
                m.unmatched_books_itc += b.signed("itc")
        if ln.gstr2b is not None:
            rows.setdefault(ln.gstr2b.period, MonthRow(ln.gstr2b.period)).gstr2b.add(ln.gstr2b)
    return [rows[k] for k in sorted(rows)]


SUGGESTED_ACTIONS = {
    Category.DATE_DIFFERENCE: "Verify invoice date with supplier copy; correct books or ask supplier to amend",
    Category.NUMBER_VARIATION: "Confirm invoice number; align books reference with supplier's GSTR-1",
    Category.TAXABLE_DIFFERENCE: "Compare with invoice copy; correct books or request supplier amendment",
    Category.IGST_DIFFERENCE: "Verify IGST charged; check place of supply",
    Category.CGST_SGST_DIFFERENCE: "Verify CGST/SGST charged; check place of supply",
    Category.CESS_DIFFERENCE: "Verify cess amount with invoice",
    Category.MULTIPLE_DIFFERENCES: "Review invoice copy against GSTR-2B; correct books or contact supplier",
    Category.MISSING_IN_2B: "Follow up with supplier to report invoice in GSTR-1/IFF; defer ITC until reflected",
    Category.MISSING_IN_BOOKS: "Check whether invoice is received and booked; confirm with client",
    Category.DUPLICATE_IN_BOOKS: "Remove duplicate entry from books to avoid double ITC claim",
    Category.DUPLICATE_IN_2B: "Ask supplier to correct duplicate reporting; claim ITC once",
    Category.PREVIOUS_PERIOD: "Timing difference – ITC of earlier booking now reflected; review claim period",
    Category.CDN_DIFFERENCE: "Reconcile credit/debit note values with supplier",
    Category.AMENDED: "Update books reference/values to amended document",
    Category.PROBABLE: "Confirm or reject the suggested match",
    Category.PENDING_CLARIFICATION: "Awaiting clarification",
}
