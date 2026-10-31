"""What goes into a supplier discrepancy letter.

Only open lines on which the *supplier* must act are included: invoices in the books
but not in GSTR-2B, matched documents with differences, and documents the supplier
reported against another GSTIN. Lines marked for correction in the books, client
clarification or timing differences stay internal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..core.models import (
    PARTIAL_CATEGORIES, TAX_FIELDS, Category, ExceptionStatus, Flag, InvoiceRecord, ReconLine,
)
from ..core.money import ZERO
from ..engine.summary import current_books, is_pending

INTERNAL_STATUSES = {ExceptionStatus.BOOKS_CORRECTION, ExceptionStatus.CLIENT_CLARIFICATION,
                     ExceptionStatus.TIMING_DIFFERENCE}
SUPPLIER_STATUSES = {ExceptionStatus.SUPPLIER_FOLLOWUP, ExceptionStatus.SUPPLIER_CORRECTION}
AMOUNT_FLAGS = {Flag.TAXABLE_DIFF.value, Flag.IGST_DIFF.value, Flag.CGST_DIFF.value, Flag.SGST_DIFF.value,
                Flag.CESS_DIFF.value, Flag.TAX_HEAD_SWAP.value}
FLAG_TEXT = {
    Flag.TAXABLE_DIFF.value: "taxable value", Flag.IGST_DIFF.value: "IGST", Flag.CGST_DIFF.value: "CGST",
    Flag.SGST_DIFF.value: "SGST", Flag.CESS_DIFF.value: "cess", Flag.DATE_DIFF.value: "invoice date",
    Flag.NUMBER_VARIATION.value: "invoice number", Flag.TAX_HEAD_SWAP.value: "tax head (IGST vs CGST/SGST)",
}


@dataclass
class LetterItem:
    invoice_no: str
    invoice_date: date | None
    doc_type: str
    books: InvoiceRecord | None
    reported: InvoiceRecord | None
    issue: str
    request: str

    @property
    def tax_books(self) -> Decimal:
        return self.books.total_tax if self.books else ZERO

    @property
    def tax_reported(self) -> Decimal:
        return self.reported.total_tax if self.reported else ZERO

    @property
    def shortfall(self) -> Decimal:
        """Credit not supported by GSTR-2B (signed, so a larger credit note in GSTR-2B also counts)."""
        signed = lambda r: sum((r.signed(f) for f in TAX_FIELDS), ZERO) if r else ZERO  # noqa: E731
        return max(ZERO, signed(self.books) - signed(self.reported))


@dataclass
class SupplierLetter:
    gstin: str
    name: str
    items: list[LetterItem] = field(default_factory=list)

    @property
    def amount(self) -> Decimal:
        return sum((i.shortfall for i in self.items), ZERO)


def _item(ln: ReconLine) -> LetterItem | None:
    b = current_books(ln)
    if b is None or not is_pending(ln) or ln.status in INTERNAL_STATUSES:
        return None
    g = ln.gstr2b
    forced = ln.status in SUPPLIER_STATUSES
    if ln.category == Category.MISSING_IN_2B:
        return LetterItem(b.invoice_no, b.invoice_date, b.doc_type.label, b, None,
                          "Not reflected in our GSTR-2B",
                          "Please report this document in your GSTR-1 / IFF (or confirm if it was reported under "
                          "a different GSTIN or number)")
    if Flag.GSTIN_MISMATCH.value in ln.flags and g is not None:
        return LetterItem(b.invoice_no, b.invoice_date, b.doc_type.label, b, g,
                          f"Reported in GSTR-1 of GSTIN {g.supplier_gstin}, our records show {b.supplier_gstin}",
                          "Please confirm the GSTIN from which the supply was made; if reported in error, amend "
                          "it in the GSTR-1 of the correct registration")
    if (ln.category in PARTIAL_CATEGORIES - {Category.PREVIOUS_PERIOD, Category.AMENDED} or forced) and g is not None:
        fields = [FLAG_TEXT[f] for f in ln.flags if f in FLAG_TEXT]
        if not forced and not set(ln.flags) & AMOUNT_FLAGS:
            return None  # number/date variations alone do not affect the credit
        what = ", ".join(fields) or "details"
        return LetterItem(b.invoice_no, b.invoice_date, b.doc_type.label, b, g, f"Difference in {what}",
                          "Please verify and amend through Table 9A (B2BA) / 9C (CDNRA) of your next GSTR-1, "
                          "or send a copy of the document as issued")
    if forced:
        return LetterItem(b.invoice_no, b.invoice_date, b.doc_type.label, b, g, ln.remarks or "Please confirm",
                          "Please confirm the details reported for this document")
    return None


def build_letters(lines: list[ReconLine], gstins: set[str] | None = None) -> list[SupplierLetter]:
    out: dict[str, SupplierLetter] = {}
    for ln in lines:
        item = _item(ln)
        if item is None:
            continue
        gstin = ln.books.supplier_gstin
        if gstins and gstin not in gstins:
            continue
        letter = out.setdefault(gstin, SupplierLetter(gstin, ln.books.supplier_name))
        letter.name = letter.name or ln.books.supplier_name
        letter.items.append(item)
    for letter in out.values():
        letter.items.sort(key=lambda i: (i.invoice_date or date.min, i.invoice_no))
    return sorted(out.values(), key=lambda x: (-x.amount, x.gstin))
