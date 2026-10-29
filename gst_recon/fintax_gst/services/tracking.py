"""Cross-period tracking: open items, document history, financial-year overview."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ..core.models import CLOSED_STATUSES, PAIRED_CATEGORIES, ExceptionStatus
from ..db.database import Database
from ..db.models import Invoice, ReconLineRow, ReconRun
from .reconciliation import fy_periods, months_between

_PAIRED = {c.value for c in PAIRED_CATEGORIES}
_CLOSED = {s.value for s in CLOSED_STATUSES}


@dataclass
class OpenItem:
    invoice_id: int
    source: str
    supplier_gstin: str
    supplier_name: str
    doc_type: str
    invoice_no: str
    invoice_date: date
    period: str
    itc: Decimal
    last_run_id: int | None
    last_line_no: int | None
    last_category: str
    status: str
    remarks: str
    runs_seen: int

    @property
    def age_days(self) -> int:
        return (date.today() - self.invoice_date).days


class TrackingService:
    def __init__(self, db: Database):
        self.db = db

    def _latest_lines(self, s, client_id: int):
        lt, rt = ReconLineRow.__table__, ReconRun.__table__
        q = (select(lt.c.run_id, lt.c.line_no, lt.c.books_invoice_id, lt.c.gstr2b_invoice_id, lt.c.category,
                    lt.c.status, lt.c.remarks)
             .join(rt, rt.c.id == lt.c.run_id).where(rt.c.client_id == client_id)
             .order_by(lt.c.run_id, lt.c.line_no))
        latest: dict[int, tuple] = {}
        seen: dict[int, int] = {}
        for r in s.execute(q):
            for doc in (r.books_invoice_id, r.gstr2b_invoice_id):
                if doc:
                    latest[doc] = r
                    seen[doc] = seen.get(doc, 0) + 1
        return latest, seen

    def open_items(self, client_id: int, include_unreconciled: bool = True) -> list[OpenItem]:
        """Documents not yet resolved, judged by the most recent run that contained them.

        A document is closed when its latest line pairs it with a counterpart or the
        reviewer closed the line. Books documents never reconciled are listed as such.
        Each document appears once, whatever the number of runs it was part of."""
        out = []
        it = Invoice.__table__
        with self.db.session() as s:
            latest, seen = self._latest_lines(s, client_id)
            q = (select(it.c.id, it.c.source_type, it.c.supplier_gstin, it.c.supplier_name, it.c.doc_type,
                        it.c.invoice_no, it.c.invoice_date, it.c.period, it.c.igst, it.c.cgst, it.c.sgst, it.c.cess)
                 .where(it.c.client_id == client_id).order_by(it.c.supplier_gstin, it.c.invoice_date, it.c.id))
            for inv in s.execute(q):
                line = latest.get(inv.id)
                if line is None:
                    if not include_unreconciled:
                        continue
                    category, status, remarks = "Not reconciled yet", ExceptionStatus.PENDING_REVIEW.value, ""
                else:
                    paired = line.category in _PAIRED and line.books_invoice_id and line.gstr2b_invoice_id
                    if paired or line.status in _CLOSED:
                        continue
                    category, status, remarks = line.category, line.status, line.remarks
                sign = -1 if inv.doc_type == "CRN" else 1
                out.append(OpenItem(
                    inv.id, inv.source_type, inv.supplier_gstin, inv.supplier_name, inv.doc_type, inv.invoice_no,
                    inv.invoice_date, inv.period, (inv.igst + inv.cgst + inv.sgst + inv.cess) * sign,
                    line.run_id if line else None, line.line_no if line else None, category, status, remarks,
                    seen.get(inv.id, 0),
                ))
        return out

    def document_history(self, invoice_id: int) -> list[dict]:
        with self.db.session() as s:
            q = (select(ReconLineRow, ReconRun).join(ReconRun, ReconRun.id == ReconLineRow.run_id)
                 .where((ReconLineRow.books_invoice_id == invoice_id) | (ReconLineRow.gstr2b_invoice_id == invoice_id))
                 .order_by(ReconRun.id))
            return [{"run_id": run.id, "period": f"{run.period_from}..{run.period_to}", "line_no": ln.line_no,
                     "category": ln.category, "status": ln.status, "remarks": ln.remarks, "run_at": run.started_at}
                    for ln, run in s.execute(q)]

    def fy_overview(self, client_id: int, fy: str) -> list[dict]:
        """Latest single-month run of each month of the financial year."""
        p_from, p_to = fy_periods(fy)
        months = months_between(p_from, p_to)
        with self.db.session() as s:
            runs = s.scalars(select(ReconRun).where(ReconRun.client_id == client_id,
                                                    ReconRun.period_from == ReconRun.period_to,
                                                    ReconRun.period_from.in_(months)).order_by(ReconRun.id)).all()
        latest = {r.period_from: r for r in runs}
        rows = []
        for m in months:
            r = latest.get(m)
            rows.append({"month": m, "run_id": r.id if r else None,
                         "summary": json.loads(r.summary_json) if r else None})
        return rows

    def latest_run(self, client_id: int, fy: str | None = None) -> ReconRun | None:
        with self.db.session() as s:
            q = select(ReconRun).where(ReconRun.client_id == client_id)
            if fy:
                q = q.where(ReconRun.financial_year == fy)
            return s.scalar(q.order_by(ReconRun.id.desc()).limit(1))

    def scope(self, client_id: int, p_from: str, p_to: str) -> dict:
        """Documents and source files that fall in a reconciliation period."""
        from sqlalchemy import func

        from ..db.models import SourceFile

        with self.db.session() as s:
            counts = dict(s.execute(
                select(Invoice.source_type, func.count()).where(
                    Invoice.client_id == client_id, Invoice.period.between(p_from, p_to))
                .group_by(Invoice.source_type)).all())
            per_file = dict(s.execute(
                select(Invoice.source_file_id, func.count()).where(
                    Invoice.client_id == client_id, Invoice.period.between(p_from, p_to))
                .group_by(Invoice.source_file_id)).all())
            files = list(s.scalars(select(SourceFile).where(SourceFile.client_id == client_id)
                                   .order_by(SourceFile.id)))
        in_scope = [(f, per_file.get(f.id, 0)) for f in files
                    if per_file.get(f.id) or (f.period and p_from <= f.period <= p_to)]
        return {"books": counts.get("BOOKS", 0), "gstr2b": counts.get("GSTR2B", 0),
                "gstr2a": counts.get("GSTR2A", 0), "files": in_scope}
