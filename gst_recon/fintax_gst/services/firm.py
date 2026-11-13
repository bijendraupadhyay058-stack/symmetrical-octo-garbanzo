"""Firm work dashboard: where every client stands for one month, what is due, and who has what to do.

Read-only. For the chosen tax period it combines, per active client:

* the data imported (purchase register, GSTR-2B, sales register, GSTR-1);
* the latest reconciliations of the month and their open review lines;
* the returns due (GSTR-1 / GSTR-3B, or IFF / PMT-06 for QRMP) and whether a filing date is recorded;
* open GST notices and supplier follow-ups that are due;

and derives a **stage** and the **next step**. Deadlines (returns, notice replies, review action dates) and
the workload of each staff member are listed across clients.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from ..compliance.calendar import due_items
from ..core.models import CLOSED_STATUSES
from ..db.database import Database
from ..db.models import (
    AuditLog, Client, GstNotice, Invoice, ReconLineRow, ReconRun, ReturnFiling, SourceFile, Vendor,
)
from ..importers.parsing import parse_period
from .calendar import CalendarService
from .common import ServiceError

#: Stages in the order work progresses; the dashboard sorts clients by it.
STAGES = ("Awaiting data", "Data incomplete", "Ready to reconcile", "Under review", "Reviewed – file returns",
          "Done")
UNASSIGNED = "(not assigned)"
_CLOSED = {s.value for s in CLOSED_STATUSES}


@dataclass
class ReturnDue:
    return_type: str
    due: date
    filed_on: date | None
    optional: bool = False

    def state(self, today: date) -> str:
        if self.filed_on:
            return "filed late" if self.filed_on > self.due else "filed"
        if self.due < today:
            return "overdue"
        return "due soon" if (self.due - today).days <= 7 else "upcoming"


@dataclass
class ClientWork:
    client_id: int
    name: str
    gstin: str
    staff: str
    frequency: str
    purchase_docs: int = 0
    gstr2b_docs: int = 0
    sales_docs: int = 0
    gstr1_docs: int = 0
    inward_run_id: int | None = None
    inward_pending: int = 0
    itc_at_risk: Decimal = Decimal(0)
    outward_run_id: int | None = None
    outward_pending: int = 0
    rerun_needed: bool = False  # data imported after the latest reconciliation
    pending_by_person: dict[str, int] = field(default_factory=dict)
    overdue_actions: int = 0  # open review lines whose action date has passed
    overdue_by_person: dict[str, int] = field(default_factory=dict)
    returns: list[ReturnDue] = field(default_factory=list)
    notices_open: int = 0
    next_reply_due: date | None = None
    followups_due: int = 0
    last_activity: datetime | None = None
    stage: str = STAGES[0]
    next_step: str = ""

    @property
    def pending(self) -> int:
        return self.inward_pending + self.outward_pending

    @property
    def stage_no(self) -> int:
        return STAGES.index(self.stage)


@dataclass
class Deadline:
    on: date
    client_id: int
    client: str
    staff: str
    item: str
    state: str  # overdue, due soon, upcoming


@dataclass
class StaffLoad:
    person: str
    clients: int = 0  # clients this person is responsible for
    clients_open: int = 0  # of those, not yet done
    pending_lines: int = 0  # open review lines assigned to the person (latest runs of the month)
    overdue_actions: int = 0


@dataclass
class FirmWork:
    period: str
    today: date
    clients: list[ClientWork]
    deadlines: list[Deadline]
    staff: list[StaffLoad]

    def count(self, stage: str) -> int:
        return sum(1 for c in self.clients if c.stage == stage)


class FirmService:
    def __init__(self, db: Database):
        self.db = db

    def work(self, period: str, today: date | None = None, staff: str | None = None,
             horizon_days: int = 15) -> FirmWork:
        """The month's work for all active clients (or those of one staff member)."""
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        today = today or date.today()
        overrides = CalendarService(self.db).overrides()
        with self.db.session() as s:
            clients = list(s.scalars(select(Client).where(Client.active.is_(True)).order_by(Client.name)))
            if staff is not None:
                clients = [c for c in clients if (c.staff or UNASSIGNED) == staff]
            ids = [c.id for c in clients]
            if not ids:
                return FirmWork(p, today, [], [], [])
            counts = {(cid, src): n for cid, src, n in s.execute(
                select(Invoice.client_id, Invoice.source_type, func.count())
                .where(Invoice.client_id.in_(ids), Invoice.period == p)
                .group_by(Invoice.client_id, Invoice.source_type))}
            last_import = {(cid, src): at for cid, src, at in s.execute(
                select(Invoice.client_id, Invoice.source_type, func.max(SourceFile.imported_at))
                .join(SourceFile, SourceFile.id == Invoice.source_file_id)
                .where(Invoice.client_id.in_(ids), Invoice.period == p)
                .group_by(Invoice.client_id, Invoice.source_type))}
            latest: dict[tuple[int, str], ReconRun] = {}
            for r in s.scalars(select(ReconRun).where(ReconRun.client_id.in_(ids), ReconRun.period_from == p,
                                                      ReconRun.period_to == p).order_by(ReconRun.id)):
                latest[(r.client_id, r.comparison)] = r  # the newest run of each comparison wins
            run_ids = [r.id for r in latest.values()]
            lines = list(s.execute(
                select(ReconLineRow.run_id, ReconLineRow.assigned_to, ReconLineRow.action_date, func.count())
                .where(ReconLineRow.run_id.in_(run_ids), ReconLineRow.status.not_in(_CLOSED))
                .group_by(ReconLineRow.run_id, ReconLineRow.assigned_to, ReconLineRow.action_date))) if run_ids else []
            filings = {(f.client_id, f.return_type): f.filed_on for f in s.scalars(
                select(ReturnFiling).where(ReturnFiling.client_id.in_(ids), ReturnFiling.period == p))}
            notices = list(s.scalars(select(GstNotice).where(GstNotice.client_id.in_(ids),
                                                             GstNotice.status == "OPEN")))
            followups = dict(s.execute(
                select(Vendor.client_id, func.count()).where(
                    Vendor.client_id.in_(ids), Vendor.next_followup.is_not(None), Vendor.next_followup <= today)
                .group_by(Vendor.client_id)).all())
            activity = dict(s.execute(select(AuditLog.client_id, func.max(AuditLog.at))
                                      .where(AuditLog.client_id.in_(ids)).group_by(AuditLog.client_id)).all())
            run_client = {r.id: r for r in latest.values()}
            rows: dict[int, ClientWork] = {}
            for c in clients:
                w = ClientWork(c.id, c.name, c.gstin, c.staff or "", c.return_frequency or "Monthly",
                               counts.get((c.id, "BOOKS"), 0), counts.get((c.id, "GSTR2B"), 0),
                               counts.get((c.id, "SALES"), 0), counts.get((c.id, "GSTR1"), 0),
                               followups_due=followups.get(c.id, 0), last_activity=activity.get(c.id))
                inward, outward = latest.get((c.id, "BOOKS_VS_GSTR2B")), latest.get((c.id, "SALES_VS_GSTR1"))
                if inward:
                    w.inward_run_id = inward.id
                    w.itc_at_risk = Decimal(str(_summary(inward).get("itc_at_risk", 0)))
                if outward:
                    w.outward_run_id = outward.id
                for comparison, run in ((k[1], v) for k, v in latest.items() if k[0] == c.id):
                    left, right = comparison.split("_VS_")
                    newest = max((last_import.get((c.id, x)) for x in (left, right) if (c.id, x) in last_import),
                                 default=None)
                    if newest and newest > run.started_at:
                        w.rerun_needed = True
                w.returns = [ReturnDue(d.return_type, d.due, filings.get((c.id, d.return_type)), d.optional)
                             for d in due_items(p, w.frequency, c.state_code, overrides)]
                rows[c.id] = w
            for run_id, assigned, action_date, n in lines:
                run = run_client[run_id]
                w = rows[run.client_id]
                if run.comparison == "BOOKS_VS_GSTR2B":
                    w.inward_pending += n
                elif run.comparison == "SALES_VS_GSTR1":
                    w.outward_pending += n
                else:
                    continue  # e-invoice / e-way bill checks are not part of the month's sign-off
                person = assigned or UNASSIGNED
                w.pending_by_person[person] = w.pending_by_person.get(person, 0) + n
                if action_date and action_date < today:
                    w.overdue_actions += n
                    w.overdue_by_person[person] = w.overdue_by_person.get(person, 0) + n
            for nt in notices:
                w = rows[nt.client_id]
                w.notices_open += 1
                if nt.reply_due and (w.next_reply_due is None or nt.reply_due < w.next_reply_due):
                    w.next_reply_due = nt.reply_due
            notice_rows = [(nt.client_id, nt.form, nt.reference, nt.reply_due) for nt in notices if nt.reply_due]
        for w in rows.values():
            w.stage, w.next_step = _stage(w, today)
        work = sorted(rows.values(), key=lambda w: (w.stage_no, w.name.lower()))
        return FirmWork(p, today, work, _deadlines(rows, notice_rows, today, horizon_days), _staff(work, today))

    def staff_names(self) -> list[str]:
        with self.db.session() as s:
            names = {n for n in s.scalars(select(Client.staff).where(Client.active.is_(True))) if n}
        return sorted(names)


