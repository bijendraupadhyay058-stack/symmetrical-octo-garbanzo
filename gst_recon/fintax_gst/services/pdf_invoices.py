"""Purchase invoices from PDF files into the purchase register, through the usual import preview."""
from __future__ import annotations

import csv
import hashlib
import tempfile
from datetime import date
from pathlib import Path

from sqlalchemy import select

from ..core.models import Source
from ..db.database import Database
from ..db.models import Client, Invoice, SourceFile
from ..importers.pdf_invoice import PdfInvoice, read_pdf_invoice
from ..importers.pipeline import ImportPreview, RowIssue
from .common import ServiceError

HEADERS = ["GSTIN", "Supplier Name", "Invoice No", "Invoice Date", "Taxable Value", "IGST", "CGST", "SGST", "Cess",
           "Invoice Value", "Narration"]


class PdfInvoiceService:
    def __init__(self, db: Database):
        self.db = db

    def read(self, client_id: int, paths: list[str | Path]) -> list[PdfInvoice]:
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            own = client.gstin
            names = {g: n for g, n in s.execute(select(Invoice.supplier_gstin, Invoice.supplier_name).where(
                Invoice.client_id == client_id, Invoice.source_type.in_(("BOOKS", "GSTR2B")),
                Invoice.supplier_name != "")).all()}
        out = []
        for p in paths:
            inv = read_pdf_invoice(p, own)
            if inv.supplier_gstin in names:  # the name the client's books already use
                inv.supplier_name = names[inv.supplier_gstin]
            out.append(inv)
        return out

    def preview(self, client_id: int, invoices: list[PdfInvoice], period: str | None = None) -> ImportPreview:
        from .imports import ImportService

        usable = [i for i in invoices if i.supplier_gstin and i.invoice_no and i.invoice_date and i.taxable]
        if not usable:
            raise ServiceError("No invoice has the GSTIN, number, date and taxable value – complete them first")
        digest = hashlib.sha256()
        for i in usable:
            digest.update(i.file.read_bytes() if i.file.is_file() else str(i.file).encode())
            digest.update(f"{i.supplier_gstin}|{i.invoice_no}|{i.invoice_date}|{i.taxable}|{i.tax}".encode())
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "pdf_invoices.csv"
            with work.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(HEADERS)
                for i in usable:
                    w.writerow([i.supplier_gstin, i.supplier_name, i.invoice_no, f"{i.invoice_date:%d-%m-%Y}",
                                i.taxable, i.igst, i.cgst, i.sgst, i.cess,
                                i.total if i.total is not None else i.taxable + i.tax, f"PDF: {i.file.name}"[:200]])
            pv = ImportService(self.db).preview(client_id, work, Source.BOOKS, period)
        pv.file_name = f"PDF invoices ({len(usable)}) {date.today():%d-%m-%Y}"
        pv.file_path = usable[0].file
        pv.sha256 = digest.hexdigest()
        pv.layout = "pdf_invoices"
        with self.db.session() as s:
            pv.already_imported_file_id = s.scalar(select(SourceFile.id).where(
                SourceFile.client_id == client_id, SourceFile.sha256 == pv.sha256))
        left = [i for i in invoices if i not in usable]
        pv.issues = [RowIssue("", i.file.name, "ignored", "; ".join(i.problems() or i.notes) or "incomplete")
                     for i in left] + pv.issues
        return pv
