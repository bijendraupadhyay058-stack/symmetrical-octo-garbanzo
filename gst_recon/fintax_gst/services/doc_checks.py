"""Duplicate invoices and credit / debit note checks of a client's financial year.

**Duplicates** (purchase and sales registers): the same number twice in a month; the same document in two months
(claimed twice); the same number written two ways (``INV-12`` / ``INV/012``); and near-duplicates – the same party,
date and value under a different number. Each finding goes to review; nothing is deleted or changed.

**Credit / debit notes**: each note is linked to its original invoice (the *original invoice number* of the
note). Flags: no original recorded or not found; note dated before its invoice; credit notes adding up to more
than the invoice; notes after the section 34 time limit (30 November after the end of the financial year of the
supply, or the annual return date if earlier – Finance Act 2022); supplier debit notes booked after their own
section 16(4) time limit; and supplier credit notes in GSTR-2B that are not in the books. *ITC to reverse* lists
the tax on supplier credit notes month by month.

Reviewers mark each finding *confirmed*, *not an issue* or *to check*, with a note (table ``review_marks``).
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.invoice_no import loose_invoice_no, normalize_invoice_no
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Invoice, ReviewMark
from ..itc.annual import fy_months
from ..itc.deadlines import itc_deadline
from .common import ServiceError, audit

SOURCES = {"BOOKS": "Purchase register", "SALES": "Sales register"}
DOC = {"INV": "Invoice", "CRN": "Credit note", "DBN": "Debit note"}
KINDS = {"same_number": "Same number twice in a month", "two_months": "Same document in two months",
         "written_differently": "Same number written differently", "near": "Same party, date and value"}
CONFIDENCE = {"same_number": "high", "two_months": "high", "written_differently": "medium", "near": "low"}
DECISIONS = {"pending": "To check", "confirmed": "Confirmed", "not_issue": "Not an issue"}
SEVERITY = {"red": 0, "amber": 1, "info": 2}


def section34_limit(supply_date: date) -> date:
    """Last date to issue / declare a credit note for a supply made on ``supply_date`` (section 34(2), as amended
    by Finance Act 2022): 30 November following the end of the financial year (annual return date if earlier)."""
    fy_start = supply_date.year if supply_date.month >= 4 else supply_date.year - 1
    return date(fy_start + 1, 11, 30) if fy_start >= 2021 else date(fy_start + 1, 9, 30)


@dataclass
class Doc:
    id: int
    source: str
    gstin: str
    name: str
    doc_type: str
    number: str
    norm: str
    date: date
    period: str
    taxable: Decimal
    tax: Decimal
    original_no: str = ""
    original_date: date | None = None

    @property
    def value(self) -> Decimal:
        return self.taxable + self.tax

    def text(self) -> str:
        return f"{DOC.get(self.doc_type, self.doc_type)} {self.number} dt {self.date:%d-%m-%Y} ({self.period}) " \
               f"₹{self.taxable:,.2f} + tax ₹{self.tax:,.2f}"


@dataclass
class Finding:
    area: str  # duplicate / note
    kind: str
    severity: str
    source: str
    party: str
    gstin: str
    title: str
    detail: str
    docs: list[Doc] = field(default_factory=list)
    tax: Decimal = ZERO  # ITC (purchases) or output tax (sales) at stake
    key: str = ""
    decision: str = "pending"
    note: str = ""
    marked_by: str = ""
    confidence: str = ""


@dataclass
class CheckReport:
    client: str
    fy: str
    duplicates: list[Finding] = field(default_factory=list)
    notes: list[Finding] = field(default_factory=list)
    reverse: list[dict] = field(default_factory=list)  # month-wise ITC to reverse on supplier credit notes

    def open(self, area: str) -> list[Finding]:
        return [f for f in (self.duplicates if area == "duplicate" else self.notes) if f.decision == "pending"]


def _key(*parts) -> str:
    text = "|".join(str(p) for p in parts)
    return text if len(text) <= 380 else text[:300] + "#" + hashlib.sha1(text.encode()).hexdigest()


def _doc(r) -> Doc:
    tax = (r.igst or ZERO) + (r.cgst or ZERO) + (r.sgst or ZERO) + (r.cess or ZERO)
    return Doc(r.id, r.source_type, r.supplier_gstin or "", r.supplier_name or "", r.doc_type, r.invoice_no,
               r.invoice_no_norm or normalize_invoice_no(r.invoice_no), r.invoice_date, r.period,
               r.taxable or ZERO, tax, r.original_invoice_no or "", r.original_invoice_date)


class DocCheckService:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- data
    def _docs(self, client_id: int, fy: str) -> tuple[str, list[Doc], list[Doc], list[Doc]]:
        months = fy_months(fy)
        cols = (Invoice.id, Invoice.source_type, Invoice.supplier_gstin, Invoice.supplier_name, Invoice.doc_type,
                Invoice.invoice_no, Invoice.invoice_no_norm, Invoice.invoice_date, Invoice.period, Invoice.taxable,
                Invoice.igst, Invoice.cgst, Invoice.sgst, Invoice.cess, Invoice.original_invoice_no,
                Invoice.original_invoice_date)
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            year = [_doc(r) for r in s.execute(select(*cols).where(
                Invoice.client_id == client_id, Invoice.source_type.in_(list(SOURCES)),
                Invoice.period.in_(months)).order_by(Invoice.period, Invoice.id)).all()]
            parties = sorted({d.gstin for d in year})
            # every period of these parties: a document of an earlier / later year counts for "two months" and
            # is the original of a note
            other = []
            for i in range(0, len(parties), 500):
                other += [_doc(r) for r in s.execute(select(*cols).where(
                    Invoice.client_id == client_id, Invoice.source_type.in_(list(SOURCES)),
                    Invoice.supplier_gstin.in_(parties[i:i + 500]), Invoice.period.not_in(months))).all()]
            b2b = [_doc(r) for r in s.execute(select(*cols).where(
                Invoice.client_id == client_id, Invoice.source_type == "GSTR2B", Invoice.doc_type == "CRN",
                Invoice.period.in_(months))).all()]
            return client.name, year, other, b2b

    def _marks(self, client_id: int) -> dict[tuple[str, str], ReviewMark]:
        with self.db.session() as s:
            return {(m.area, m.key): m for m in s.scalars(select(ReviewMark).where(
                ReviewMark.client_id == client_id))}

    # ---------------------------------------------------------------- checks
    def check(self, client_id: int, fy: str, today: date | None = None) -> CheckReport:
        today = today or date.today()
        return self.db.cached(("doc_checks", client_id, fy, today), lambda: self._check(client_id, fy, today))

    def _check(self, client_id: int, fy: str, today: date) -> CheckReport:
        name, year, other, b2b = self._docs(client_id, fy)
        rep = CheckReport(name, fy)
        rep.duplicates = self._duplicates(year, other)
        rep.notes, rep.reverse = self._notes(year, other, b2b, fy)
        marks = self._marks(client_id)
        for f in rep.duplicates + rep.notes:
            m = marks.get((f.area, f.key))
            if m:
                f.decision, f.note, f.marked_by = m.decision, m.note, m.marked_by
        return rep

    def _duplicates(self, year: list[Doc], other: list[Doc]) -> list[Finding]:
        out: list[Finding] = []
        used: set[int] = set()
        in_year = {d.id for d in year}

        def add(kind: str, docs: list[Doc], detail: str):
            docs = sorted(docs, key=lambda d: (d.period, d.date, d.id))
            if not any(d.id in in_year for d in docs):
                return
            used.update(d.id for d in docs)
            first = docs[0]
            extra = sum((d.tax for d in docs[1:]), ZERO)
            what = "ITC" if first.source == "BOOKS" else "output tax"
            out.append(Finding(
                "duplicate", kind, "red" if CONFIDENCE[kind] == "high" else "amber", first.source,
                first.name or first.gstin, first.gstin,
                f"{KINDS[kind]}: {len(docs)} entries of {DOC.get(first.doc_type, first.doc_type).lower()} "
                f"{first.number}", f"{detail} {what} counted again ₹{extra:,.2f} if it is one document – "
                "remove the extra entry in Tally and re-import (nothing is deleted here).", docs, extra,
                _key("dup", kind, first.source, first.gstin, first.doc_type,
                     *[f"{d.period}:{d.norm}:{d.date:%Y%m%d}:{d.value}" for d in docs]),
                confidence=CONFIDENCE[kind]))

        everything = year + other
        exact: dict[tuple, list[Doc]] = defaultdict(list)
        for d in everything:
            exact[(d.source, d.gstin, d.doc_type, d.norm)].append(d)
        for docs in exact.values():
            if len(docs) < 2:
                continue
            by_period: dict[str, list[Doc]] = defaultdict(list)
            for d in docs:
                by_period[d.period].append(d)
            for ds in by_period.values():
                if len(ds) > 1:
                    add("same_number", ds, f"Entered {len(ds)} times in {ds[0].period}.")
            rest = [d for d in docs if d.id not in used]
            if len({d.period for d in rest}) > 1:
                add("two_months", rest, "Booked in " + ", ".join(sorted({d.period for d in rest})) + ".")
        loose: dict[tuple, list[Doc]] = defaultdict(list)
        for d in everything:
            if d.id not in used:
                loose[(d.source, d.gstin, d.doc_type, loose_invoice_no(d.number))].append(d)
        for docs in loose.values():
            if len({d.norm for d in docs}) > 1:
                add("written_differently", docs, "Numbers " + " / ".join(sorted({d.number for d in docs})) + ".")
        near: dict[tuple, list[Doc]] = defaultdict(list)
        for d in year:
            if d.id not in used and d.value:
                near[(d.source, d.gstin, d.doc_type, d.date, d.value)].append(d)
        for docs in near.values():
            if len(docs) > 1:
                add("near", docs, "Different numbers " + " / ".join(d.number for d in docs) + " with the same "
                    "date and value – may be two genuine bills; check the copies.")
        out.sort(key=lambda f: (SEVERITY[f.severity], -f.tax, f.party))
        return out

    def _notes(self, year: list[Doc], other: list[Doc], b2b: list[Doc], fy: str) -> tuple[list[Finding], list[dict]]:
        out: list[Finding] = []
        invoices: dict[tuple, list[Doc]] = defaultdict(list)
        for d in year + other:
            if d.doc_type == "INV":
                invoices[(d.source, d.gstin, d.norm)].append(d)
        notes = [d for d in year if d.doc_type in ("CRN", "DBN")]
        credited: dict[int, list[Doc]] = defaultdict(list)

        def add(kind, sev, note: Doc, title, detail, docs, tax=ZERO):
            out.append(Finding("note", kind, sev, note.source, note.name or note.gstin, note.gstin, title, detail,
                               docs, tax, _key("note", kind, note.source, note.gstin, note.doc_type, note.norm,
                                               f"{note.date:%Y%m%d}", note.value)))

        for n in notes:
            label = f"{DOC[n.doc_type].lower()} {n.number}"
            inward = n.source == "BOOKS"
            orig = None
            if not n.original_no.strip():
                add("no_original", "amber", n, f"No original invoice recorded on {label}",
                    "Record the original invoice number (Tally: the note's original invoice details) so the time "
                    "limit and amount can be checked.", [n])
            else:
                found = invoices.get((n.source, n.gstin, normalize_invoice_no(n.original_no)), [])
                if not found:
                    add("original_missing", "amber", n, f"Original invoice {n.original_no} of {label} not found",
                        "The invoice is not in the imported data of any year – import that year's register, or check "
                        "the number.", [n])
                else:
                    orig = sorted(found, key=lambda d: d.date)[0]
            supply = orig.date if orig else n.original_date
            if orig and n.date < orig.date:
                add("before_original", "red", n, f"{label.capitalize()} dated before its invoice",
                    f"Invoice {orig.number} is dated {orig.date:%d-%m-%Y}; the note {n.date:%d-%m-%Y}. Check the "
                    "dates or the original invoice number.", [orig, n])
            if orig and n.doc_type == "CRN":
                credited[orig.id].append(n)
            if n.doc_type == "CRN" and supply:
                limit = section34_limit(supply)
                if n.date > limit:
                    if inward:
                        add("late_credit", "amber", n, f"Supplier {label} issued after the section 34 time limit",
                            f"Supply of {supply:%d-%m-%Y}; limit {limit:%d-%m-%Y}. The supplier cannot reduce its tax "
                            "on a late credit note – confirm with the supplier whether your ITC must still be "
                            "reduced (financial / commercial credit note).", [d for d in (orig, n) if d], n.tax)
                    else:
                        add("late_credit", "red", n, f"{label.capitalize()} issued after the section 34 time limit",
                            f"Supply of {supply:%d-%m-%Y}; limit {limit:%d-%m-%Y} (30 November after the year, or "
                            "the annual return date if earlier). Output tax cannot be reduced by this note – treat it "
                            "as a financial credit note.", [d for d in (orig, n) if d], n.tax)
            if n.doc_type == "DBN" and inward:
                limit = itc_deadline(n.date)[0]
                if n.period > f"{limit:%Y-%m}":
                    add("late_debit", "red", n, f"Supplier {label} booked after its section 16(4) time limit",
                        f"ITC on a debit note must be availed by {limit:%d-%m-%Y} (runs from the debit note's own "
                        f"date); booked in {n.period}. ITC ₹{n.tax:,.2f} is not available.", [n], n.tax)
        by_id = {d.id: d for d in year + other}
        for oid, ns in credited.items():
            orig = by_id[oid]
            total = sum((d.taxable for d in ns), ZERO)
            if total > orig.taxable:
                first = sorted(ns, key=lambda d: d.date)[0]
                add("exceeds", "red", first, f"Credit notes exceed invoice {orig.number}",
                    f"Credit notes ₹{total:,.2f} against an invoice of ₹{orig.taxable:,.2f} (taxable value).",
                    [orig] + ns, sum((d.tax for d in ns), ZERO))
        booked = {(d.gstin, d.norm) for d in year + other if d.source == "BOOKS" and d.doc_type == "CRN"}
        months = fy_months(fy)
        reverse = {m: {"month": m, "books": ZERO, "count": 0, "not_booked": ZERO, "nb_count": 0} for m in months}
        for d in year:
            if d.source == "BOOKS" and d.doc_type == "CRN" and d.period in reverse:
                reverse[d.period]["books"] += d.tax
                reverse[d.period]["count"] += 1
        for d in b2b:
            if (d.gstin, d.norm) not in booked:
                add("not_booked", "amber", d, f"Supplier credit note {d.number} in GSTR-2B not in the books",
                    f"Credit note of {d.date:%d-%m-%Y} reported by the supplier in GSTR-2B {d.period}: ITC "
                    f"₹{d.tax:,.2f} should be reduced. Book it in Tally, or mark why not.", [d], d.tax)
                if d.period in reverse:
                    reverse[d.period]["not_booked"] += d.tax
                    reverse[d.period]["nb_count"] += 1
        out.sort(key=lambda f: (SEVERITY[f.severity], f.party, f.title))
        rows = [r | {"total": r["books"] + r["not_booked"]} for r in reverse.values()]
        return out, rows

    # ---------------------------------------------------------------- review
    def mark(self, client_id: int, finding: Finding, decision: str, note: str = "", user: str = "") -> None:
        if decision not in DECISIONS:
            raise ServiceError(f"Unknown decision {decision!r}")
        if decision == "not_issue" and not note.strip():
            raise ServiceError("Give the reason it is not an issue (the note is kept with the working)")
        with self.db.session() as s:
            m = s.scalars(select(ReviewMark).where(ReviewMark.client_id == client_id,
                                                   ReviewMark.area == finding.area,
                                                   ReviewMark.key == finding.key)).first()
            if m is None:
                m = ReviewMark(client_id=client_id, area=finding.area, key=finding.key)
                s.add(m)
            m.decision, m.note, m.marked_by = decision, note.strip(), (user or "")[:80]
            audit(s, "review_mark", finding.area, finding.key[:60], {"title": finding.title, "decision": decision,
                                                                     "note": note}, user=user or None,
                  client_id=client_id)
            s.commit()

    # ---------------------------------------------------------------- export
    def export_xlsx(self, client_id: int, fy: str, path: str | Path, today: date | None = None) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        rep = self.check(client_id, fy, today)
        wb = Workbook()
        bold = Font(bold=True)
        fills = {"red": PatternFill("solid", fgColor="FFCDD2"), "amber": PatternFill("solid", fgColor="FFF3C4")}

        def sheet(ws, title, heads, rows, sev=None):
            ws.title = title
            ws.append([f"{rep.client} – FY {rep.fy} – {title}"])
            ws["A1"].font = Font(bold=True, size=12)
            ws.append(heads)
            for c in ws[2]:
                c.font = bold
            for i, r in enumerate(rows):
                ws.append(r)
                if sev and sev[i] in fills:
                    for c in ws[ws.max_row]:
                        c.fill = fills[sev[i]]
            for col, w in zip("ABCDEFGHIJKL", (12, 30, 18, 40, 60, 14, 12, 14, 30, 60)):
                ws.column_dimensions[col].width = w

        def rows(fs):
            return [[SOURCES.get(f.source, "GSTR-2B"), f.party, f.gstin, f.title, f.detail, float(f.tax),
                     f.confidence or f.severity, DECISIONS[f.decision], f.note,
                     "\n".join(d.text() for d in f.docs)] for f in fs]

        heads = ["Register", "Party", "GSTIN", "Finding", "What to do", "Tax at stake", "Confidence", "Review",
                 "Reviewer's note", "Documents"]
        sheet(wb.active, "Duplicates", heads, rows(rep.duplicates), [f.severity for f in rep.duplicates])
        sheet(wb.create_sheet(), "Credit-debit notes", heads, rows(rep.notes), [f.severity for f in rep.notes])
        sheet(wb.create_sheet(), "ITC to reverse", ["Month", "Credit notes booked", "Tax on them",
                                                    "In 2B not booked", "Tax on them", "Total ITC to reduce"],
              [[r["month"], r["count"], float(r["books"]), r["nb_count"], float(r["not_booked"]), float(r["total"])]
               for r in rep.reverse])
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        return path
