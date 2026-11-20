"""The firm's own fee billing: fee invoices to clients (with GST when the firm is registered), receipts with TDS,
outstanding fees and an invoice PDF.

Invoice numbers run per financial year (e.g. FTP/2025-26/0001) and are never reused: an invoice issued by
mistake is cancelled, not deleted. All money is Decimal and rounded to the paisa.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from ..core.gstin import normalize_gstin, validate_gstin
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import AppSetting, Client, FeeInvoice, FeeReceipt
from ..core.models import fy_of
from .auth import Session, require
from .common import ServiceError, audit

PROFILE_KEY = "firm_profile"
PAISA = Decimal("0.01")
MODES = ("Bank transfer", "UPI", "Cheque", "Cash", "Other")


def _r(v: Decimal) -> Decimal:
    return Decimal(v).quantize(PAISA, rounding=ROUND_HALF_UP)


def _amount(v, what: str) -> Decimal:
    try:
        d = Decimal(str(v).replace(",", "").strip() or "0")
    except InvalidOperation:
        raise ServiceError(f"{what}: '{v}' is not an amount") from None
    return _r(d)


@dataclass
class FirmProfile:
    name: str = ""
    address: str = ""
    gstin: str = ""  # blank: the firm is not registered – a bill of supply without GST
    state_code: str = ""
    pan: str = ""
    email: str = ""
    phone: str = ""
    bank: str = ""  # bank name, account and IFSC for the invoice
    prefix: str = "FTP"
    sac: str = "9982"  # legal and accounting services
    gst_rate: str = "18"
    due_days: int = 15


@dataclass
class Outstanding:
    client_id: int
    name: str
    billed: Decimal = ZERO
    received: Decimal = ZERO
    tds: Decimal = ZERO
    oldest_due: date | None = None
    invoices: int = 0

    @property
    def balance(self) -> Decimal:
        return self.billed - self.received - self.tds

    def overdue_days(self, today: date) -> int:
        return max((today - self.oldest_due).days, 0) if self.oldest_due and self.balance > 0 else 0


@dataclass
class InvoiceView:
    inv: FeeInvoice
    client: str
    lines: list[dict] = field(default_factory=list)
    received: Decimal = ZERO

    @property
    def balance(self) -> Decimal:
        return ZERO if self.inv.status == "cancelled" else self.inv.total - self.received


class BillingService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ profile
    def profile(self) -> FirmProfile:
        with self.db.session() as s:
            row = s.get(AppSetting, PROFILE_KEY)
            data = json.loads(row.value_json) if row else {}
        return FirmProfile(**{k: v for k, v in data.items() if k in FirmProfile.__dataclass_fields__})

    def save_profile(self, p: FirmProfile, by: Session | None) -> None:
        require(by, "settings")
        if not p.name.strip():
            raise ServiceError("Enter the firm's name")
        g = normalize_gstin(p.gstin)
        if g:
            ok, problem = validate_gstin(g)
            if not ok or problem:
                raise ServiceError(f"GSTIN {g} is not valid")
            p.state_code = g[:2]
            p.pan = p.pan or g[2:12]
        p.gstin = g
        if not p.prefix.strip():
            raise ServiceError("Enter an invoice number prefix, e.g. your firm's initials")
        _amount(p.gst_rate, "GST rate")
        with self.db.session() as s:
            row = s.get(AppSetting, PROFILE_KEY)
            if row is None:
                row = AppSetting(key=PROFILE_KEY, value_json="{}")
                s.add(row)
            row.value_json = json.dumps(asdict(p))
            audit(s, "SETTING", "app_settings", PROFILE_KEY, {"name": p.name, "gstin": p.gstin}, by.username)

    # ----------------------------------------------------------- invoices
    def _next_number(self, s, prefix: str, fy: str) -> str:
        stem = f"{prefix}/{fy}/"
        last = [int(n[len(stem):]) for n in s.scalars(select(FeeInvoice.number).where(
            FeeInvoice.number.like(f"{stem}%"))) if n[len(stem):].isdigit()]
        return f"{stem}{(max(last) if last else 0) + 1:04d}"

    def create_invoice(self, client_id: int, lines: list[tuple[str, object]], by: Session | None,
                       invoice_date: date | None = None, notes: str = "") -> FeeInvoice:
        require(by, "manage_clients")
        prof = self.profile()
        if not prof.name:
            raise ServiceError("Fill in the firm profile first (name, address, GSTIN if registered)")
        items = [(str(t).strip(), _amount(a, f"'{t}'")) for t, a in lines if str(t).strip() or str(a).strip()]
        if not items or not any(a for _t, a in items):
            raise ServiceError("Enter at least one fee line with an amount")
        if any(not t for t, _a in items):
            raise ServiceError("Every fee line needs a description")
        invoice_date = invoice_date or date.today()
        taxable = sum((a for _t, a in items), ZERO)
        igst = cgst = sgst = ZERO
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            if prof.gstin:
                rate = _amount(prof.gst_rate, "GST rate")
                if client.state_code and client.state_code != prof.state_code:
                    igst = _r(taxable * rate / 100)
                else:
                    cgst = _r(taxable * rate / 200)
                    sgst = cgst
            inv = FeeInvoice(client_id=client_id, number=self._next_number(s, prof.prefix.strip(), fy_of(invoice_date)),
                             invoice_date=invoice_date, due_date=invoice_date + timedelta(days=int(prof.due_days)),
                             lines_json=json.dumps([{"text": t, "amount": str(a)} for t, a in items]),
                             sac=prof.sac if prof.gstin else "", taxable=taxable, igst=igst, cgst=cgst, sgst=sgst,
                             total=taxable + igst + cgst + sgst, notes=notes, created_by=by.username)
            s.add(inv)
            s.flush()
            audit(s, "FEE_INVOICE", "fee_invoices", inv.id, {"number": inv.number, "total": inv.total},
                  by.username, client_id)
            s.expunge(inv)
        return inv

    def cancel_invoice(self, invoice_id: int, reason: str, by: Session | None) -> None:
        require(by, "manage_clients")
        if not reason.strip():
            raise ServiceError("Give the reason for cancelling")
        with self.db.session() as s:
            inv = s.get(FeeInvoice, invoice_id)
            if inv is None:
                raise ServiceError(f"Fee invoice {invoice_id} not found")
            if s.scalar(select(FeeReceipt.id).where(FeeReceipt.invoice_id == invoice_id).limit(1)):
                raise ServiceError(f"{inv.number} has receipts against it – remove them before cancelling")
            inv.status = "cancelled"
            inv.notes = f"{inv.notes}\nCancelled: {reason.strip()}".strip()
            audit(s, "FEE_INVOICE_CANCEL", "fee_invoices", inv.id, {"number": inv.number, "reason": reason},
                  by.username, inv.client_id)

    def invoices(self, client_id: int | None = None, fy: str | None = None) -> list[InvoiceView]:
        with self.db.session() as s:
            q = select(FeeInvoice).order_by(FeeInvoice.invoice_date.desc(), FeeInvoice.id.desc())
            if client_id:
                q = q.where(FeeInvoice.client_id == client_id)
            rows = list(s.scalars(q))
            names = dict(s.execute(select(Client.id, Client.name)).all())
            paid: dict[int, Decimal] = {}
            for r in s.scalars(select(FeeReceipt).where(FeeReceipt.invoice_id.is_not(None))):
                paid[r.invoice_id] = paid.get(r.invoice_id, ZERO) + r.amount + r.tds
        if fy:
            rows = [r for r in rows if fy_of(r.invoice_date) == fy]
        return [InvoiceView(r, names.get(r.client_id, ""), json.loads(r.lines_json), paid.get(r.id, ZERO))
                for r in rows]

    # ----------------------------------------------------------- receipts
    def record_receipt(self, client_id: int, amount, received_on: date, by: Session | None, mode: str = "",
                       reference: str = "", tds=0, invoice_id: int | None = None, notes: str = "") -> FeeReceipt:
        require(by, "manage_clients")
        amt, tds_amt = _amount(amount, "Amount"), _amount(tds, "TDS")
        if amt <= 0 and tds_amt <= 0:
            raise ServiceError("Enter the amount received")
        if amt < 0 or tds_amt < 0:
            raise ServiceError("Amounts cannot be negative")
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            if invoice_id is not None:
                inv = s.get(FeeInvoice, invoice_id)
                if inv is None or inv.client_id != client_id:
                    raise ServiceError("That invoice is not this client's")
                if inv.status == "cancelled":
                    raise ServiceError(f"{inv.number} is cancelled")
            r = FeeReceipt(client_id=client_id, invoice_id=invoice_id, received_on=received_on, amount=amt,
                           tds=tds_amt, mode=mode[:20], reference=reference[:80], notes=notes, created_by=by.username)
            s.add(r)
            s.flush()
            audit(s, "FEE_RECEIPT", "fee_receipts", r.id, {"amount": amt, "tds": tds_amt, "invoice": invoice_id},
                  by.username, client_id)
            s.expunge(r)
        return r

    def delete_receipt(self, receipt_id: int, by: Session | None) -> None:
        require(by, "manage_clients")
        with self.db.session() as s:
            r = s.get(FeeReceipt, receipt_id)
            if r is None:
                raise ServiceError(f"Receipt {receipt_id} not found")
            audit(s, "FEE_RECEIPT_DELETE", "fee_receipts", r.id, {"amount": r.amount, "tds": r.tds,
                                                                  "received_on": r.received_on}, by.username,
                  r.client_id)
            s.delete(r)

    def receipts(self, client_id: int | None = None) -> list[FeeReceipt]:
        with self.db.session() as s:
            q = select(FeeReceipt).order_by(FeeReceipt.received_on.desc(), FeeReceipt.id.desc())
            if client_id:
                q = q.where(FeeReceipt.client_id == client_id)
            return list(s.scalars(q))

    def outstanding(self) -> list[Outstanding]:
        """Per client: billed (issued invoices), received and TDS; oldest unpaid due date (first in, first out)."""
        with self.db.session() as s:
            names = dict(s.execute(select(Client.id, Client.name)).all())
            invs = list(s.scalars(select(FeeInvoice).where(FeeInvoice.status == "issued")
                                  .order_by(FeeInvoice.invoice_date, FeeInvoice.id)))
            recs = list(s.scalars(select(FeeReceipt)))
        out: dict[int, Outstanding] = {}
        for i in invs:
            o = out.setdefault(i.client_id, Outstanding(i.client_id, names.get(i.client_id, "")))
            o.billed += i.total
            o.invoices += 1
        for r in recs:
            o = out.setdefault(r.client_id, Outstanding(r.client_id, names.get(r.client_id, "")))
            o.received += r.amount
            o.tds += r.tds
        for cid, o in out.items():
            paid = o.received + o.tds
            for i in (x for x in invs if x.client_id == cid):
                if paid >= i.total:
                    paid -= i.total
                    continue
                o.oldest_due = i.due_date or i.invoice_date
                break
        return sorted(out.values(), key=lambda o: (-o.balance, o.name))

    # ---------------------------------------------------------------- PDF
    def invoice_pdf(self, invoice_id: int, path: str | Path) -> Path:
        from ..reports.fee_invoice_pdf import build_fee_invoice

        view = next((v for v in self.invoices() if v.inv.id == invoice_id), None)
        if view is None:
            raise ServiceError(f"Fee invoice {invoice_id} not found")
        with self.db.session() as s:
            client = s.get(Client, view.inv.client_id)
            s.expunge(client)
        return build_fee_invoice(self.profile(), client, view, Path(path))
