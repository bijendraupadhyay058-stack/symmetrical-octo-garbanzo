"""Reverse charge register and ISD distribution (see compliance/rcm.py)."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from ..compliance.rcm import IsdShare, RcmMonth, distribute_isd, rcm_month
from ..core.models import DocType, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, RcmEntry
from ..importers.gstr3b import Gstr3bValues
from ..importers.parsing import parse_period
from ..itc.annual import fy_months
from .common import ServiceError, audit

PAISA = Decimal("0.01")


def _entry_record(e: RcmEntry):
    from ..core.models import InvoiceRecord

    return InvoiceRecord(uid=f"RCM{e.id}", source=Source.BOOKS, supplier_gstin="", doc_type=DocType.INVOICE,
                         invoice_no=e.bill_no or f"RCM-{e.id}", invoice_date=e.entry_date, taxable=e.taxable,
                         igst=e.igst, cgst=e.cgst, sgst=e.sgst, cess=e.cess, period=e.period,
                         supplier_name=e.supplier_name, rate=e.rate, reverse_charge=True, description=e.description)


class RcmService:
    def __init__(self, db: Database):
        self.db = db

    def _client(self, client_id: int) -> Client:
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            s.expunge(c)
            return c

    # ----------------------------------------------------------------- RCM
    def month(self, client_id: int, period: str) -> RcmMonth:
        from .gstr3b import Gstr3bService
        from .itc import ItcService

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        self._client(client_id)
        with self.db.session() as s:
            books = ItcService(self.db)._docs(s, client_id, Source.BOOKS, [p])
            entries = list(s.scalars(select(RcmEntry).where(RcmEntry.client_id == client_id,
                                                            RcmEntry.period == p).order_by(RcmEntry.entry_date)))
        books += [_entry_record(e) for e in entries]
        filed = Gstr3bService(self.db).values(client_id, [p]).get(p)
        return rcm_month(p, books, filed)

    def add_entry(self, client_id: int, entry_date: date, supplier_name: str, taxable, rate, user: str | None = None,
                  bill_no: str = "", description: str = "", supplier_state: str = "",
                  source_file_id: int | None = None, _session=None) -> RcmEntry:
        """A reverse-charge purchase from an unregistered person; the tax is worked out from the rate (IGST when the
        supplier is in another state, else CGST + SGST)."""
        client = self._client(client_id)
        try:
            taxable = Decimal(str(taxable).replace(",", "").strip())
            rate = Decimal(str(rate).replace("%", "").strip())
        except InvalidOperation:
            raise ServiceError("Taxable value and rate must be numbers") from None
        if taxable <= 0:
            raise ServiceError("Enter the taxable value")
        if rate < 0 or rate > 40:
            raise ServiceError(f"GST rate {rate}% is not valid")
        if not supplier_name.strip():
            raise ServiceError("Enter the supplier's name")
        state = (supplier_state or "").strip()[:2]
        tax = (taxable * rate / 100).quantize(PAISA, rounding=ROUND_HALF_UP)
        igst = cgst = sgst = ZERO
        if state and state != client.state_code:
            igst = tax
        else:
            cgst = (taxable * rate / 200).quantize(PAISA, rounding=ROUND_HALF_UP)
            sgst = cgst
        e = RcmEntry(client_id=client_id, source_file_id=source_file_id, period=f"{entry_date:%Y-%m}",
                     entry_date=entry_date, supplier_name=supplier_name.strip()[:200], bill_no=bill_no.strip()[:60],
                     supplier_state=state, description=description.strip()[:300], taxable=taxable, rate=rate,
                     igst=igst, cgst=cgst, sgst=sgst, created_by=(user or "")[:80])
        if _session is not None:
            _session.add(e)
            return e
        with self.db.session() as s:
            s.add(e)
            s.flush()
            audit(s, "RCM_ENTRY", "rcm_entries", e.id, {"supplier": e.supplier_name, "taxable": taxable,
                                                        "rate": rate}, user, client_id)
            s.expunge(e)
        return e

    def delete_entry(self, entry_id: int, user: str | None = None) -> None:
        with self.db.session() as s:
            e = s.get(RcmEntry, entry_id)
            if e is None:
                raise ServiceError(f"RCM entry {entry_id} not found")
            audit(s, "RCM_ENTRY_DELETE", "rcm_entries", e.id, {"supplier": e.supplier_name, "taxable": e.taxable},
                  user, e.client_id)
            s.delete(e)

    def entries(self, client_id: int, period: str) -> list[RcmEntry]:
        with self.db.session() as s:
            return list(s.scalars(select(RcmEntry).where(RcmEntry.client_id == client_id, RcmEntry.period == period)
                                  .order_by(RcmEntry.entry_date, RcmEntry.id)))

    def import_entries(self, client_id: int, path: str | Path, default_rate: str = "18",
                       user: str | None = None) -> tuple[int, list[str]]:
        """A list of RCM expenses (e.g. Tally ledger of rent / legal / freight to unregistered parties): date,
        party, amount and, if given, bill no., rate, state and narration."""
        from ..importers.parsing import parse_date
        from ..importers.pipeline import sha256_of
        from ..importers.readers import UnsupportedFileError, read_csv, read_excel
        from ..db.models import SourceFile

        path = Path(path)
        tables = [read_csv(path, path.name)] if path.suffix.lower() == ".csv" else read_excel(path)
        cols_of = {"date": ("date", "bill date", "voucher date", "invoice date"),
                   "name": ("party", "party name", "supplier", "supplier name", "name", "particulars", "vendor"),
                   "amount": ("taxable value", "amount", "taxable", "value", "debit"),
                   "rate": ("rate", "gst rate", "tax rate", "rate %"), "bill": ("bill no", "invoice no", "voucher no",
                                                                               "ref no", "bill number"),
                   "state": ("state code", "state", "supplier state"),
                   "desc": ("narration", "description", "ledger", "expense", "nature of service", "service")}

        def norm(v):
            return " ".join(str(v or "").lower().replace(".", " ").replace("%", " ").split())

        rows, problems = [], []
        for t in tables:
            cols = None
            for n, vals in t.rows:
                if cols is None:
                    names = [norm(v) for v in vals]
                    found = {k: next((names.index(o) for o in opts if o in names), None) for k, opts in cols_of.items()}
                    if found["date"] is not None and found["name"] is not None and found["amount"] is not None:
                        cols = found
                    continue

                def cell(k, vals=vals):
                    i = cols[k]
                    return vals[i] if i is not None and i < len(vals) else None

                if not any(v not in (None, "") for v in vals):
                    continue
                try:
                    d = parse_date(cell("date"))
                except ValueError:
                    d = None
                if d is None:
                    problems.append(f"{t.name}!{n}: no date – not imported")
                    continue
                state = str(cell("state") or "").strip()
                if state and not state[:2].isdigit():
                    from ..compliance.tax_checks import pos_code

                    state = pos_code(state) or ""
                rows.append((n, d, str(cell("name") or ""), cell("amount"), cell("rate") or default_rate,
                             str(cell("bill") or ""), str(cell("desc") or ""), state, t.name))
        if not rows:
            raise UnsupportedFileError(f"{path.name}: no RCM list found – it needs columns for the date, the party "
                                       "and the amount")
        saved = 0
        with self.db.session() as s:
            sf = SourceFile(client_id=client_id, source_type="RCM", file_name=path.name,
                            file_path=str(path.resolve()), sha256=sha256_of(path), layout="rcm_list", period=None,
                            rows_read=len(rows), documents_imported=0, imported_by=user or "")
            s.add(sf)
            s.flush()
            for n, d, name, amount, rate, bill, desc, state, sheet in rows:
                try:
                    self.add_entry(client_id, d, name, amount, rate, user, bill, desc, state, sf.id, _session=s)
                    saved += 1
                except ServiceError as exc:
                    problems.append(f"{sheet}!{n} ({name}): {exc}")
            sf.documents_imported = saved
            audit(s, "IMPORT", "source_file", sf.id, {"file": path.name, "rcm_entries": saved,
                                                      "problems": len(problems)}, user, client_id)
        return saved, problems

    def self_invoices_pdf(self, client_id: int, period: str, path: str | Path, first_number: int = 1,
                          prefix: str = "SI", user: str | None = None) -> tuple[Path, int]:
        """Self-invoices (section 31(3)(f)) for the month's RCM purchases from unregistered suppliers."""
        from ..reports.self_invoice_pdf import build_self_invoices

        m = self.month(client_id, period)
        lines = sorted((ln for ln in m.marked if ln.needs_self_invoice), key=lambda x: (x.doc.invoice_date,
                                                                                         x.doc.invoice_no))
        if not lines:
            raise ServiceError(f"No reverse-charge purchase from an unregistered supplier in {period}")
        client = self._client(client_id)
        out = build_self_invoices(client, lines, Path(path), first_number, prefix)
        with self.db.session() as s:
            audit(s, "EXPORT", "self_invoices", period, {"count": len(lines), "first": first_number}, user, client_id)
        return out, len(lines)

    # ----------------------------------------------------------------- ISD
    def isd_units(self, isd_client_id: int) -> list[Client]:
        """Other registrations of the same PAN – the units the ISD can distribute to."""
        isd = self._client(isd_client_id)
        with self.db.session() as s:
            rows = list(s.scalars(select(Client).where(Client.pan == isd.pan, Client.id != isd_client_id,
                                                       Client.active.is_(True)).order_by(Client.gstin)))
            for r in rows:
                s.expunge(r)
        return rows

    def unit_turnover(self, client_id: int, fy: str) -> Decimal:
        """Taxable turnover of a unit in the year, from its sales register (exact decimals, added in Python)."""
        from .outward import OutwardService

        total = ZERO
        for r in OutwardService(self.db).sales(client_id, fy_months(fy)):
            total += -r.taxable if r.doc_type == DocType.CREDIT_NOTE else r.taxable
        return total

    def isd_itc(self, isd_client_id: int, period: str) -> Gstr3bValues:
        from .itc import ItcService

        with self.db.session() as s:
            docs = ItcService(self.db)._docs(s, isd_client_id, Source.BOOKS, [period])
        t = Gstr3bValues()
        for d in docs:
            k = -1 if d.doc_type == DocType.CREDIT_NOTE else 1
            t = Gstr3bValues(t.igst + k * d.igst, t.cgst + k * d.cgst, t.sgst + k * d.sgst, t.cess + k * d.cess,
                             t.taxable + k * d.taxable)
        return t

    def isd_distribution(self, isd_client_id: int, period: str, turnover: dict[int, Decimal] | None = None,
                         basis_fy: str | None = None) -> tuple[Gstr3bValues, list[IsdShare], str]:
        """Shares of the month's ISD credit. Turnover: given per unit, else the units' sales registers of the
        previous financial year (rule 39(1)(d))."""
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        isd = self._client(isd_client_id)
        units = self.isd_units(isd_client_id)
        if not units:
            raise ServiceError(f"No other registration of PAN {isd.pan} – add the units as clients first")
        y, mth = int(p[:4]), int(p[5:])
        fy_start = y if mth >= 4 else y - 1
        basis_fy = basis_fy or f"{fy_start - 1}-{str(fy_start)[2:]}"
        turnover = turnover or {}
        recips = [(u.name, u.gstin, Decimal(str(turnover[u.id])) if u.id in turnover else
                   self.unit_turnover(u.id, basis_fy)) for u in units]
        if not any(t > 0 for _n, _g, t in recips):
            raise ServiceError(f"No turnover found for the units in {basis_fy} – enter each unit's turnover")
        itc = self.isd_itc(isd_client_id, p)
        basis = "entered" if turnover else f"sales registers of FY {basis_fy}"
        return itc, distribute_isd(itc, isd.gstin[:2], recips), basis

    def export_isd(self, isd_client_id: int, period: str, shares: list[IsdShare], itc: Gstr3bValues, basis: str,
                   path: str | Path, first_number: int = 1, user: str | None = None) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        isd = self._client(isd_client_id)
        wb = Workbook()
        ws = wb.active
        ws.title = "Distribution"
        ws.append([f"ISD distribution – {isd.name} ({isd.gstin}) – {period}"])
        ws["A1"].font = Font(bold=True, size=12)
        ws.append([f"ITC available for distribution: IGST {itc.igst}, CGST {itc.cgst}, SGST {itc.sgst}, "
                   f"Cess {itc.cess}. Ratio: turnover ({basis}), rule 39."])
        ws.append([])
        head = ["ISD invoice no", "Date", "Recipient GSTIN", "Recipient", "Turnover", "Ratio %", "IGST", "CGST",
                "SGST", "Cess", "Total"]
        ws.append(head)
        for c in ws[4]:
            c.font = Font(bold=True)
        last_day = date(int(period[:4]) + (int(period[5:]) == 12), int(period[5:]) % 12 + 1, 1)
        from datetime import timedelta

        doc_date = last_day - timedelta(days=1)
        n = first_number
        for s in shares:
            if not s.total:
                continue
            ws.append([f"ISD/{period}/{n:03d}", doc_date, s.gstin, s.name, float(s.turnover), float(s.ratio),
                       float(s.igst), float(s.cgst), float(s.sgst), float(s.cess), float(s.total)])
            n += 1
        for col, w in zip("ABCDEFGHIJK", (18, 12, 18, 30, 16, 9, 14, 14, 14, 10, 14)):
            ws.column_dimensions[col].width = w
        path = Path(path)
        wb.save(path)
        with self.db.session() as s:
            audit(s, "EXPORT", "isd_distribution", period, {"units": len(shares), "basis": basis}, user,
                  isd_client_id)
        return path