def _summary(run: ReconRun) -> dict:
    return json.loads(run.summary_json or "{}")


def _stage(w: ClientWork, today: date) -> tuple[str, str]:
    has_in = w.purchase_docs or w.gstr2b_docs
    has_out = w.sales_docs or w.gstr1_docs
    main = [r for r in w.returns if not r.optional]
    late = [r for r in main if r.state(today) == "overdue"]
    warn = f" {', '.join(r.return_type for r in late)} overdue." if late else ""
    if not has_in and not has_out:
        return STAGES[0], "Import the purchase register and GSTR-2B." + warn
    missing = []
    if w.purchase_docs and not w.gstr2b_docs:
        missing.append("GSTR-2B")
    if w.gstr2b_docs and not w.purchase_docs:
        missing.append("purchase register")
    if w.gstr1_docs and not w.sales_docs:
        missing.append("sales register")
    if missing:
        return STAGES[1], f"Import the {' and '.join(missing)}." + warn
    to_run = []
    if w.purchase_docs and w.inward_run_id is None:
        to_run.append("purchases vs GSTR-2B")
    if w.sales_docs and w.gstr1_docs and w.outward_run_id is None:
        to_run.append("sales vs GSTR-1")
    if to_run or w.rerun_needed:
        what = "Reconcile " + " and ".join(to_run) if to_run else "New data since the last reconciliation – " \
                                                                   "reconcile again"
        return STAGES[2], what + "." + warn
    if w.pending:
        who = ", ".join(f"{p} {n}" for p, n in sorted(w.pending_by_person.items()))
        extra = f" {w.overdue_actions} past their action date." if w.overdue_actions else ""
        return STAGES[3], f"Review {w.pending} open line(s) ({who}).{extra}" + warn
    unfiled = [r for r in main if not r.filed_on]
    if unfiled:
        nxt = min(unfiled, key=lambda r: r.due)
        return STAGES[4], f"File {', '.join(r.return_type for r in unfiled)} – {nxt.return_type} due " \
                          f"{nxt.due:%d-%m-%Y}." + warn
    return STAGES[5], "All returns of the month filed." if main else "Nothing due for this month."


