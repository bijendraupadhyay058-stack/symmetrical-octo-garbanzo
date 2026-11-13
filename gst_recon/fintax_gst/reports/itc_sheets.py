"""Workbook sheets for the ITC module: GSTR-3B Table 4 working, IMS review, ITC eligibility review."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..itc.ims import ImsRow
from ..itc.review import BUCKET_LABELS, DocReview
from ..itc.table4 import PeriodWorking

STATUS_DESC = {True: "Claimed", False: "Not claimed"}


@dataclass
class ItcReportData:
    reviews: list[DocReview] = field(default_factory=list)
    buckets: dict[str, Decimal] = field(default_factory=dict)
    table4: list[PeriodWorking] = field(default_factory=list)
    ims_rows: list[ImsRow] = field(default_factory=list)
    ims_notes: list[str] = field(default_factory=list)
    as_of: object = None


def gstr3b_sheet(wb, data: ItcReportData) -> bool:
    """Table 4 working per period. Returns False when no GSTR-3B is imported (caller writes the editable sheet)."""
    from .excel_report import _Sheet, _write_table, section_label

    workings = [w for w in data.table4 if any(r.filed is not None for r in w.rows)]
    if not workings:
        return False
    sh = _Sheet(wb, "GSTR-3B ITC Comparison", [9, 9, 52, 14, 14, 14, 12, 15, 15, 15, 14, 14])
    sh.ws.freeze_panes = "D5"
    sh.banner("GSTR-3B Table 4 working", "GSTR-2B auto-draft vs books/claim register vs GSTR-3B filed. A working "
                                         "paper for review – not the amounts to be filed.", 12)
    rows = []
    for w in data.table4:
        for r in w.rows:
            f = r.filed
            rows.append([w.period, r.code, r.label, r.auto_2b.igst, r.auto_2b.cgst + r.auto_2b.sgst, r.auto_2b.cess,
                         r.auto_2b.total, r.books.total, f.total if f else None, r.diff_filed_2b, r.diff_filed_books,
                         w.books_basis if r.code == "4A5" else ""])
    _write_table(sh, ["Period", "Table", "Description", "2B IGST", "2B CGST+SGST", "2B Cess", "2B Total",
                      "Books / Review", "3B Filed", "3B − 2B", "3B − Books", "Books basis"], rows,
                 ["text", "text", "text", "money", "money", "money", "money", "money", "money", "money", "money",
                  "wrap"], name="Table4Working", totals=False)
    sh.append([])
    sh.append([section_label(sh, "CLASSIFIED DIFFERENCES")])
    frows = [[w.period, f.kind.title(), f.severity.upper(), f.text, f.amount] for w in data.table4 for f in w.findings]
    _write_table(sh, ["Period", "Type", "Severity", "Finding", "Amount"], frows,
                 ["text", "text", "text", "wrap", "money"], name="Table4Findings", totals=False)
    return True


def ims_sheet(wb, data: ItcReportData) -> bool:
    from .excel_report import _Sheet, _write_table

    if not data.ims_rows:
        return False
    sh = _Sheet(wb, "IMS Review", [18, 26, 16, 12, 11, 14, 12, 12, 12, 70])
    sh.ws.freeze_panes = "C5"
    sh.banner("IMS Review", "Compared with books and GSTR-2B. No action is performed on the GST portal by this "
                            "software." + (" " + " ".join(data.ims_notes) if data.ims_notes else ""), 10)
    rows = []
    for r in data.ims_rows:
        rows.append([r.ims.supplier_gstin, r.ims.supplier_name, r.ims.invoice_no, r.ims.doc_type.label,
                     r.action_label, r.ims.invoice_date, "Yes" if r.books else "No", "Yes" if r.gstr2b else "No",
                     (r.worst or "").upper(), " | ".join(t for _s, t in r.observations)])
    _write_table(sh, ["Supplier GSTIN", "Supplier", "Document No", "Type", "IMS Action", "Date", "In Books",
                      "In GSTR-2B", "Severity", "Observations"], rows,
                 ["text", "text", "text", "text", "text", "date", "text", "text", "text", "wrap"], totals=False)
    return True


def itc_review_sheet(wb, data: ItcReportData) -> None:
    from .excel_report import _Sheet, _write_table, section_label

    sh = _Sheet(wb, "ITC Eligibility Review", [8, 18, 26, 16, 12, 13, 9, 14, 12, 9, 22, 46, 9, 40, 60, 12, 30])
    sh.ws.freeze_panes = "D5"
    sh.banner("ITC Eligibility Review", "Flags for professional review with statutory references – not "
                                        "conclusions on eligibility. Dismissed flags remain visible.", 12)
    sh.append([section_label(sh, "ITC SUMMARY")])
    _write_table(sh, ["Measure", "Amount"], [[label, data.buckets.get(k, Decimal(0))] for k, label in BUCKET_LABELS],
                 ["text", "money"], name="ItcBuckets", totals=False)
    sh.append([])
    sh.append([section_label(sh, "DOCUMENT FLAGS")])
    rows = []
    for rv in data.reviews:
        if not rv.hits:
            continue
        for h in rv.hits:
            rows.append([rv.line_no, rv.record.supplier_gstin, rv.record.supplier_name, rv.record.invoice_no,
                         rv.record.invoice_date, rv.itc, "Yes" if rv.in_2b else "No",
                         STATUS_DESC[rv.claim.is_claimed], rv.deadline, rv.days_left, h.code, h.title,
                         h.severity.upper(), h.reference, h.message, h.decision or "Open", h.remarks])
    _write_table(sh, ["Line", "Supplier GSTIN", "Supplier", "Invoice No", "Date", "ITC", "In 2B", "Claim",
                      "16(4) Deadline", "Days Left", "Rule", "Flag", "Severity", "Reference", "Detail", "Decision",
                      "Reviewer Remarks"], rows,
                 ["int", "text", "text", "text", "date", "money", "text", "text", "date", "int", "text", "wrap",
                  "text", "wrap", "wrap", "text", "wrap"], name="ItcFlags", totals=False)
