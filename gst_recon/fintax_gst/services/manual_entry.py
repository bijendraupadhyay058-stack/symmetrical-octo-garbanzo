"""Enter purchase / sales documents by hand, and correct or delete single documents.

Entries go through the same validation as an imported row (GSTIN, number, dates, amounts, tax heads) and are
stored like imported documents, under one 'Entered by hand' import per client and register, so reports,
reconciliations and the import log treat them alike. Every addition, change and deletion is written to the
audit log with the values before and after.

A document used in a reconciliation can be corrected (the reconciliation is then out of date – reconcile again)
but not deleted; documents with manual match decisions or ITC claim entries cannot be deleted either.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from ..core.models import Source, period_of
from ..db.database import Database
from ..db.models import Client, Invoice, ItcClaim, MatchDecision, ReconLineRow, SourceFile
from ..importers.validation import RowContext, build_record
from .common import ServiceError, audit

SOURCES = (Source.BOOKS, Source.SALES)
FILE_NAMES = {Source.BOOKS: "Entered by hand – purchases", Source.SALES: "Entered by hand – sales"}
FIELDS = ("supplier_gstin", "supplier_name", "doc_type", "invoice_no", "invoice_date", "period", "taxable_value",
          "igst", "cgst", "sgst", "cess", "invoice_value", "place_of_supply", "reverse_charge", "supply_type",
          "description")


@dataclass
class SaveResult:
    invoice_id: int
    warnings: list[str]
    in_reconciliation: int  # reconciliations that used the document (now out of date)


def values_of(inv: Invoice) -> dict:
    return {"supplier_gstin": inv.supplier_gstin, "supplier_name": inv.supplier_name, "doc_type": inv.doc_type,
            "invoice_no": inv.invoice_no, "invoice_date": inv.invoice_date, "period": inv.period,
            "taxable_value": inv.taxable, "igst": inv.igst, "cgst": inv.cgst, "sgst": inv.sgst, "cess": inv.cess,
            "invoice_value": inv.invoice_value, "place_of_supply": inv.place_of_supply,
            "reverse_charge": inv.reverse_charge, "supply_type": inv.supply_type or "",
            "description": inv.description or ""}


def _plain(v):
    return v.isoformat() if isinstance(v, date) else (str(v) if isinstance(v, Decimal) else v)


class ManualEntryService:
    def __init__(self, db: Database):
        self.db = db

    def _validate(self, source: Source, values: dict):
        """The document as the importer would read it: (record, warnings); errors raise ServiceError."""
        unknown = set(values) - set(FIELDS)
        if unknown:
            raise ServiceError(f"Unknown field(s): {', '.join(sorted(unknown))}")
        row = {k: v for k, v in values.items() if k not in ("period", "reverse_charge")}
        row["reverse_charge"] = "Y" if values.get("reverse_charge") else "N"
        outcome = build_record(row, RowContext(source, "generic", "manual", None), "M")
        if outcome.record is None:
            raise ServiceError("; ".join(outcome.errors) or "The document is not valid")
        rec = outcome.record
        if values.get("period"):
            p = str(values["period"])
            if len(p) != 7 or p[4] != "-":
                raise ServiceError("Period must be YYYY-MM (the month the document is booked in)")
            rec.period = p
        else:
            rec.period = period_of(rec.invoice_date)
        return rec, outcome.warnings

    def _manual_file(self, s, client_id: int, source: Source) -> SourceFile:
        digest = hashlib.sha256(f"manual:{client_id}:{source.value}".encode()).hexdigest()
        sf = s.scalar(select(SourceFile).where(SourceFile.client_id == client_id, SourceFile.sha256 == digest,
                                               SourceFile.source_type == source.value))
        if sf is None:
            sf = SourceFile(client_id=client_id, source_type=source.value, file_name=FILE_NAMES[source],
                            file_path="", sha256=digest, layout="manual", period=None, rows_read=0,
                            documents_imported=0, rows_rejected=0, documents_skipped_existing=0,
                            warnings_json="[]", imported_by="")
            s.add(sf)
            s.flush()
        return sf

    @staticmethod
    def _fields(rec) -> dict:
        return {"supplier_gstin": rec.supplier_gstin, "supplier_name": rec.supplier_name[:200],
                "doc_type": rec.doc_type.value, "invoice_no": rec.invoice_no[:100],
                "invoice_no_norm": rec.invoice_no_norm[:100], "invoice_date": rec.invoice_date, "period": rec.period,
                "taxable": rec.taxable, "igst": rec.igst, "cgst": rec.cgst, "sgst": rec.sgst, "cess": rec.cess,
                "invoice_value": rec.invoice_value, "place_of_supply": rec.place_of_supply[:60],
                "reverse_charge": rec.reverse_charge, "supply_type": rec.supply_type[:40],
                "description": rec.description, "identity_hash": rec.identity_hash()}

    def _same_number(self, s, client_id: int, source: Source, rec, exclude: int | None = None) -> Invoice | None:
        q = select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == source.value,
                                  Invoice.supplier_gstin == rec.supplier_gstin,
                                  Invoice.invoice_no_norm == rec.invoice_no_norm,
                                  Invoice.doc_type == rec.doc_type.value)
        if exclude:
            q = q.where(Invoice.id != exclude)
        return s.scalar(q.limit(1))

    # ------------------------------------------------------------------ add
    def add(self, client_id: int, source: Source | str, values: dict, user: str | None = None) -> SaveResult:
        source = Source(source)
        if source not in SOURCES:
            raise ServiceError("Only purchase and sales documents can be entered by hand")
        rec, warnings = self._validate(source, values)
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            dup = self._same_number(s, client_id, source, rec)
            if dup is not None:
                raise ServiceError(f"Document {dup.invoice_no} of {dup.supplier_gstin or 'this party'} is already in "
                                   f"the data ({dup.period}) – correct that one instead")
            sf = self._manual_file(s, client_id, source)
            inv = Invoice(client_id=client_id, source_file_id=sf.id, source_type=source.value, source_rows="manual",
                          **self._fields(rec))
            s.add(inv)
            sf.documents_imported += 1
            sf.rows_read += 1
            s.flush()
            audit(s, "CREATE", "invoices", inv.id, {"entered_by_hand": {k: _plain(v) for k, v in values.items()}},
                  user, client_id)
            return SaveResult(inv.id, warnings, 0)

    # --------------------------------------------------------------- update
    def update(self, client_id: int, invoice_id: int, values: dict, user: str | None = None) -> SaveResult:
        with self.db.session() as s:
            inv = s.get(Invoice, invoice_id)
            if inv is None or inv.client_id != client_id or Source(inv.source_type) not in SOURCES:
                raise ServiceError("Document not found for this client")
            before = values_of(inv)
            source = Source(inv.source_type)
            rec, warnings = self._validate(source, {**before, **values})
            dup = self._same_number(s, client_id, source, rec, exclude=invoice_id)
            if dup is not None:
                raise ServiceError(f"Another document {dup.invoice_no} of {dup.supplier_gstin or 'this party'} is "
                                   "already in the data")
            for k, v in self._fields(rec).items():
                setattr(inv, k, v)
            used = s.scalar(select(func.count(func.distinct(ReconLineRow.run_id))).where(
                (ReconLineRow.books_invoice_id == invoice_id) | (ReconLineRow.gstr2b_invoice_id == invoice_id))) or 0
            after = values_of(inv)
            audit(s, "UPDATE", "invoices", invoice_id,
                  {"before": {k: _plain(v) for k, v in before.items() if before[k] != after[k]},
                   "after": {k: _plain(v) for k, v in after.items() if before[k] != after[k]}}, user, client_id)
            return SaveResult(invoice_id, warnings, used)

    # --------------------------------------------------------------- delete
    def delete(self, client_id: int, invoice_id: int, user: str | None = None) -> None:
        with self.db.session() as s:
            inv = s.get(Invoice, invoice_id)
            if inv is None or inv.client_id != client_id or Source(inv.source_type) not in SOURCES:
                raise ServiceError("Document not found for this client")
            for model, cond, what in (
                    (ReconLineRow, (ReconLineRow.books_invoice_id == invoice_id) |
                     (ReconLineRow.gstr2b_invoice_id == invoice_id), "a reconciliation (delete it on History first)"),
                    (MatchDecision, (MatchDecision.books_invoice_id == invoice_id) |
                     (MatchDecision.gstr2b_invoice_id == invoice_id), "a manual match decision"),
                    (ItcClaim, ItcClaim.invoice_id == invoice_id, "the ITC claim register")):
                if s.scalar(select(func.count()).select_from(model).where(cond)):
                    raise ServiceError(f"Document {inv.invoice_no} is used in {what} – it cannot be deleted. Correct "
                                       "it instead, or remove its import.")
            sf = s.get(SourceFile, inv.source_file_id)
            if sf is not None:
                sf.documents_imported = max((sf.documents_imported or 0) - 1, 0)
            audit(s, "DELETE", "invoices", invoice_id, {k: _plain(v) for k, v in values_of(inv).items()},
                  user, client_id)
            s.delete(inv)

    # ----------------------------------------------------------------- list
    def documents(self, client_id: int, source: Source | str, period: str | None = None,
                  search: str = "") -> list[Invoice]:
        source = Source(source)
        with self.db.session() as s:
            q = select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == source.value)
            if period:
                q = q.where(Invoice.period == period)
            if search.strip():
                t = f"%{search.strip()}%"
                q = q.where(Invoice.invoice_no.ilike(t) | Invoice.supplier_gstin.ilike(t) |
                            Invoice.supplier_name.ilike(t))
            rows = list(s.scalars(q.order_by(Invoice.invoice_date, Invoice.id).limit(5000)))
            names = {f.id: f.file_name for f in s.scalars(select(SourceFile).where(SourceFile.client_id == client_id))}
            for r in rows:
                r.file_name = names.get(r.source_file_id, "")
            return rows
