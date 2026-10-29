"""Reconciliation runs: load scope from the database, run the engine, persist,
reload for reporting, and record exception updates with an audit trail."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import and_, insert, select

from ..core.models import (
    PAIRED_CATEGORIES, Category, ExceptionStatus, ReconLine, ReconSettings, Source, fy_of,
)
from ..db.database import Database
from ..db.models import Client, Invoice, ReconLineRow, ReconRun, SourceFile, utcnow
from ..engine.matcher import CancelToken, ReconResult, reconcile
from ..engine.summary import dashboard
from ..importers.parsing import parse_period
from .common import ServiceError, audit, dumps, invoice_to_record

BATCH = 2000


def months_between(p_from: str, p_to: str) -> list[str]:
    y, m = int(p_from[:4]), int(p_from[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= p_to:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fy_periods(fy: str) -> tuple[str, str]:
    start = int(fy[:4])
    return f"{start}-04", f"{start + 1}-03"


@dataclass
class RunContext:
    run: ReconRun
    client: Client
    result: ReconResult
    source_files: list[SourceFile] = field(default_factory=list)


class ReconciliationService:
    def __init__(self, db: Database):
        self.db = db

    def run(self, client_id: int, period_from: str, period_to: str | None = None,
            settings: ReconSettings | None = None, compare_with: Source = Source.GSTR2B, user: str | None = None,
            progress=None, cancel: CancelToken | None = None) -> int:
        settings = settings or ReconSettings()
        p_from = parse_period(period_from)
        p_to = parse_period(period_to or period_from)
        if not p_from or not p_to or p_to < p_from:
            raise ServiceError(f"Invalid reconciliation period {period_from} – {period_to}")
        period_start = date(int(p_from[:4]), int(p_from[5:]), 1)
        progress = progress or (lambda pct, msg: None)
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            files = {f.id: f.file_name for f in s.scalars(select(SourceFile).where(SourceFile.client_id == client_id))}
            progress(2, "Loading documents")
            file_of: dict[int, int] = {}

            def load(source: Source, prior: bool = False):
                q = select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == source.value)
                q = q.where(Invoice.period < p_from) if prior else q.where(Invoice.period.between(p_from, p_to))
                out = []
                for r in s.scalars(q):
                    file_of[r.id] = r.source_file_id
                    out.append(invoice_to_record(r, files.get(r.source_file_id, ""), prior))
                return out

            books = load(Source.BOOKS)
            g2b = load(compare_with)
            if not books and not g2b:
                raise ServiceError(f"No books or {compare_with.value} documents imported for {p_from} to {p_to}")
            # Earlier-period books not yet paired in a reconciliation of an earlier period.
            consumed = set(s.scalars(
                select(ReconLineRow.books_invoice_id).join(ReconRun, ReconRun.id == ReconLineRow.run_id).where(
                    ReconRun.client_id == client_id, ReconRun.period_to < p_from,
                    ReconLineRow.books_invoice_id.is_not(None), ReconLineRow.gstr2b_invoice_id.is_not(None),
                    ReconLineRow.category.in_([c.value for c in PAIRED_CATEGORIES]))))
            prior = [r for r in load(Source.BOOKS, prior=True) if r.db_id not in consumed]

            def engine_progress(pct, msg):
                progress(5 + int(pct * 0.8), msg)

            result = reconcile(books, g2b, settings, prior_books=prior, period_start=period_start,
                               progress=engine_progress, cancel=cancel)
            if cancel:
                cancel.check()
            progress(87, "Saving results")
            file_ids = sorted({file_of[r.db_id] for ln in result.lines for r in (ln.books, ln.gstr2b)
                               if r is not None})
            run = ReconRun(
                client_id=client_id, financial_year=fy_of(period_start), period_from=p_from, period_to=p_to,
                comparison=f"BOOKS_VS_{compare_with.value}", settings_json=dumps(settings.to_dict()),
                fingerprint=result.fingerprint, engine_version=result.engine_version,
                summary_json=dumps(dashboard(result.lines)), source_file_ids=json.dumps(file_ids),
                created_by=user or "", status="COMPLETED",
            )
            s.add(run)
            s.flush()
            self._carry_forward(s, client_id, p_from, p_to, result.lines, exclude_run=run.id)
            rows = [self._line_row(run.id, ln) for ln in result.lines]
            for i in range(0, len(rows), BATCH):
                if cancel:
                    cancel.check()
                s.execute(insert(ReconLineRow), rows[i:i + BATCH])
            run.finished_at = utcnow()
            audit(s, "RECONCILE", "recon_run", run.id, {
                "period_from": p_from, "period_to": p_to, "settings": settings.to_dict(),
                "fingerprint": result.fingerprint, "lines": len(result.lines),
            }, user, client_id)
            run_id = run.id
        progress(100, "Reconciliation saved")
        return run_id

    @staticmethod
    def _line_row(run_id: int, ln: ReconLine) -> dict:
        return {
            "run_id": run_id, "line_no": ln.line_no, "category": ln.category.value,
            "books_invoice_id": ln.books.db_id if ln.books else None,
            "gstr2b_invoice_id": ln.gstr2b.db_id if ln.gstr2b else None,
            "match_level": ln.match_level, "confidence": ln.confidence,
            "flags_json": json.dumps(ln.flags), "reasons_json": json.dumps(ln.reasons, ensure_ascii=False),
            "candidates_json": json.dumps(ln.candidates), "date_diff_days": ln.date_diff_days,
            "status": ln.status.value, "remarks": ln.remarks, "assigned_to": ln.assigned_to,
            "action_date": ln.action_date, "updated_at": utcnow(),
        }

    @staticmethod
    def _carry_forward(s, client_id: int, p_from: str, p_to: str, lines: list[ReconLine], exclude_run: int) -> None:
        """Copy review status/remarks from the latest earlier run of the same period
        onto lines that pair the same documents in the same category."""
        prev = s.scalar(select(ReconRun).where(
            ReconRun.client_id == client_id, ReconRun.period_from == p_from, ReconRun.period_to == p_to,
            ReconRun.id != exclude_run)
            .order_by(ReconRun.id.desc()).limit(1))
        if prev is None:
            return
        old = {(r.books_invoice_id, r.gstr2b_invoice_id, r.category): r
               for r in s.scalars(select(ReconLineRow).where(ReconLineRow.run_id == prev.id))}
        for ln in lines:
            key = (ln.books.db_id if ln.books else None, ln.gstr2b.db_id if ln.gstr2b else None, ln.category.value)
            o = old.get(key)
            if o is not None and (o.remarks or o.assigned_to or o.status != ln.status.value):
                ln.status = ExceptionStatus(o.status)
                ln.remarks, ln.assigned_to, ln.action_date = o.remarks, o.assigned_to, o.action_date

    # ------------------------------------------------------------- loading
    def load(self, run_id: int) -> RunContext:
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            if run is None:
                raise ServiceError(f"Reconciliation run {run_id} not found")
            client = s.get(Client, run.client_id)
            line_rows = list(s.scalars(select(ReconLineRow).where(ReconLineRow.run_id == run_id)
                                       .order_by(ReconLineRow.line_no)))
            ids = {i for r in line_rows for i in (r.books_invoice_id, r.gstr2b_invoice_id) if i}
            invoices = {}
            id_list = sorted(ids)
            for i in range(0, len(id_list), 900):
                for inv in s.scalars(select(Invoice).where(Invoice.id.in_(id_list[i:i + 900]))):
                    invoices[inv.id] = inv
            file_ids = json.loads(run.source_file_ids or "[]")
            files = list(s.scalars(select(SourceFile).where(SourceFile.id.in_(file_ids)).order_by(SourceFile.id)))
            names = {f.id: f.file_name for f in files}
            records = {}
            for inv_id, inv in invoices.items():
                prior = inv.source_type == Source.BOOKS.value and inv.period < run.period_from
                records[inv_id] = invoice_to_record(inv, names.get(inv.source_file_id, ""), prior)
            lines = []
            for r in line_rows:
                lines.append(ReconLine(
                    line_no=r.line_no, category=Category(r.category),
                    books=records.get(r.books_invoice_id), gstr2b=records.get(r.gstr2b_invoice_id),
                    match_level=r.match_level, confidence=r.confidence, flags=json.loads(r.flags_json),
                    reasons=json.loads(r.reasons_json), candidates=json.loads(r.candidates_json),
                    date_diff_days=r.date_diff_days, status=ExceptionStatus(r.status), remarks=r.remarks,
                    assigned_to=r.assigned_to, action_date=r.action_date, db_id=r.id,
                ))
        settings = ReconSettings.from_dict(json.loads(run.settings_json))
        books = [ln.books for ln in lines if ln.books is not None and not ln.books.is_prior_period]
        g2b = [ln.gstr2b for ln in lines if ln.gstr2b is not None]
        result = ReconResult(lines=lines, settings=settings, books=books, gstr2b=g2b,
                             period_start=date(int(run.period_from[:4]), int(run.period_from[5:]), 1),
                             fingerprint=run.fingerprint, engine_version=run.engine_version)
        return RunContext(run, client, result, files)

    def list_runs(self, client_id: int) -> list[ReconRun]:
        with self.db.session() as s:
            return list(s.scalars(select(ReconRun).where(ReconRun.client_id == client_id)
                                  .order_by(ReconRun.id.desc())))

    # ---------------------------------------------------- exception updates
    def update_line(self, run_id: int, line_no: int, user: str | None = None, *, status: str | None = None,
                    remarks: str | None = None, assigned_to: str | None = None,
                    action_date: date | None = None) -> None:
        with self.db.session() as s:
            row = s.scalar(select(ReconLineRow).where(and_(ReconLineRow.run_id == run_id,
                                                           ReconLineRow.line_no == line_no)))
            if row is None:
                raise ServiceError(f"Line {line_no} not found in run {run_id}")
            changes = {}
            if status is not None:
                try:
                    status_value = ExceptionStatus(status).value
                except ValueError:
                    raise ServiceError(f"Unknown status '{status}'. Use one of: "
                                       + ", ".join(e.value for e in ExceptionStatus)) from None
                changes["status"] = status_value
            if remarks is not None:
                changes["remarks"] = remarks
            if assigned_to is not None:
                changes["assigned_to"] = assigned_to
            if action_date is not None:
                changes["action_date"] = action_date
            before = {k: getattr(row, k) for k in changes}
            for k, v in changes.items():
                setattr(row, k, v)
            run = s.get(ReconRun, run_id)
            audit(s, "UPDATE", "recon_line", f"{run_id}:{line_no}", {"before": before, "after": changes}, user,
                  run.client_id)


def default_report_name(client: Client, run: ReconRun, ext: str) -> str:
    return f"FINTAXPRO_GSTRecon_{client.gstin}_FY{run.financial_year}_{run.period_from}_to_{run.period_to}_run{run.id}.{ext}"


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
