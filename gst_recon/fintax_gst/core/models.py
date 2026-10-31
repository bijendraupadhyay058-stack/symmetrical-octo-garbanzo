"""Domain types shared by importers, the engine, persistence and reports."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from .invoice_no import loose_invoice_no, normalize_invoice_no
from .money import ZERO


class Source(str, Enum):
    BOOKS = "BOOKS"
    GSTR2B = "GSTR2B"
    GSTR2A = "GSTR2A"
    IMS = "IMS"  # Invoice Management System export (recipient's actions on supplier documents)
    SALES = "SALES"  # own sales register (outward supplies)
    GSTR1 = "GSTR1"  # GSTR-1 as filed / downloaded (outward supplies)
    GSTR8A = "GSTR8A"  # GSTR-9 Table 8A document details downloaded from the portal (annual)
    EINV = "EINV"  # e-invoices reported to the IRP (IRN report of the e-invoice portal)
    EWB = "EWB"  # e-way bills generated (report of the e-way bill portal)


#: Sources that represent the taxpayer's own books (left side of a reconciliation).
LEFT_SOURCES = frozenset({Source.BOOKS, Source.SALES})
#: Comparison partner of each books source.
PARTNER = {Source.GSTR2B: Source.BOOKS, Source.GSTR2A: Source.BOOKS, Source.GSTR1: Source.SALES,
           Source.GSTR8A: Source.BOOKS, Source.EINV: Source.SALES, Source.EWB: Source.SALES}
#: Outward reference documents generated on a government portal for the sales register's documents.
REFERENCE_SOURCES = frozenset({Source.EINV, Source.EWB})
#: Sources whose party GSTIN is the customer's (the field is still called supplier_gstin).
OUTWARD_SOURCES = frozenset({Source.SALES, Source.GSTR1, Source.EINV, Source.EWB})


def side_labels(comparison: str) -> tuple[str, str]:
    """('Books', 'GSTR-2B') style labels for a run comparison such as 'SALES_VS_GSTR1'."""
    right = comparison.split("_VS_")[-1] if comparison else "GSTR2B"
    left = comparison.split("_VS_")[0] if comparison and "_VS_" in comparison else "BOOKS"
    names = {"BOOKS": "Books", "SALES": "Sales register", "GSTR2B": "GSTR-2B", "GSTR2A": "GSTR-2A",
             "GSTR1": "GSTR-1", "GSTR8A": "Table 8A", "EINV": "e-Invoice (IRP)", "EWB": "e-Way bill"}
    return names.get(left, left), names.get(right, right)


def relabel(text: str, comparison: str) -> str:
    """Rewrite inward wording ('Books', 'GSTR-2B') for the run's actual comparison."""
    left, right = side_labels(comparison)
    if (left, right) == ("Books", "GSTR-2B"):
        return text
    text = text.replace("GSTR-2B", right).replace("Books", left).replace("books", left.lower())
    if left == "Sales register":
        for a, b in (("Input Tax Credit", "Output tax"), ("Purchase", "Sales"), ("purchase", "sales"),
                     ("ITC", "Tax"), ("Supplier", "Customer"), ("supplier", "customer")):
            text = text.replace(a, b)
    return text


class DocType(str, Enum):
    """Document type from the *supplier's* point of view (as in GSTR-2B)."""

    INVOICE = "INV"
    CREDIT_NOTE = "CRN"
    DEBIT_NOTE = "DBN"

    @property
    def label(self) -> str:
        return {"INV": "Invoice", "CRN": "Credit Note", "DBN": "Debit Note"}[self.value]


class Category(str, Enum):
    FULLY_MATCHED = "Fully Matched"
    DATE_DIFFERENCE = "Matched with Date Difference"
    NUMBER_VARIATION = "Matched with Invoice Number Variation"
    TAXABLE_DIFFERENCE = "Matched with Taxable Value Difference"
    IGST_DIFFERENCE = "Matched with IGST Difference"
    CGST_SGST_DIFFERENCE = "Matched with CGST/SGST Difference"
    CESS_DIFFERENCE = "Matched with Cess Difference"
    MULTIPLE_DIFFERENCES = "Matched with Multiple Differences"
    MISSING_IN_2B = "Available in Books but Missing in GSTR-2B"
    MISSING_IN_BOOKS = "Available in GSTR-2B but Missing in Books"
    DUPLICATE_IN_BOOKS = "Duplicate in Books"
    DUPLICATE_IN_2B = "Duplicate in GSTR-2B"
    PREVIOUS_PERIOD = "Previous-Period Invoice"
    CDN_DIFFERENCE = "Credit/Debit Note Difference"
    AMENDED = "Amended Invoice"
    PROBABLE = "Probable Match Requiring Review"
    MANUALLY_MATCHED = "Manually Matched"
    PENDING_CLARIFICATION = "Pending Client or Supplier Clarification"


