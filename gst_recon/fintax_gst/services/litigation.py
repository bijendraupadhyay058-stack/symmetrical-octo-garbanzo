"""Litigation tracker: GST disputes from notice to order, appeal and tribunal, with time limits, pre-deposit,
hearings and a dated history (see compliance/litigation.py for the rules)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from ..compliance.litigation import STAGES, STATUSES, limitation, next_step, pre_deposit
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import CaseEvent, Client, GstNotice, LitigationCase
from .common import ServiceError, audit

MONEY = ("tax", "interest", "penalty", "tax_admitted", "pre_deposit_paid")
FIELDS = ("title", "stage", "form", "reference", "order_date", "period_from", "period_to", *MONEY, "pre_deposit_ref",
          "appeal_filed_on", "appeal_ref", "hearing_date", "status", "remarks")


@dataclass
class Alert:
    case: LitigationCase
    client: str
    on: date
    kind: str  # limitation / hearing / pre-deposit
    text: str


class LitigationService:
    def __init__(self, db: Database):
        self.db = db

    def _clean(self, values: dict) -> dict:
        out = {}
        for k, v in values.items():
            if k not in FIELDS:
                raise ServiceError(f"Unknown field {k}")
            if k in MONEY:
                try:
                    v = Decimal(str(v or "0").replace(",", "").strip() or "0")
                except InvalidOperation:
                    raise ServiceError(f"{k.replace('_', ' ')}: '{v}' is not an amount") from None
                if v < 0:
                    raise ServiceError(f"{k.replace('_', ' ')} cannot be negative")
            if k == "stage" and v not in STAGES:
                raise ServiceError(f"Stage must be one of {', '.join(STAGES)}")
            if k == "status" and v not in STATUSES:
                raise ServiceError(f"Status must be one of {', '.join(STATUSES)}")
            out[k] = v.strip() if isinstance(v, str) else v
        return out

    def add(self, client_id: int, user: str, **values) -> LitigationCase:
        values = self._clean(values)
        if not values.get("title"):
            raise ServiceError("Give the case a title (e.g. 'ITC mismatch FY 2021-22')")
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            c = LitigationCase(client_id=client_id, updated_by=user[:80], **values)
            s.add(c)
            s.flush()
            s.add(CaseEvent(case_id=c.id, client_id=client_id, on=values.get("order_date") or date.today(),
                            kind="note", text=f"Case opened at stage: {STAGES[c.stage]}", user=user[:80]))
            audit(s, "CASE_ADD", "litigation_cases", c.id, {"title": c.title, "stage": c.stage}, user, client_id)
            s.expunge(c)
        return c

    def from_notice(self, notice_id: int, user: str) -> LitigationCase:
        with self.db.session() as s:
            n = s.get(GstNotice, notice_id)
            if n is None:
                raise ServiceError(f"Notice #{notice_id} not found")
            if s.scalar(select(LitigationCase.id).where(LitigationCase.notice_id == notice_id)):
                raise ServiceError("A case already exists for this notice")
            data = dict(client_id=n.client_id, form=n.form, reference=n.reference, notice_date=n.notice_date,
                        period_from=n.period_from, period_to=n.period_to, amount=n.amount)
        c = self.add(data["client_id"], user, title=f"{data['form']} {data['reference']}".strip(), stage="SCN",
                     form=data["form"], reference=data["reference"], period_from=data["period_from"],
                     period_to=data["period_to"], tax=data["amount"] or 0, order_date=None)
        with self.db.session() as s:
            row = s.get(LitigationCase, c.id)
            row.notice_id = notice_id
        c.notice_id = notice_id
        return c

    def update(self, case_id: int, user: str, event: str | None = None, **values) -> LitigationCase:
        """Change the case; ``event`` adds a line to its history (stage and status changes are recorded too)."""
        values = self._clean(values)
        with self.db.session() as s:
            c = s.get(LitigationCase, case_id)
            if c is None:
                raise ServiceError(f"Case #{case_id} not found")
            before = {k: getattr(c, k) for k in values}
            for k, v in values.items():
                setattr(c, k, v)
            c.updated_by = user[:80]
            notes = []
            if "stage" in values and before["stage"] != values["stage"]:
                notes.append(f"Stage: {STAGES[values['stage']]}")
            if "status" in values and before["status"] != values["status"]:
                notes.append(f"Status: {values['status']}")
            if event:
                notes.append(event)
            for t in notes:
                s.add(CaseEvent(case_id=c.id, client_id=c.client_id, on=date.today(), kind="note", text=t,
                                user=user[:80]))
            audit(s, "CASE_UPDATE", "litigation_cases", c.id, {"before": before, "after": values}, user, c.client_id)
            s.flush()
            s.expunge(c)
        return c

    def add_event(self, case_id: int, on: date, kind: str, text: str, user: str) -> CaseEvent:
        if not text.strip():
            raise ServiceError("Describe the event")
        with self.db.session() as s:
            c = s.get(LitigationCase, case_id)
            if c is None:
                raise ServiceError(f"Case #{case_id} not found")
            e = CaseEvent(case_id=case_id, client_id=c.client_id, on=on, kind=kind[:12], text=text.strip(),
                          user=user[:80])
            s.add(e)
            if kind == "hearing" and (c.hearing_date is None or on >= c.hearing_date):
                c.hearing_date = on  # the latest hearing fixed
            s.flush()
            s.expunge(e)
        return e

    def delete(self, case_id: int, user: str) -> None:
        with self.db.session() as s:
            c = s.get(LitigationCase, case_id)
            if c is None:
                raise ServiceError(f"Case #{case_id} not found")
            for e in s.scalars(select(CaseEvent).where(CaseEvent.case_id == case_id)):
                s.delete(e)
            audit(s, "CASE_DELETE", "litigation_cases", case_id, {"title": c.title}, user, c.client_id)
            s.delete(c)

    def cases(self, client_id: int | None = None, open_only: bool = False) -> list[LitigationCase]:
        with self.db.session() as s:
            q = select(LitigationCase).order_by(LitigationCase.id.desc())
            if client_id:
                q = q.where(LitigationCase.client_id == client_id)
            if open_only:
                q = q.where(LitigationCase.status == "OPEN")
            return list(s.scalars(q))

    def events(self, case_id: int) -> list[CaseEvent]:
        with self.db.session() as s:
            return list(s.scalars(select(CaseEvent).where(CaseEvent.case_id == case_id)
                                  .order_by(CaseEvent.on, CaseEvent.id)))

    # ----------------------------------------------------------- workings
    @staticmethod
    def working(c: LitigationCase) -> dict:
        """Demand, next step, its last date and the pre-deposit needed."""
        step = next_step(c.stage)
        lim = limitation(step, c.order_date) if step and c.order_date and not c.appeal_filed_on else None
        dep, basis = pre_deposit(step or "", c.tax, c.tax_admitted, c.penalty) if step in ("APPEAL", "TRIBUNAL") \
            else (ZERO, "")
        return {"demand": c.tax + c.interest + c.penalty, "next_step": step, "limitation": lim,
                "pre_deposit": dep, "pre_deposit_basis": basis,
                "pre_deposit_due": max(dep - c.pre_deposit_paid, ZERO) if step else ZERO}

    def alerts(self, client_id: int | None = None, today: date | None = None, days: int = 15) -> list[Alert]:
        today = today or date.today()
        with self.db.session() as s:
            names = dict(s.execute(select(Client.id, Client.name)).all())
        out = []
        for c in self.cases(client_id, open_only=True):
            w = self.working(c)
            lim = w["limitation"]
            if lim is not None and (lim.last_date - today).days <= days:
                late = lim.last_date < today
                out.append(Alert(c, names.get(c.client_id, ""), lim.last_date, "limitation",
                                 (f"time to file passed on {lim.last_date:%d-%m-%Y}" + (
                                     f" – can be condoned up to {lim.condonable_to:%d-%m-%Y}" if lim.condonable_to
                                     else "")) if late else
                                 f"file the {'appeal' if w['next_step'] == 'APPEAL' else w['next_step'].lower()} by "
                                 f"{lim.last_date:%d-%m-%Y}"))
            if c.hearing_date and 0 <= (c.hearing_date - today).days <= days:
                out.append(Alert(c, names.get(c.client_id, ""), c.hearing_date, "hearing",
                                 f"personal hearing on {c.hearing_date:%d-%m-%Y}"))
            if w["pre_deposit_due"] > 0 and lim is not None:
                out.append(Alert(c, names.get(c.client_id, ""), lim.last_date, "pre-deposit",
                                 f"pre-deposit ₹{w['pre_deposit_due']:,.2f} to pay (DRC-03) before filing"))
        return sorted(out, key=lambda a: a.on)

    def make_tasks(self, user: str, today: date | None = None) -> int:
        """Staff tasks for the coming hearings and appeal time limits (once each)."""
        from ..db.models import StaffTask

        n = 0
        with self.db.session() as s:
            have = set(s.scalars(select(StaffTask.auto_key).where(StaffTask.auto_key.is_not(None))))
            staff = dict(s.execute(select(Client.id, Client.staff)).all())
            for a in self.alerts(today=today, days=30):
                key = f"case{a.case.id}:{a.kind}:{a.on}"
                if key in have:
                    continue
                s.add(StaffTask(client_id=a.case.client_id, title=f"{a.case.title}: {a.text}"[:200],
                                assignee=staff.get(a.case.client_id) or "", due_date=a.on, auto_key=key[:80],
                                created_by=user[:80]))
                have.add(key)
                n += 1
        return n

    def export_xlsx(self, path: str | Path, client_id: int | None = None) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        with self.db.session() as s:
            names = dict(s.execute(select(Client.id, Client.name)).all())
        wb = Workbook()
        ws = wb.active
        ws.title = "Cases"
        head = ["Client", "Case", "Stage", "Form", "Reference", "Order date", "Period", "Tax", "Interest", "Penalty",
                "Demand", "Next step by", "Pre-deposit", "Paid", "Hearing", "Status", "Remarks"]
        ws.append(head)
        for cc in ws[1]:
            cc.font = Font(bold=True)
        for c in self.cases(client_id):
            w = self.working(c)
            ws.append([names.get(c.client_id, ""), c.title, STAGES.get(c.stage, c.stage), c.form, c.reference,
                       c.order_date, f"{c.period_from}..{c.period_to}", float(c.tax), float(c.interest),
                       float(c.penalty), float(w["demand"]), w["limitation"].last_date if w["limitation"] else None,
                       float(w["pre_deposit"]), float(c.pre_deposit_paid), c.hearing_date, c.status, c.remarks])
        path = Path(path)
        wb.save(path)
        return path
