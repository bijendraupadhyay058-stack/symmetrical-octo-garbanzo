"""Export / SEZ invoices vs shipping bills, LUT details, and the refund (RFD-01) working (see outward/exports.py)."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.models import DocType, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import AppSetting, Client, ShippingBillRow, SourceFile
from ..importers.parsing import parse_date, parse_period
from ..importers.pipeline import sha256_of
from ..importers.readers import UnsupportedFileError, read_csv, read_excel
from ..outward.exports import ExportLine, RefundInputs, RefundResult, ShippingBill, check_exports, compute_refund, \
    is_export
from .common import ServiceError, audit

SB_COLS = {"sb_no": ("shipping bill no", "sb no", "sb number", "shipping bill number", "sbno"),
           "sb_date": ("shipping bill date", "sb date", "sbdate"),
           "port": ("port code", "port", "port of loading"),
           "invoice_no": ("invoice no", "invoice number", "inv no"),
           "igst": ("igst amount", "igst paid", "igst", "integrated tax"),
           "value": ("fob value", "invoice value", "value", "fob")}


def _norm(v) -> str:
    return " ".join(str(v or "").lower().replace(".", " ").replace("_", " ").replace("(", " ").replace(")", " ").split())


class ExportService:
    def __init__(self, db: Database):
        self.db = db

    # --------------------------------------------------------- shipping bills
    def import_shipping_bills(self, client_id: int, path: str | Path, user: str | None = None) -> tuple[int, list[str]]:
        from ..core.money import parse_amount

        path = Path(path)
        tables = [read_csv(path, path.name)] if path.suffix.lower() == ".csv" else read_excel(path)
        rows, problems = [], []
        for t in tables:
            cols = None
            for n, vals in t.rows:
                if cols is None:
                    names = [_norm(v) for v in vals]
                    found = {k: next((names.index(o) for o in opts if o in names), None) for k, opts in SB_COLS.items()}
                    if found["sb_no"] is not None and found["sb_date"] is not None and found["invoice_no"] is not None:
                        cols = found
                    continue

                def cell(k, vals=vals):
                    i = cols[k]
                    return vals[i] if i is not None and i < len(vals) else None

                if not any(v not in (None, "") for v in vals):
                    continue
                sb = str(cell("sb_no") or "").strip()
                if sb.endswith(".0"):
                    sb = sb[:-2]
                try:
                    d = parse_date(cell("sb_date"))
                    igst = parse_amount(cell("igst")) or ZERO
                    value = parse_amount(cell("value")) if cell("value") not in (None, "") else None
                except ValueError as exc:
                    problems.append(f"{t.name}!{n}: {exc}")
                    continue
                if not sb or d is None or not str(cell("invoice_no") or "").strip():
                    problems.append(f"{t.name}!{n}: shipping bill number, date or invoice number missing")
                    continue
                rows.append((sb, d, str(cell("port") or "").strip()[:10], str(cell("invoice_no")).strip(), igst, value))
        if not rows:
            raise UnsupportedFileError(f"{path.name}: no shipping bills found – it needs columns for the shipping "
                                       "bill number and date and the invoice number")
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            have = set(s.scalars(select(ShippingBillRow.sb_no).where(ShippingBillRow.client_id == client_id)))
            sf = SourceFile(client_id=client_id, source_type="SHIPBILL", file_name=path.name,
                            file_path=str(path.resolve()), sha256=sha256_of(path), layout="shipping_bills",
                            period=None, rows_read=len(rows), documents_imported=0, imported_by=user or "")
            s.add(sf)
            s.flush()
            saved = 0
            for sb, d, port, inv, igst, value in rows:
                if sb in have:
                    problems.append(f"shipping bill {sb} was already imported")
                    continue
                s.add(ShippingBillRow(client_id=client_id, source_file_id=sf.id, sb_no=sb, sb_date=d, port=port,
                                      invoice_no=inv, igst=igst, value=value))
                have.add(sb)
                saved += 1
            sf.documents_imported = saved
            audit(s, "IMPORT", "source_file", sf.id, {"file": path.name, "shipping_bills": saved}, user, client_id)
        return saved, problems

    def bills(self, client_id: int) -> list[ShippingBill]:
        with self.db.session() as s:
            return [ShippingBill(r.sb_no, r.sb_date, r.port, r.invoice_no, r.igst, r.value)
                    for r in s.scalars(select(ShippingBillRow).where(ShippingBillRow.client_id == client_id))]

    # ------------------------------------------------------------------ LUT
    def lut(self, client_id: int, fy: str) -> dict:
        with self.db.session() as s:
            row = s.get(AppSetting, f"lut:{client_id}:{fy}")
            return json.loads(row.value_json) if row else {}

    def save_lut(self, client_id: int, fy: str, arn: str, filed_on: date | None, user: str | None = None) -> None:
        with self.db.session() as s:
            key = f"lut:{client_id}:{fy}"
            row = s.get(AppSetting, key)
            if row is None:
                row = AppSetting(key=key, value_json="{}")
                s.add(row)
            row.value_json = json.dumps({"arn": arn.strip(), "filed_on": filed_on.isoformat() if filed_on else ""})
            audit(s, "SETTING", "app_settings", key, {"arn": arn}, user, client_id)

    # -------------------------------------------------------------- checks
    def _sale_docs(self, client_id: int, months: list[str]):
        from ..outward.gstr1_json import SaleDoc
        from ..db.models import Invoice

        with self.db.session() as s:
            rows = list(s.scalars(select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == "SALES",
                                                        Invoice.period.in_(months))))
        return [SaleDoc(r.id, r.supplier_gstin or "", r.supplier_name, r.doc_type, r.invoice_no, r.invoice_date,
                        r.taxable, r.igst, r.cgst, r.sgst, r.cess, r.invoice_value, r.place_of_supply or "",
                        r.supply_type or "", bool(r.reverse_charge), json.loads(r.hsn_json) if r.hsn_json else [])
                for r in rows]

    def check(self, client_id: int, period_from: str, period_to: str, as_of: date | None = None) -> list[ExportLine]:
        from .reconciliation import months_between

        p1, p2 = parse_period(period_from), parse_period(period_to)
        if not p1 or not p2 or p1 > p2:
            raise ServiceError("Choose a valid month range")
        docs = self._sale_docs(client_id, months_between(p1, p2))
        return check_exports(docs, self.bills(client_id), as_of or date.today())

    # -------------------------------------------------------------- refund
    def refund_defaults(self, client_id: int, kind: str, period_from: str, period_to: str) -> RefundInputs:
        """Figures from the registers for the period; every one can be changed before working out the refund."""
        from .itc import ItcService
        from .portal import PortalService
        from .reconciliation import months_between

        months = months_between(parse_period(period_from), parse_period(period_to))
        docs = self._sale_docs(client_id, months)
        zr = att = ZERO
        for d in docs:
            k = -1 if d.doc_type == "CRN" else 1
            tax = d.igst + d.cgst + d.sgst + d.cess
            export = is_export(d)
            if export and d.igst == 0:
                zr += k * d.taxable
            if export or tax:  # exempt / nil domestic supplies are left out of the adjusted total turnover
                att += k * d.taxable
        with self.db.session() as s:
            books = ItcService(self.db)._docs(s, client_id, Source.BOOKS, months)
        itc = ZERO
        for b in books:
            itc += (-1 if b.doc_type == DocType.CREDIT_NOTE else 1) * (b.igst + b.cgst + b.sgst + b.cess)
        bal = PortalService(self.db).balances(client_id).get("CREDIT")
        i = RefundInputs(kind, months[0], months[-1], turnover_zero_rated=zr, adjusted_total_turnover=att, net_itc=itc,
                         itc_inputs_and_services=itc, credit_ledger_balance=sum(bal[1].values(), ZERO) if bal else None)
        i.notes.append("Net ITC is the purchase register's ITC for the period – remove input services and capital goods"
                       + (" (inverted duty: inputs only)" if kind == "inverted" else " (capital goods are excluded)")
                       + " before filing.")
        if kind == "inverted":
            i.notes.append("Enter the turnover of the inverted rated supply and the tax payable on it.")
        if bal is None:
            i.notes.append("Credit ledger balance not known – import the electronic credit ledger on the GST Portal "
                           "page to apply the limit.")
        return i

    def refund(self, inputs: RefundInputs) -> RefundResult:
        try:
            return compute_refund(inputs)
        except ValueError as exc:
            raise ServiceError(str(exc)) from None

    def export_xlsx(self, client_id: int, lines: list[ExportLine], refund: tuple[RefundInputs, RefundResult] | None,
                    path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        with self.db.session() as s:
            c = s.get(Client, client_id)
            name, gstin = c.name, c.gstin
        wb = Workbook()
        ws = wb.active
        ws.title = "Exports"
        ws.append([f"Exports and SEZ supplies – {name} ({gstin})"])
        ws["A1"].font = Font(bold=True)
        ws.append(["Invoice no", "Date", "Customer", "Type", "Goods / services", "Taxable", "IGST", "Shipping bill",
                   "SB date", "Port", "SB IGST", "Status", "Note"])
        for cc in ws[2]:
            cc.font = Font(bold=True)
        for ln in lines:
            d, sb = ln.doc, ln.sb
            ws.append([d.number, d.date, d.name, ln.kind, "Goods" if ln.goods else "Services", float(d.taxable),
                       float(d.igst), sb.sb_no if sb else "", sb.sb_date if sb else None, sb.port if sb else "",
                       float(sb.igst) if sb else None, ln.status, ln.note])
        if refund is not None:
            inp, res = refund
            r = wb.create_sheet("Refund working")
            r.append([f"Refund of ITC – {res.formula} – {inp.period_from} to {inp.period_to}"])
            r["A1"].font = Font(bold=True)
            for label, v in res.steps:
                r.append([label, float(v)])
            for n in inp.notes:
                r.append([n])
            r.column_dimensions["A"].width = 70
        path = Path(path)
        wb.save(path)
        return path


__all__ = ["ExportService", "Decimal"]