#: Categories in which a books record and a GSTR-2B record are confirmed as the same document.
PAIRED_CATEGORIES = frozenset({
    Category.FULLY_MATCHED, Category.DATE_DIFFERENCE, Category.NUMBER_VARIATION,
    Category.TAXABLE_DIFFERENCE, Category.IGST_DIFFERENCE, Category.CGST_SGST_DIFFERENCE,
    Category.CESS_DIFFERENCE, Category.MULTIPLE_DIFFERENCES, Category.PREVIOUS_PERIOD,
    Category.CDN_DIFFERENCE, Category.AMENDED, Category.MANUALLY_MATCHED,
})
#: Paired, but with at least one reported difference.
PARTIAL_CATEGORIES = PAIRED_CATEGORIES - {Category.FULLY_MATCHED, Category.MANUALLY_MATCHED}

#: Display order used in summaries and reports.
CATEGORY_ORDER = list(Category)


class ExceptionStatus(str, Enum):
    NO_ACTION = "No Action Required"
    PENDING_REVIEW = "Pending Review"
    SUPPLIER_FOLLOWUP = "Supplier Follow-up Required"
    CLIENT_CLARIFICATION = "Client Clarification Required"
    BOOKS_CORRECTION = "Correction Required in Books"
    SUPPLIER_CORRECTION = "Supplier Correction Required"
    TIMING_DIFFERENCE = "Timing Difference"
    RESOLVED = "Resolved"
    CLOSED = "Closed After Review"


CLOSED_STATUSES = frozenset({ExceptionStatus.NO_ACTION, ExceptionStatus.RESOLVED, ExceptionStatus.CLOSED})


class Flag(str, Enum):
    """Machine-readable reasons attached to a reconciliation line."""

    NUMBER_VARIATION = "INVOICE_NO_VARIATION"
    DATE_DIFF = "DATE_DIFFERENCE"
    TAXABLE_DIFF = "TAXABLE_DIFFERENCE"
    IGST_DIFF = "IGST_DIFFERENCE"
    CGST_DIFF = "CGST_DIFFERENCE"
    SGST_DIFF = "SGST_DIFFERENCE"
    CESS_DIFF = "CESS_DIFFERENCE"
    ROUNDING = "ROUNDING_WITHIN_TOLERANCE"
    TAX_HEAD_SWAP = "IGST_VS_CGST_SGST"
    AMENDMENT = "AMENDMENT"
    PRIOR_PERIOD = "PRIOR_PERIOD_BOOKS"
    DATED_BEFORE_PERIOD = "DATED_BEFORE_PERIOD"
    GSTIN_MISMATCH = "GSTIN_MISMATCH"
    DATE_BEYOND_TOLERANCE = "DATE_BEYOND_TOLERANCE"
    FUZZY = "FUZZY_INVOICE_NO"
    AMBIGUOUS = "AMBIGUOUS_CANDIDATES"
    COUNTERPART_DUPLICATED = "COUNTERPART_DUPLICATED"
    ITC_NOT_AVAILABLE = "ITC_NOT_AVAILABLE_IN_2B"
    REVERSE_CHARGE = "REVERSE_CHARGE"


TAX_FIELDS = ("igst", "cgst", "sgst", "cess")
AMOUNT_FIELDS = ("taxable",) + TAX_FIELDS


