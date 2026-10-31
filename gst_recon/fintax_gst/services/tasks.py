"""Staff tasks: work entered by hand, and return-filing tasks created from the due-date calendar for each client
(assigned to the client's responsible staff). A return task closes itself when the filing is recorded."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select

from ..compliance.calendar import due_items
from ..db.database import Database
from ..db.models import Client, ReturnFiling, StaffTask
from ..importers.parsing import parse_period
from .common import ServiceError, audit
from .reminders import month_name


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class TaskView:
    task: StaffTask
    client: str

    def state(self, today: date) -> str:
        t = self.task
        if t.status == "done":
            return "Done"
        if t.due_date is None:
            return "Open"
        days = (t.due_date - today).days
        return "Overdue" if days < 0 else ("Due today" if days == 0 else ("Due soon" if days <= 3 else "Open"))


class TaskService:
    def __init__(self, db: Database):
        self.db = db

    def add(self, title: str, user: str, assignee: str = "", due_date: date | None = None,
            client_id: int | None = None, notes: str = "") -> StaffTask:
        if not title.strip():
            raise ServiceError("Describe the task")
        with self.db.session() as s:
            if client_id is not None and s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            t = StaffTask(title=title.strip()[:200], assignee=assignee.strip()[:80], due_date=due_date,
                          client_id=client_id, notes=notes, created_by=user[:80])
            s.add(t)
            s.flush()
            audit(s, "TASK_ADD", "staff_tasks", t.id, {"title": t.title, "assignee": t.assignee}, user, client_id)
            s.expunge(t)
        return t

    def set_status(self, task_ids: list[int], done: bool, user: str) -> int:
        n = 0
        with self.db.session() as s:
            for t in s.scalars(select(StaffTask).where(StaffTask.id.in_(task_ids))):
                if (t.status == "done") == done:
                    continue
                t.status = "done" if done else "open"
                t.done_by, t.done_at = (user[:80], _now()) if done else ("", None)
                n += 1
                audit(s, "TASK_DONE" if done else "TASK_REOPEN", "staff_tasks", t.id, {"title": t.title}, user,
                      t.client_id)
        return n

    def reassign(self, task_ids: list[int], assignee: str, user: str) -> int:
        with self.db.session() as s:
            rows = list(s.scalars(select(StaffTask).where(StaffTask.id.in_(task_ids))))
            for t in rows:
                t.assignee = assignee.strip()[:80]
            audit(s, "TASK_ASSIGN", "staff_tasks", ",".join(map(str, task_ids)), {"assignee": assignee}, user)
        return len(rows)

    def delete(self, task_ids: list[int], user: str) -> int:
        with self.db.session() as s:
            rows = list(s.scalars(select(StaffTask).where(StaffTask.id.in_(task_ids))))
            for t in rows:
                audit(s, "TASK_DELETE", "staff_tasks", t.id, {"title": t.title, "status": t.status}, user,
                      t.client_id)
                s.delete(t)
        return len(rows)

    def return_tasks(self, period: str, user: str) -> tuple[int, int]:
        """Create filing tasks for the period's returns of every active client; returns (created, closed)."""
        from .calendar import CalendarService

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        overrides = CalendarService(self.db).overrides()
        created = 0
        with self.db.session() as s:
            existing = set(s.scalars(select(StaffTask.auto_key).where(StaffTask.auto_key.is_not(None))))
            for c in s.scalars(select(Client).where(Client.active.is_(True))):
                for d in due_items(p, c.return_frequency, c.state_code, overrides):
                    if d.optional:
                        continue
                    key = f"{c.id}:{d.return_type}:{d.period}"
                    if key in existing:
                        continue
                    s.add(StaffTask(client_id=c.id, title=f"File {d.return_type} – {month_name(d.period)}",
                                    assignee=c.staff or "", due_date=d.due, auto_key=key, created_by=user[:80]))
                    existing.add(key)
                    created += 1
            if created:
                audit(s, "TASK_GENERATE", "staff_tasks", p, {"created": created}, user)
        return created, self.close_filed(user)

    def close_filed(self, user: str = "") -> int:
        """Return tasks whose filing has been recorded are marked done."""
        n = 0
        with self.db.session() as s:
            filed = {(f.client_id, f.return_type, f.period) for f in s.scalars(select(ReturnFiling))}
            for t in s.scalars(select(StaffTask).where(StaffTask.status == "open", StaffTask.auto_key.is_not(None))):
                cid, rtype, period = t.auto_key.split(":", 2)
                if (int(cid), rtype, period) in filed:
                    t.status, t.done_by, t.done_at = "done", "filing recorded", _now()
                    n += 1
        return n

    def tasks(self, assignee: str | None = None, include_done: bool = False,
              client_id: int | None = None) -> list[TaskView]:
        self.close_filed()
        with self.db.session() as s:
            q = select(StaffTask)
            if not include_done:
                q = q.where(StaffTask.status == "open")
            if assignee is not None:
                q = q.where(StaffTask.assignee == assignee)
            if client_id is not None:
                q = q.where(StaffTask.client_id == client_id)
            rows = list(s.scalars(q))
            names = dict(s.execute(select(Client.id, Client.name)).all())
        rows.sort(key=lambda t: (t.status == "done", t.due_date or date.max, t.id))
        return [TaskView(t, names.get(t.client_id, "")) for t in rows]

    def assignees(self) -> list[str]:
        from .firm import FirmService

        with self.db.session() as s:
            names = set(s.scalars(select(StaffTask.assignee).where(StaffTask.assignee != "")))
        return sorted(names | {n for n in FirmService(self.db).staff_names() if n and not n.startswith("(")})