def _deadlines(rows: dict[int, ClientWork], notices: list, today: date, horizon: int) -> list[Deadline]:
    out = []

    def add(on: date, w: ClientWork, item: str):
        days = (on - today).days
        if days <= horizon:
            out.append(Deadline(on, w.client_id, w.name, w.staff, item,
                                "overdue" if days < 0 else "due soon" if days <= 7 else "upcoming"))

    for w in rows.values():
        for r in w.returns:
            if not r.filed_on and not r.optional:
                add(r.due, w, f"{r.return_type} not filed")
    for cid, form, ref, due in notices:
        add(due, rows[cid], f"Reply to {form}" + (f" {ref}" if ref else ""))
    return sorted(out, key=lambda d: (d.on, d.client.lower()))


def _staff(work: list[ClientWork], today: date) -> list[StaffLoad]:
    loads: dict[str, StaffLoad] = defaultdict(lambda: StaffLoad(""))
    for w in work:
        resp = loads[w.staff or UNASSIGNED]
        resp.clients += 1
        resp.clients_open += w.stage != STAGES[-1]
        for person, n in w.pending_by_person.items():
            loads[person].pending_lines += n
        for person, n in w.overdue_by_person.items():
            loads[person].overdue_actions += n
    out = []
    for person, load in loads.items():
        load.person = person
        out.append(load)
    return sorted(out, key=lambda x: (x.person == UNASSIGNED, -x.pending_lines, x.person.lower()))


def export_xlsx(work: FirmWork, path: str | Path) -> Path:
    """The dashboard as an Excel workbook: clients, deadlines and staff workload."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    head = PatternFill("solid", fgColor="1F3864")
    wb = Workbook()
    sheets = [
        ("Clients", ["Client", "GSTIN", "Staff", "Stage", "Next step", "Open lines", "ITC at risk",
                     *[f"Return {i}" for i in (1, 2)], "Open notices", "Supplier follow-ups due"],
         [[c.name, c.gstin, c.staff, c.stage, c.next_step, c.pending, float(c.itc_at_risk),
           *[f"{r.return_type}: {r.state(work.today)}"
             + (f" on {r.filed_on:%d-%m-%Y}" if r.filed_on else f" (due {r.due:%d-%m-%Y})") for r in c.returns][:2],
           *[""] * (2 - min(len(c.returns), 2)), c.notices_open, c.followups_due] for c in work.clients]),
        ("Deadlines", ["Date", "Client", "Staff", "Item", "State"],
         [[d.on, d.client, d.staff, d.item, d.state] for d in work.deadlines]),
        ("Staff", ["Staff", "Clients", "Not done", "Open lines assigned", "Past action date"],
         [[s.person, s.clients, s.clients_open, s.pending_lines, s.overdue_actions] for s in work.staff]),
    ]
    for i, (title, headers, rows) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append([f"Firm work – {work.period} (as on {work.today:%d-%m-%Y})"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append(headers)
        for cell in ws[2]:
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), head
        for r in rows:
            ws.append(r)
        for col in ws.columns:
            letter = col[0].column_letter
            ws.column_dimensions[letter].width = min(60, max(10, *(len(str(c.value or "")) + 2 for c in col[1:])))
            if title == "Deadlines" and letter == "A":
                for c in col[2:]:
                    c.number_format = "DD-MM-YYYY"
        ws.freeze_panes = "A3"
    out = Path(path)
    wb.save(out)
    return out