def fy_of(d: date) -> str:
    """Indian financial year label, e.g. 2025-04-01 -> '2025-26'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


@dataclass
class InvoiceRecord:
    """One document as it appears in a single source.

    Amounts are stored as non-negative magnitudes; the sign is implied by
    ``doc_type`` (credit notes reduce ITC). ``signed()`` applies it.
    """

    uid: str
    source: Source
    supplier_gstin: str
    doc_type: DocType
    invoice_no: str
    invoice_date: date
    taxable: Decimal = ZERO
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO
    period: str = ""  # books: booking month; GSTR-2B: return period (YYYY-MM)
    supplier_name: str = ""
    invoice_value: Decimal | None = None
    rate: Decimal | None = None
    place_of_supply: str = ""
    reverse_charge: bool = False
    itc_availability: str = ""
    itc_reason: str = ""
    is_amendment: bool = False
    original_invoice_no: str = ""
    original_invoice_date: date | None = None
    supplier_period: str = ""
    description: str = ""  # narration / expense head / item description (used by ITC rules)
    supply_type: str = ""  # e.g. Regular, SEZ with payment, Export – outward summaries use it
    ims_action: str = ""  # IMS only: A accepted, R rejected, P pending, N no action (deemed accepted)
    #: HSN lines of the document (hsn, uqc, qty, taxable, igst, cgst, sgst, cess), kept through rate/HSN merges
    hsn_lines: list[dict] = field(default_factory=list)
    irn: str = ""  # e-invoice only: Invoice Reference Number
    ref_no: str = ""  # e-invoice acknowledgement number / e-way bill number
    ref_status: str = ""  # e-invoice / e-way bill: ACTIVE or CANCELLED
    source_file: str = ""
    source_rows: str = ""
    db_id: int | None = None
    is_prior_period: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def invoice_no_norm(self) -> str:
        return normalize_invoice_no(self.invoice_no)

    @property
    def invoice_no_loose(self) -> str:
        return loose_invoice_no(self.invoice_no)

    @property
    def sign(self) -> int:
        return -1 if self.doc_type == DocType.CREDIT_NOTE else 1

    @property
    def total_tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def signed(self, name: str) -> Decimal:
        value = self.total_tax if name == "itc" else getattr(self, name)
        return value * self.sign

    @property
    def fy(self) -> str:
        return fy_of(self.invoice_date)

    @property
    def reference(self) -> str:
        where = self.source_file or self.source.value
        return f"{where}:{self.source_rows}" if self.source_rows else where

    def sort_key(self) -> tuple:
        return (
            self.supplier_gstin, self.doc_type.value, self.invoice_no_norm, self.invoice_date,
            self.taxable, self.igst, self.cgst, self.sgst, self.cess, self.uid,
        )

    def identity_hash(self) -> str:
        """Content identity used to detect the same document being imported twice.

        GSTR-2A/2B records include the return period: the same invoice reported
        in two periods is two separate portal records (and is then flagged as a
        duplicate during reconciliation), not a repeated import."""
        parts = [self.period if self.source not in LEFT_SOURCES else "", self.ims_action,
            self.source.value, self.supplier_gstin, self.doc_type.value, self.invoice_no_norm,
            self.invoice_date.isoformat(), *(str(getattr(self, f).normalize()) for f in AMOUNT_FIELDS),
            "A" if self.is_amendment else "O",
        ]
        if self.source in REFERENCE_SOURCES:  # a cancellation re-imported later is a new record
            parts += [self.irn, self.ref_no, self.ref_status]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


@dataclass
class ReconSettings:
    amount_tolerance: Decimal = Decimal("1.00")  # per component, in rupees
    date_tolerance_days: int = 7
    fuzzy_threshold: int = 85  # 0-100 invoice-number similarity needed for a suggestion
    fuzzy_min_gap: int = 5  # best candidate must beat the runner-up by this many points
    large_difference_threshold: Decimal = Decimal("10000")
    enable_loose_number_match: bool = True
    enable_fuzzy: bool = True
    enable_gstin_mismatch_check: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in data.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "ReconSettings":
        base = cls()
        kwargs = {}
        for key, default in asdict(base).items():
            if key in data:
                value = data[key]
                kwargs[key] = Decimal(str(value)) if isinstance(default, Decimal) else type(default)(value)
        return cls(**kwargs)


@dataclass
class ReconLine:
    line_no: int
    category: Category
    books: InvoiceRecord | None = None
    gstr2b: InvoiceRecord | None = None
    match_level: int | None = None  # 1 perfect .. 5 probable
    confidence: int | None = None
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # uids of suggested counterparts
    date_diff_days: int | None = None
    status: ExceptionStatus = ExceptionStatus.PENDING_REVIEW
    remarks: str = ""
    assigned_to: str = ""
    action_date: date | None = None
    db_id: int | None = None
    version: int = 0  # stored line version when loaded (0 = not loaded from the database)

    @property
    def is_paired(self) -> bool:
        return self.category in PAIRED_CATEGORIES and self.books is not None and self.gstr2b is not None

    @property
    def primary(self) -> InvoiceRecord:
        return self.books or self.gstr2b  # type: ignore[return-value]

    @property
    def supplier_gstin(self) -> str:
        return self.primary.supplier_gstin

    @property
    def supplier_name(self) -> str:
        return (self.books and self.books.supplier_name) or (self.gstr2b and self.gstr2b.supplier_name) or ""

    @property
    def doc_type(self) -> DocType:
        return self.primary.doc_type

    def side(self, source: str, name: str) -> Decimal:
        record = self.books if source == "books" else self.gstr2b
        return record.signed(name) if record else ZERO

    def diff(self, name: str) -> Decimal:
        """Books minus GSTR-2B, signed. Only meaningful for two-sided lines."""
        return self.side("books", name) - self.side("gstr2b", name)
