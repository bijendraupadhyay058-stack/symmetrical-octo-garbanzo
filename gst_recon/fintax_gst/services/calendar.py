"""Due-date extensions (recorded by the user) and the upcoming-returns list across clients."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from ..compliance.calendar import RETURN_TYPES, DueItem, DueOverride, annual_items, due_items
from ..core.gstin import STATE_CODES
from ..db.database import Database
from ..db.models import Client, DueDateOverride, Gstr1Summary, Gstr3bEntry, Invoice
from .auth import Session, require
from .common import ServiceError, audit


@dataclass
class Upcoming:
    client_id: int
    client: str
    gstin: str
    item: DueItem
    status: str  # "imported", "not imported", "not tracked"
    overdue: bool = False  # past the due date (as of the day asked) with the return data not imported


class CalendarService:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------- extensions
    def overrides(self) -> list[DueOverride]:
        with self.db.session() as s:
            return [DueOverride(o.return_type, o.period, o.due_date, o.reference,
                                frozenset(x for x in o.state_codes.split(",") if x))
                    for o in s.scalars(select(DueDateOverride).order_by(DueDateOverride.id))]

    def override_rows(self) -> list[DueDateOverride]:
        with self.db.session() as s:
            rows = list(s.scalars(select(DueDateOverride).order_by(DueDateOverride.period.desc(),
                                                                   DueDateOverride.return_type)))
            for r in rows:
                s.expunge(r)
        return rows

    def add_override(self, return_type: str, period: str, due: date, reference: str, by: Session,
                     state_codes: list[str] | None = None) -> DueDateOverride:
        require(by, "settings")
        if return_type not in RETURN_TYPES:
            raise ServiceError(f"Return type must be one of {', '.join(RETURN_TYPES)}")
        annual = return_type in ("GSTR-9", "GSTR-9C")
        valid = (len(period) == 7 and period[4] == "-" and
                 (period[5:].isdigit() if annual else (period[:4].isdigit() and 1 <= int(period[5:]) <= 12)))
        if not valid:
            raise ServiceError("Period must be YYYY-MM (or the financial year, e.g. 2025-26, for GSTR-9/9C)")
        if not reference.strip():
            raise ServiceError("Record the notification or circular that extended the date")
        codes = sorted({c.strip().zfill(2) for c in state_codes or [] if c.strip()})
        unknown = [c for c in codes if c not in STATE_CODES]
        if unknown:
            raise ServiceError(f"Unknown state code(s): {', '.join(unknown)}")
        with self.db.session() as s:
            o = DueDateOverride(return_type=return_type, period=period, due_date=due, reference=reference.strip(),
                                state_codes=",".join(codes), recorded_by=by.username)
            s.add(o)
            s.flush()
            audit(s, "DUE_DATE_EXTENSION", "due_date_overrides", o.id,
                  {"return": return_type, "period": period, "due": due, "reference": reference, "states": codes},
                  by.username)
            s.expunge(o)
        return o

    def delete_override(self, override_id: int, by: Session) -> None:
        require(by, "settings")
        with self.db.session() as s:
            o = s.get(DueDateOverride, override_id)
            if o is None:
                raise ServiceError(f"Extension {override_id} not found")
            audit(s, "DELETE", "due_date_overrides", override_id,
                  {"return": o.return_type, "period": o.period, "due": o.due_date}, by.username)
            s.delete(o)

    # ------------------------------------------------------------ upcoming
    def upcoming(self, today: date | None = None, days: int = 30, overdue_days: int = 60) -> list[Upcoming]:
        """Returns due from ``overdue_days`` ago to ``days`` ahead for every active client, with
        whether the data that shows filing (GSTR-3B / GSTR-1) has been imported."""
        today = today or date.today()
        start, end = today - timedelta(days=overdue_days), today + timedelta(days=days)
        overrides = self.overrides()
        # tax periods whose returns can fall due in the window: up to three months before it
        periods = []
        y, m = start.year, start.month
        for _ in range(6):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        for _ in range(6 + (end.year - start.year) * 12 + end.month - start.month + 1):
            periods.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        out = []
        with self.db.session() as s:
            clients = list(s.scalars(select(Client).where(Client.active.is_(True)).order_by(Client.name)))
            filed3b = set(s.execute(select(Gstr3bEntry.client_id, Gstr3bEntry.period)
                                    .where(Gstr3bEntry.active.is_(True), Gstr3bEntry.period.in_(periods))).all())
            g1 = set(s.execute(select(Gstr1Summary.client_id, Gstr1Summary.period)
                               .where(Gstr1Summary.period.in_(periods))).all())
            g1 |= set(s.execute(select(Invoice.client_id, Invoice.period).where(
                Invoice.source_type == "GSTR1", Invoice.period.in_(periods)).distinct()).all())
        for c in clients:
            items = [i for p in periods for i in due_items(p, c.return_frequency, c.state_code, overrides)]
            for due_year in range(start.year, end.year + 1):  # GSTR-9 of FY (y-1)-y is due on 31 December of y
                items += annual_items(f"{due_year - 1}-{str(due_year)[-2:]}", c.state_code, overrides)
            for i in items:
                if not (start <= i.due <= end):
                    continue
                if i.return_type == "GSTR-3B":
                    status = "imported" if (c.id, i.period) in filed3b else "not imported"
                elif i.return_type == "GSTR-1":
                    status = "imported" if (c.id, i.period) in g1 else "not imported"
                else:
                    status = "not tracked"
                out.append(Upcoming(c.id, c.name, c.gstin, i, status, status == "not imported" and i.due < today))
        return sorted(out, key=lambda u: (u.item.due, u.client, u.item.return_type))
