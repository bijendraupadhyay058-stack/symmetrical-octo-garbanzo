"""Register of GST notices and draft replies built from the reconciliations (see notices/content.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, GstNotice
from ..importers.parsing import parse_period
from ..notices.content import FORMS, NoticeFacts, PeriodComparison, ReplyDraft, build_reply
from .auth import Session, require
from .common import ServiceError, audit
from .reconciliation import months_between

STATUSES = ("OPEN", "REPLIED", "CLOSED")
FIELDS = ("form", "reference", "notice_date", "period_from", "period_to", "amount", "reply_due", "status",
          "replied_on", "officer", "remarks")


def _fy_of_period(p: str) -> str:
    y, m = int(p[:4]), int(p[5:])
    start = y if m >= 4 else y - 1
    return f"{start}-{str(start + 1)[-2:]}"


class NoticeService:
    def __init__(self, db: Database):
        self.db = db

    def list(self, client_id: int) -> list[GstNotice]:
        with self.db.session() as s:
            return list(s.scalars(select(GstNotice).where(GstNotice.client_id == client_id)
                                  .order_by(GstNotice.notice_date.desc(), GstNotice.id.desc())))

    def get(self, notice_id: int) -> GstNotice:
        with self.db.session() as s:
            n = s.get(GstNotice, notice_id)
            if n is None:
                raise ServiceError(f"Notice #{notice_id} not found")
            return n

    @staticmethod
    def _clean(values: dict) -> dict:
        out = {}
        for k, v in values.items():
            if k not in FIELDS:
                raise ServiceError(f"Unknown notice field '{k}'")
            if k == "form":
                v = str(v).upper()
                if v not in FORMS:
                    raise ServiceError(f"Form must be one of {', '.join(FORMS)}")
            elif k in ("period_from", "period_to"):
                v = parse_period(v) or ""
                if not v:
                    raise ServiceError(f"Invalid {k.replace('_', ' ')} (YYYY-MM)")
            elif k == "status":
                v = str(v).upper()
                if v not in STATUSES:
                    raise ServiceError(f"Status must be one of {', '.join(STATUSES)}")
            elif k == "amount" and v is not None and not isinstance(v, Decimal):
                try:
                    v = Decimal(str(v).replace(",", "").strip())
                except InvalidOperation:
                    raise ServiceError(f"'{v}' is not an amount") from None
            elif k in ("notice_date", "reply_due", "replied_on") and isinstance(v, str):
                v = date.fromisoformat(v) if v else None
            out[k] = v
        return out

    def add(self, client_id: int, by: Session | None, **values) -> int:
        require(by, "review")
        values = self._clean(values)
        for k in ("form", "notice_date", "period_from"):
            if not values.get(k):
                raise ServiceError(f"Give the {k.replace('_', ' ')}")
        values.setdefault("period_to", values["period_from"])
        if values["period_to"] < values["period_from"]:
            raise ServiceError("Period to is before period from")
        with self.db.session() as s:
            n = GstNotice(client_id=client_id, updated_by=by.username, **values)
            s.add(n)
            s.flush()
            audit(s, "NOTICE_ADD", "gst_notice", n.id, {k: v for k, v in values.items()}, by.username, client_id)
            return n.id

    def update(self, notice_id: int, by: Session | None, **values) -> None:
        require(by, "review")
        values = self._clean(values)
        with self.db.session() as s:
            n = s.get(GstNotice, notice_id)
            if n is None:
                raise ServiceError(f"Notice #{notice_id} not found")
            before = {k: getattr(n, k) for k in values}
            for k, v in values.items():
                setattr(n, k, v)
            if values.get("status") == "REPLIED" and n.replied_on is None:
                n.replied_on = date.today()
            n.updated_by = by.username
            audit(s, "NOTICE_UPDATE", "gst_notice", notice_id, {"before": before, "after": values}, by.username,
                  n.client_id)

    def delete(self, notice_id: int, by: Session | None) -> None:
        require(by, "review")
        with self.db.session() as s:
            n = s.get(GstNotice, notice_id)
            if n is None:
                raise ServiceError(f"Notice #{notice_id} not found")
            audit(s, "NOTICE_DELETE", "gst_notice", notice_id, {"form": n.form, "reference": n.reference},
                  by.username, n.client_id)
            s.delete(n)

    # ------------------------------------------------------------- drafting
    def build(self, notice_id: int, as_of: date | None = None) -> tuple[ReplyDraft, GstNotice, Client]:
        from .interest import InterestService
        from .itc import ItcService
        from .outward import OutwardService

        as_of = as_of or date.today()
        n = self.get(notice_id)
        with self.db.session() as s:
            client = s.get(Client, n.client_id)
        months = months_between(n.period_from, n.period_to)
        facts = NoticeFacts(n.form, n.reference, n.notice_date, n.period_from, n.period_to, n.amount, n.officer,
                            client.name, client.gstin)
        from .gstr3b import Gstr3bService

        filed = Gstr3bService(self.db).values(n.client_id, months)
        liability, itc = [], []
        if n.form in ("DRC-01B", "ASMT-10", "OTHER"):
            have_g1 = {p for p, rows in OutwardService(self.db).summaries(n.client_id, months).items() if rows}
            for lw in OutwardService(self.db).liability(n.client_id, months):
                if lw.period not in filed or lw.period not in have_g1:
                    continue
                g1 = sum((lw.row(c).gstr1.total for c in ("31A", "31B")), ZERO)
                paid = sum((lw.row(c).filed.total for c in ("31A", "31B") if lw.row(c).filed is not None), ZERO)
                liability.append(PeriodComparison(lw.period, g1, paid, [
                    (f.kind, f.text, f.amount) for f in lw.findings]))
        if n.form in ("DRC-01C", "ASMT-10", "OTHER"):
            for pw in ItcService(self.db).table4(n.client_id, [p for p in months if p in filed], as_of):
                r = pw.row("4C")
                if r.filed is None:
                    continue
                itc.append(PeriodComparison(pw.period, r.filed.total, r.auto_2b.total, [
                    (f.kind, f.text, f.amount) for f in pw.findings]))
        short, excess = [], []
        isvc = InterestService(self.db)
        for fy in sorted({_fy_of_period(p) for p in months}):
            w = isvc.working(n.client_id, fy, as_of)
            short += [e for e in w.exposures if e.kind == "SHORT_PAYMENT" and e.period in months]
            excess += [e for e in w.exposures if e.kind == "EXCESS_ITC" and e.period in months]
        return build_reply(facts, liability, itc, short, excess, as_of), n, client

    def draft(self, notice_id: int, out_dir, as_of: date | None = None, signatory: str = "",
              user: str | None = None) -> tuple[Path, ReplyDraft]:
        from ..letters.render import safe_name
        from ..notices.render import render_reply

        draft, n, client = self.build(notice_id, as_of)
        name = f"FINTAXPRO_Reply_{n.form}_{safe_name(n.reference or str(n.id))}_{client.gstin}.docx"
        path = render_reply(draft, Path(out_dir) / name, client.name, client.gstin, client.address or "", n.officer,
                            date.today(), signatory)
        with self.db.session() as s:
            audit(s, "NOTICE_DRAFT", "gst_notice", notice_id, {"file": str(path), "placeholders": draft.placeholders},
                  user, n.client_id)
        return path, draft

    def due(self, client_id: int | None = None, on: date | None = None, days: int = 15) -> list[GstNotice]:
        """Open notices whose reply is due within ``days`` (or overdue)."""
        from datetime import timedelta

        on = on or date.today()
        with self.db.session() as s:
            q = select(GstNotice).where(GstNotice.status == "OPEN", GstNotice.reply_due.is_not(None),
                                        GstNotice.reply_due <= on + timedelta(days=days))
            if client_id is not None:
                q = q.where(GstNotice.client_id == client_id)
            return list(s.scalars(q.order_by(GstNotice.reply_due)))
