"""Client document reminders: what each client still has to send or answer for a month, as a message.

For the chosen tax period, per active client:

* the purchase register, if none is imported (and the sales register, if GSTR-1 data is in but no sales
  register – or ``ask_sales`` is set);
* invoices the reviewer marked *Client Clarification Required* in the latest reconciliations of the month;
* invoices marked *Correction Required in Books*.

The message is plain text for e-mail or WhatsApp. **The program never sends it**: the user copies it, or
opens it in their own e-mail program or WhatsApp, and each such step is logged (``ClientReminder``).
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from ..core.models import ExceptionStatus
from ..core.money import fmt_inr
from ..db.database import Database
from ..db.models import Client, ClientReminder, Invoice, ReconLineRow, ReconRun
from ..importers.parsing import parse_period
from .common import ServiceError, audit

CHANNELS = ("copy", "email", "whatsapp")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def month_name(period: str) -> str:
    return f"{_MONTHS[int(period[5:]) - 1]} {period[:4]}"


@dataclass
class DocLine:
    party: str
    gstin: str
    invoice_no: str
    invoice_date: date
    tax: Decimal
    remarks: str

    def text(self) -> str:
        note = f" – {self.remarks.splitlines()[-1][:120]}" if self.remarks.strip() else ""
        return (f"{self.party or self.gstin}, invoice {self.invoice_no} dated {self.invoice_date:%d-%m-%Y}, "
                f"tax {fmt_inr(self.tax)}{note}")


@dataclass
class ClientRequest:
    client_id: int
    name: str
    contact: str
    email: str
    mobile: str
    staff: str
    period: str
    documents: list[str] = field(default_factory=list)
    clarify: list[DocLine] = field(default_factory=list)
    correct: list[DocLine] = field(default_factory=list)
    last_reminded: datetime | None = None
    times_reminded: int = 0

    @property
    def needed(self) -> bool:
        return bool(self.documents or self.clarify or self.correct)

    def items(self) -> list[str]:
        return ([*self.documents] + [f"Clarify: {d.text()}" for d in self.clarify]
                + [f"Correct in books: {d.text()}" for d in self.correct])

    def summary(self) -> str:
        parts = list(self.documents)
        if self.clarify:
            parts.append(f"{len(self.clarify)} invoice(s) to clarify")
        if self.correct:
            parts.append(f"{len(self.correct)} correction(s) in books")
        return "; ".join(parts)


class ReminderService:
    def __init__(self, db: Database):
        self.db = db

    def requests(self, period: str, staff: str | None = None, ask_sales: bool = False,
                 only_needed: bool = True) -> list[ClientRequest]:
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        label = month_name(p)
        with self.db.session() as s:
            clients = list(s.scalars(select(Client).where(Client.active.is_(True)).order_by(Client.name)))
            if staff is not None:
                clients = [c for c in clients if (c.staff or "") == staff]
            ids = [c.id for c in clients]
            if not ids:
                return []
            have = {(cid, src) for cid, src in s.execute(
                select(Invoice.client_id, Invoice.source_type).where(Invoice.client_id.in_(ids), Invoice.period == p)
                .distinct())}
            latest: dict[tuple[int, str], int] = {}
            for r in s.execute(select(ReconRun.client_id, ReconRun.comparison, ReconRun.id).where(
                    ReconRun.client_id.in_(ids), ReconRun.period_from == p, ReconRun.period_to == p)
                    .order_by(ReconRun.id)):
                latest[(r.client_id, r.comparison)] = r.id
            run_client = {rid: cid for (cid, _c), rid in latest.items()}
            asks = {ExceptionStatus.CLIENT_CLARIFICATION.value: "clarify",
                    ExceptionStatus.BOOKS_CORRECTION.value: "correct"}
            lines = list(s.execute(
                select(ReconLineRow.run_id, ReconLineRow.status, ReconLineRow.remarks, Invoice)
                .join(Invoice, Invoice.id == func.coalesce(ReconLineRow.books_invoice_id,
                                                           ReconLineRow.gstr2b_invoice_id))
                .where(ReconLineRow.run_id.in_(list(run_client)), ReconLineRow.status.in_(list(asks)))
                .order_by(ReconLineRow.run_id, ReconLineRow.line_no))) if run_client else []
            reminded = {cid: (n, last) for cid, n, last in s.execute(
                select(ClientReminder.client_id, func.count(), func.max(ClientReminder.made_at))
                .where(ClientReminder.client_id.in_(ids), ClientReminder.period == p)
                .group_by(ClientReminder.client_id))}
            out: dict[int, ClientRequest] = {}
            for c in clients:
                r = ClientRequest(c.id, c.name, c.contact_person or "", c.email or "", c.mobile or "", c.staff or "",
                                  p)
                if (c.id, "BOOKS") not in have:
                    r.documents.append(f"Purchase register for {label}")
                if (c.id, "SALES") not in have and (ask_sales or (c.id, "GSTR1") in have):
                    r.documents.append(f"Sales register for {label}")
                r.times_reminded, r.last_reminded = reminded.get(c.id, (0, None))
                out[c.id] = r
            for run_id, status, remarks, inv in lines:
                d = DocLine(inv.supplier_name, inv.supplier_gstin, inv.invoice_no, inv.invoice_date,
                            inv.igst + inv.cgst + inv.sgst + inv.cess, remarks or "")
                getattr(out[run_client[run_id]], asks[status]).append(d)
        rows = list(out.values())
        return [r for r in rows if r.needed] if only_needed else rows

    @staticmethod
    def message(r: ClientRequest, signature: str = "") -> str:
        label = month_name(r.period)
        greet = f"Dear {r.contact}," if r.contact else f"Dear Sir/Madam ({r.name}),"
        out = [greet, "", f"For the GST work of {r.name} for {label}, we need the following from you:", ""]
        n = 0
        for doc in r.documents:
            n += 1
            out.append(f"{n}. {doc}")
        if r.clarify:
            n += 1
            out.append(f"{n}. Please clarify these purchase/sales invoices:")
            out += [f"   - {d.text()}" for d in r.clarify]
        if r.correct:
            n += 1
            out.append(f"{n}. Please correct these entries in your books (or tell us if they are right):")
            out += [f"   - {d.text()}" for d in r.correct]
        out += ["", "Kindly send them at the earliest so that the returns can be filed on time.", "", "Regards,"]
        out += [signature] if signature else []
        return "\n".join(out)

    @staticmethod
    def mailto(r: ClientRequest, text: str) -> str:
        subject = f"GST {month_name(r.period)} – documents needed from {r.name}"
        query = urllib.parse.urlencode({"subject": subject, "body": text}, quote_via=urllib.parse.quote)
        return f"mailto:{urllib.parse.quote(r.email)}?{query}"

    @staticmethod
    def whatsapp(r: ClientRequest, text: str) -> str:
        digits = "".join(ch for ch in r.mobile if ch.isdigit())
        if len(digits) == 10:  # an Indian mobile number without the country code
            digits = "91" + digits
        return f"https://wa.me/{digits}?text={urllib.parse.quote(text)}" if digits else \
            f"https://wa.me/?text={urllib.parse.quote(text)}"

    def record(self, r: ClientRequest, channel: str, user: str | None = None) -> None:
        if channel not in CHANNELS:
            raise ServiceError(f"Unknown channel {channel}")
        with self.db.session() as s:
            s.add(ClientReminder(client_id=r.client_id, period=r.period, channel=channel,
                                 items_json=json.dumps(r.items()), user=(user or "")[:80]))
            audit(s, "REMINDER", "client_reminder", f"{r.client_id}:{r.period}",
                  {"channel": channel, "items": len(r.items())}, user, r.client_id)

    def history(self, client_id: int, period: str | None = None) -> list[ClientReminder]:
        with self.db.session() as s:
            q = select(ClientReminder).where(ClientReminder.client_id == client_id)
            if period:
                q = q.where(ClientReminder.period == period)
            return list(s.scalars(q.order_by(ClientReminder.id.desc())))
