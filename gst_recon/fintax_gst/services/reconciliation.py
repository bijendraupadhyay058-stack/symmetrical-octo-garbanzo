"""Reconciliation runs: load scope from the database, run the engine, persist,
reload for reporting, and record exception updates with an audit trail."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import and_, func, insert, select

from ..core.models import (
    CLOSED_STATUSES, LEFT_SOURCES, PAIRED_CATEGORIES, PARTNER, REFERENCE_SOURCES, Category, DocType,
    ExceptionStatus, InvoiceRecord, ReconLine, ReconSettings, Source, fy_of,
)
from ..core.money import fmt_inr
from ..db.database import Database
from ..db.models import Client, Invoice, MatchDecision, ReconLineRow, ReconRun, SourceFile, utcnow
from ..engine.matcher import CancelToken, ReconResult, manual_pair_line, reconcile, single_sided_line
from ..engine.summary import dashboard
from ..importers.parsing import parse_period
from ..outward.liability import sales_code
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


def reference_scope(books: list[InvoiceRecord], portal: list[InvoiceRecord], source: Source):
    """Documents compared with the e-invoice (IRP) or e-way bill report.

    * e-invoices: supplies to registered persons and exports (B2C, nil/exempt and
      non-GST supplies are not e-invoiced);
    * e-way bills: every sales document (the threshold and services are handled
      after matching, see :func:`reference_remarks`).

    When the same IRN / e-way bill number was imported more than once (e.g. a later
    report showing it cancelled), the latest import is used. Cancelled ones are not
    compared; they are returned to explain the documents they leave unreported.
    """
    if source == Source.EINV:
        books = [r for r in books if (r.supplier_gstin or sales_code(r) == "31B")
                 and sales_code(r) not in ("31C", "31E")]
    latest: dict[str, InvoiceRecord] = {}
    loose = []
    for r in sorted(portal, key=lambda r: r.db_id or 0):
        key = r.irn or r.ref_no
        if key:
            latest[key] = r
        else:
            loose.append(r)
    current = sorted([*latest.values(), *loose], key=lambda r: r.db_id or 0)
    return books, [r for r in current if r.ref_status != "CANCELLED"], \
        [r for r in current if r.ref_status == "CANCELLED"]


AUTO_STATUS = "status set automatically: "


def _note(ln: ReconLine, text: str, status: ExceptionStatus | None = None) -> None:
    """Explain a line in its reasons (system text; remarks are the reviewer's)."""
    if status is not None:
        ln.status = status
        text += f" ({AUTO_STATUS}{status.value})"
    ln.reasons.append(text)


def auto_status(reasons: list[str]) -> str | None:
    """The status a rule set on a line, if any (a re-run re-applies the rule unless a user changed it)."""
    for r in reasons:
        if AUTO_STATUS in r:
            return r.rsplit(AUTO_STATUS, 1)[1].rstrip(")")
    return None


def reference_remarks(lines: list[ReconLine], cancelled: list[InvoiceRecord], source: Source,
                      threshold: Decimal) -> None:
    """Explain one-sided lines of a sales register vs e-invoice / e-way bill run.

    Nothing is hidden: lines keep their category. Only an e-way bill not needed by
    rule (value below the threshold, or a supply of services only) is marked
    *No Action Required*, with the reason in the remarks.
    """
    what = "IRN" if source == Source.EINV else "e-way bill"
    by_doc = {}
    for c in cancelled:
        by_doc.setdefault(c.invoice_no_norm, c)
    for ln in lines:
        if ln.category == Category.MISSING_IN_2B and ln.books is not None:
            b = ln.books
            c = by_doc.get(b.invoice_no_norm)
            if c is not None:
                _note(ln, f"{what} {c.ref_no or c.irn} for this document was cancelled – the sale is still in the "
                          "sales register: confirm whether it was made", ExceptionStatus.CLIENT_CLARIFICATION)
            elif source == Source.EWB:
                value = b.invoice_value if b.invoice_value is not None else b.taxable + b.total_tax
                services = bool(b.hsn_lines) and all(str(h.get("hsn", "")).startswith("99") for h in b.hsn_lines)
                if b.doc_type != DocType.INVOICE:
                    _note(ln, "Credit / debit note – no e-way bill for the note itself (goods returned move under "
                              "the e-way bill of the person sending them)", ExceptionStatus.NO_ACTION)
                elif services:
                    _note(ln, "Services only (SAC 99…) – no e-way bill needed", ExceptionStatus.NO_ACTION)
                elif value < threshold:
                    _note(ln, f"Below the ₹{fmt_inr(threshold)} e-way bill threshold (document value "
                              f"₹{fmt_inr(value)}) – check that no e-way bill was needed for the consignment",
                          ExceptionStatus.NO_ACTION)
                else:
                    _note(ln, "No e-way bill found – needed if goods worth more than the threshold moved "
                              "(check job work, services, or an e-way bill under another document number)")
            else:
                _note(ln, "No e-invoice found – a B2B / export invoice without an IRN is not a valid tax invoice "
                          "for a taxpayer required to e-invoice")
        elif ln.category == Category.MISSING_IN_BOOKS and ln.gstr2b is not None:
            _note(ln, f"{what} generated but the document is not in the sales register – record the sale, or "
                      f"confirm that the {what} was cancelled on the portal")


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
                q = q.order_by(Invoice.id)  # same input order on every database engine
                out = []
                for r in s.scalars(q):
                    file_of[r.id] = r.source_file_id
                    out.append(invoice_to_record(r, files.get(r.source_file_id, ""), prior))
                return out

            left = PARTNER.get(compare_with, Source.BOOKS)
            comparison = f"{left.value}_VS_{compare_with.value}"
            books = load(left)
            g2b = load(compare_with)
            cancelled: list[InvoiceRecord] = []
            if compare_with in REFERENCE_SOURCES:
                books, g2b, cancelled = reference_scope(books, g2b, compare_with)
            elif left == Source.SALES:
                # Unregistered recipients (B2C), exports and nil/exempt/non-GST supplies are reported in
                # GSTR-1 as section totals, so they are compared at summary level, not per invoice.
                books = [r for r in books if r.supplier_gstin and sales_code(r) not in ("31C", "31E")]
                g2b = [r for r in g2b if r.supplier_gstin]
            if not books and not g2b:
                raise ServiceError(f"No books or {compare_with.value} documents imported for {p_from} to {p_to}")
            # Earlier-period books not yet paired in a reconciliation of an earlier period.
            consumed = set(s.scalars(
                select(ReconLineRow.books_invoice_id).join(ReconRun, ReconRun.id == ReconLineRow.run_id).where(
                    ReconRun.client_id == client_id, ReconRun.period_to < p_from, ReconRun.comparison == comparison,
                    ReconLineRow.books_invoice_id.is_not(None), ReconLineRow.gstr2b_invoice_id.is_not(None),
                    ReconLineRow.category.in_([c.value for c in PAIRED_CATEGORIES]))))
            prior = [r for r in load(left, prior=True) if r.db_id not in consumed and r.supplier_gstin
                     and (left == Source.BOOKS or sales_code(r) not in ("31C", "31E"))]

            def engine_progress(pct, msg):
                progress(5 + int(pct * 0.8), msg)

            manual, rejected = self._decisions(s, client_id)
            result = reconcile(books, g2b, settings, prior_books=prior, period_start=period_start,
                               progress=engine_progress, cancel=cancel, manual_pairs=manual,
                               rejected_pairs=rejected)
            if cancel:
                cancel.check()
            if compare_with in REFERENCE_SOURCES:
                from .security import SecurityService

                threshold = SecurityService(self.db).setting("ewb_threshold")
                reference_remarks(result.lines, cancelled, compare_with,
                                  Decimal(str(threshold if threshold is not None else 50000)))
            progress(87, "Saving results")
            file_ids = sorted({file_of[r.db_id] for ln in result.lines for r in (ln.books, ln.gstr2b)
                               if r is not None})
            run = ReconRun(
                client_id=client_id, financial_year=fy_of(period_start), period_from=p_from, period_to=p_to,
                comparison=comparison, settings_json=dumps(settings.to_dict()),
                fingerprint=result.fingerprint, engine_version=result.engine_version,
                summary_json=dumps(dashboard(result.lines)), source_file_ids=json.dumps(file_ids),
                created_by=user or "", status="COMPLETED",
            )
            s.add(run)
            s.flush()
            self._carry_forward(s, client_id, p_from, p_to, result.lines, exclude_run=run.id, comparison=comparison)
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
    def _decisions(s, client_id: int):
        manual, rejected = [], []
        for d in s.scalars(select(MatchDecision).where(MatchDecision.client_id == client_id,
                                                       MatchDecision.active.is_(True)).order_by(MatchDecision.id)):
            pair = (f"I{d.books_invoice_id}", f"I{d.gstr2b_invoice_id}")
            if d.decision == "MATCH":
                note = f"Manually matched by {d.user or 'user'} on {d.created_at:%d-%m-%Y}"
                manual.append((*pair, note + (f": {d.remarks}" if d.remarks else "")))
            else:
                rejected.append(pair)
        return manual, rejected

    @staticmethod
    def _carry_forward(s, client_id: int, p_from: str, p_to: str, lines: list[ReconLine], exclude_run: int,
                       comparison: str = "BOOKS_VS_GSTR2B") -> None:
        """Carry review work into a new run without duplicating documents.

        * Same period re-run: status, remarks, assignee and action date of lines that
          contain the same documents in the same category are copied (a line the user
          marked *Pending Clarification* keeps that category unless it is now fully matched).
        * Any other earlier run: remarks, assignee and action date of the latest earlier
          line containing either document are carried so follow-up history continues
          across months; the status is re-evaluated.

        Only runs of the same comparison are used: a sales document's review against
        GSTR-1 says nothing about its e-invoice or e-way bill, and vice versa.
        """
        prev = s.scalar(select(ReconRun).where(
            ReconRun.client_id == client_id, ReconRun.period_from == p_from, ReconRun.period_to == p_to,
            ReconRun.id != exclude_run, ReconRun.comparison == comparison)
            .order_by(ReconRun.id.desc()).limit(1))
        old = {}
        if prev is not None:
            for r in s.scalars(select(ReconLineRow).where(ReconLineRow.run_id == prev.id)):
                old[(r.books_invoice_id, r.gstr2b_invoice_id)] = r
        ids = {r.db_id for ln in lines for r in (ln.books, ln.gstr2b) if r is not None and r.db_id}
        latest: dict[int, ReconLineRow] = {}
        if ids:
            q = (select(ReconLineRow).join(ReconRun, ReconRun.id == ReconLineRow.run_id)
                 .where(ReconRun.client_id == client_id, ReconRun.id != exclude_run,
                        ReconRun.comparison == comparison, (ReconLineRow.remarks != "") | (ReconLineRow.assigned_to != ""))
                 .order_by(ReconLineRow.run_id))
            for r in s.scalars(q):
                for doc in (r.books_invoice_id, r.gstr2b_invoice_id):
                    if doc in ids:
                        latest[doc] = r
        for ln in lines:
            key = (ln.books.db_id if ln.books else None, ln.gstr2b.db_id if ln.gstr2b else None)
            o = old.get(key)
            if o is not None and o.category == Category.PENDING_CLARIFICATION.value \
                    and ln.category != Category.FULLY_MATCHED:
                ln.reasons.append(f"Marked pending clarification earlier (engine category: {ln.category.value})")
                ln.category = Category.PENDING_CLARIFICATION
            if o is not None and o.category == ln.category.value:
                if o.status != auto_status(json.loads(o.reasons_json or "[]")):  # a rule's status is re-applied
                    ln.status = ExceptionStatus(o.status)
                ln.remarks, ln.assigned_to, ln.action_date = o.remarks, o.assigned_to, o.action_date
                continue
            src = next((latest[k] for k in key if k in latest), None)
            if src is not None and not ln.remarks:
                ln.remarks = f"[run #{src.run_id}] {src.remarks}" if src.remarks else ""
                ln.assigned_to, ln.action_date = src.assigned_to, src.action_date

    # ------------------------------------------------------------- loading
    def load(self, run_id: int) -> RunContext:
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            if run is None:
                raise ServiceError(f"Reconciliation run {run_id} not found")
            client = s.get(Client, run.client_id)
            # Core (not ORM) queries: loading 50k lines is several times faster this way.
            lt, it = ReconLineRow.__table__, Invoice.__table__
            line_rows = s.execute(select(lt).where(lt.c.run_id == run_id).order_by(lt.c.line_no)).all()
            doc_ids = select(lt.c.books_invoice_id).where(lt.c.run_id == run_id).union(
                select(lt.c.gstr2b_invoice_id).where(lt.c.run_id == run_id))
            invoices = {inv.id: inv for inv in s.execute(select(it).where(it.c.id.in_(doc_ids))).all()}
            file_ids = json.loads(run.source_file_ids or "[]")
            files = list(s.scalars(select(SourceFile).where(SourceFile.id.in_(file_ids)).order_by(SourceFile.id)))
            names = {f.id: f.file_name for f in files}
            records = {}
            for inv_id, inv in invoices.items():
                prior = Source(inv.source_type) in LEFT_SOURCES and inv.period < run.period_from
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
            if "status" in changes:  # keep the stored summary's pending count current without a full reload
                s.flush()
                summary = json.loads(run.summary_json or "{}")
                summary["pending_cases"] = s.scalar(select(func.count()).select_from(ReconLineRow).where(
                    ReconLineRow.run_id == run_id,
                    ReconLineRow.status.not_in([c.value for c in CLOSED_STATUSES])))
                run.summary_json = dumps(summary)
            audit(s, "UPDATE", "recon_line", f"{run_id}:{line_no}", {"before": before, "after": changes}, user,
                  run.client_id)

    # -------------------------------------------------- manual decisions
    def _row(self, s, run_id: int, line_no: int) -> ReconLineRow:
        row = s.scalar(select(ReconLineRow).where(ReconLineRow.run_id == run_id, ReconLineRow.line_no == line_no))
        if row is None:
            raise ServiceError(f"Line {line_no} not found in run {run_id}")
        return row

    @staticmethod
    def _record(s, run: ReconRun, invoice_id: int | None):
        if invoice_id is None:
            return None
        inv = s.get(Invoice, invoice_id)
        prior = Source(inv.source_type) in LEFT_SOURCES and inv.period < run.period_from
        return invoice_to_record(inv, inv.source_file.file_name if inv.source_file else "", prior)

    @staticmethod
    def _snapshot(row: ReconLineRow) -> dict:
        return {"line_no": row.line_no, "category": row.category, "books_invoice_id": row.books_invoice_id,
                "gstr2b_invoice_id": row.gstr2b_invoice_id, "status": row.status, "remarks": row.remarks}

    @staticmethod
    def _apply(row: ReconLineRow, ln: ReconLine) -> None:
        row.category = ln.category.value
        row.books_invoice_id = ln.books.db_id if ln.books else None
        row.gstr2b_invoice_id = ln.gstr2b.db_id if ln.gstr2b else None
        row.match_level, row.confidence = ln.match_level, ln.confidence
        row.flags_json = json.dumps(ln.flags)
        row.reasons_json = json.dumps(ln.reasons, ensure_ascii=False)
        row.candidates_json = json.dumps(ln.candidates)
        row.date_diff_days = ln.date_diff_days
        row.status = ln.status.value

    @staticmethod
    def _decide(s, client_id: int, run_id: int, books_id: int, g_id: int, decision: str, remarks: str,
                user: str | None) -> None:
        for d in s.scalars(select(MatchDecision).where(
                MatchDecision.client_id == client_id, MatchDecision.active.is_(True),
                ((MatchDecision.books_invoice_id == books_id) | (MatchDecision.gstr2b_invoice_id == g_id)))):
            # A document can be in only one confirmed pair; a new decision on the same
            # pair supersedes the old one.
            same_pair = (d.books_invoice_id, d.gstr2b_invoice_id) == (books_id, g_id)
            if same_pair or (decision == "MATCH" and d.decision == "MATCH"):
                d.active = False
        s.add(MatchDecision(client_id=client_id, books_invoice_id=books_id, gstr2b_invoice_id=g_id,
                            decision=decision, remarks=remarks or "", user=user or "", run_id=run_id))

    def _note(self, user: str | None, remarks: str, verb: str) -> str:
        note = f"{verb} by {user or 'user'} on {date.today():%d-%m-%Y}"
        return note + (f": {remarks}" if remarks else "")

    def _pair(self, s, run: ReconRun, keep: ReconLineRow, b, g, user, remarks) -> None:
        if b.doc_type != g.doc_type:
            raise ServiceError(f"Cannot pair a {b.doc_type.label} with a {g.doc_type.label}")
        settings = ReconSettings.from_dict(json.loads(run.settings_json))
        ln = manual_pair_line(b, g, settings, self._note(user, remarks, "Manually matched"))
        self._apply(keep, ln)
        if remarks:
            keep.remarks = f"{keep.remarks}\n{remarks}".strip()
        self._decide(s, run.client_id, run.id, b.db_id, g.db_id, "MATCH", remarks, user)

    def confirm_match(self, run_id: int, line_no: int, user: str | None = None, remarks: str = "") -> None:
        """Confirm the suggested pair on a line (probable match, GSTIN mismatch, far-apart dates)."""
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            row = self._row(s, run_id, line_no)
            if row.books_invoice_id is None or row.gstr2b_invoice_id is None:
                raise ServiceError("This line has no suggested counterpart – use Manual Match with two lines")
            if row.category == Category.MANUALLY_MATCHED.value:
                raise ServiceError("This line is already manually matched")
            before = self._snapshot(row)
            self._pair(s, run, row, self._record(s, run, row.books_invoice_id),
                       self._record(s, run, row.gstr2b_invoice_id), user, remarks)
            audit(s, "CONFIRM_MATCH", "recon_line", f"{run_id}:{line_no}",
                  {"before": before, "after": self._snapshot(row)}, user, run.client_id)
        self.refresh_summary(run_id)

    def manual_match(self, run_id: int, line_a: int, line_b: int, user: str | None = None,
                     remarks: str = "") -> int:
        """Pair a books-only line with a GSTR-2B-only line. Returns the surviving line number."""
        if line_a == line_b:
            raise ServiceError("Select two different lines")
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            rows = [self._row(s, run_id, n) for n in (line_a, line_b)]
            books_rows = [r for r in rows if r.books_invoice_id and not r.gstr2b_invoice_id]
            g_rows = [r for r in rows if r.gstr2b_invoice_id and not r.books_invoice_id]
            if len(books_rows) != 1 or len(g_rows) != 1:
                raise ServiceError("Manual match needs one line with only a books document and one line with "
                                   "only a GSTR-2B document (unmatch a suggested pair first)")
            keep, drop = sorted(rows, key=lambda r: r.line_no)
            before = [self._snapshot(r) for r in rows]
            b = self._record(s, run, books_rows[0].books_invoice_id)
            g = self._record(s, run, g_rows[0].gstr2b_invoice_id)
            keep.remarks = "\n".join(x for x in (keep.remarks, drop.remarks) if x)
            s.delete(drop)
            s.flush()
            self._pair(s, run, keep, b, g, user, remarks)
            audit(s, "MANUAL_MATCH", "recon_line", f"{run_id}:{keep.line_no}",
                  {"before": before, "after": self._snapshot(keep),
                   "note": f"line {drop.line_no} merged into line {keep.line_no}"}, user, run.client_id)
            kept = keep.line_no
        self.refresh_summary(run_id)
        return kept

    def unmatch(self, run_id: int, line_no: int, user: str | None = None, remarks: str = "") -> int:
        """Split a paired (or suggested) line; the pair is never matched again automatically.
        Returns the line number given to the GSTR-2B document."""
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            row = self._row(s, run_id, line_no)
            if row.books_invoice_id is None or row.gstr2b_invoice_id is None:
                raise ServiceError("Only a line holding both a books and a GSTR-2B document can be unmatched")
            before = self._snapshot(row)
            settings = ReconSettings.from_dict(json.loads(run.settings_json))
            start = date(int(run.period_from[:4]), int(run.period_from[5:]), 1)
            b = self._record(s, run, row.books_invoice_id)
            g = self._record(s, run, row.gstr2b_invoice_id)
            note = self._note(user, remarks, "Pair rejected")
            self._decide(s, run.client_id, run_id, b.db_id, g.db_id, "REJECT", remarks, user)
            new_no = (s.scalar(select(func.max(ReconLineRow.line_no)).where(ReconLineRow.run_id == run_id)) or 0) + 1
            g_line = single_sided_line(g, settings, start, note)
            g_line.line_no = new_no
            g_line.remarks = row.remarks
            if b.is_prior_period:
                # A prior-period booking only enters a run through its pairing.
                s.delete(row)
            else:
                self._apply(row, single_sided_line(b, settings, start, note))
            s.execute(insert(ReconLineRow), [self._line_row(run_id, g_line)])
            audit(s, "UNMATCH", "recon_line", f"{run_id}:{line_no}",
                  {"before": before, "gstr2b_line": new_no, "remarks": remarks}, user, run.client_id)
        self.refresh_summary(run_id)
        return new_no

    def mark_pending_clarification(self, run_id: int, line_no: int, user: str | None = None, remarks: str = "",
                                   status: str = ExceptionStatus.CLIENT_CLARIFICATION.value) -> None:
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            row = self._row(s, run_id, line_no)
            before = self._snapshot(row)
            if row.category != Category.PENDING_CLARIFICATION.value:
                reasons = json.loads(row.reasons_json)
                reasons.append(f"Engine category before clarification request: {row.category}")
                row.reasons_json = json.dumps(reasons, ensure_ascii=False)
            row.category = Category.PENDING_CLARIFICATION.value
            row.status = ExceptionStatus(status).value
            if remarks:
                row.remarks = f"{row.remarks}\n{remarks}".strip()
            audit(s, "PENDING_CLARIFICATION", "recon_line", f"{run_id}:{line_no}",
                  {"before": before, "after": self._snapshot(row)}, user, run.client_id)
        self.refresh_summary(run_id)

    def refresh_summary(self, run_id: int) -> dict:
        ctx = self.load(run_id)
        summary = dashboard(ctx.result.lines)
        with self.db.session() as s:
            s.get(ReconRun, run_id).summary_json = dumps(summary)
        return summary

    def decisions(self, client_id: int, active_only: bool = True) -> list[MatchDecision]:
        with self.db.session() as s:
            q = select(MatchDecision).where(MatchDecision.client_id == client_id)
            if active_only:
                q = q.where(MatchDecision.active.is_(True))
            return list(s.scalars(q.order_by(MatchDecision.id)))

    def line_history(self, run_id: int, line_no: int) -> list[dict]:
        """Audit entries for a line (status changes, matches, unmatches)."""
        from ..db.models import AuditLog

        with self.db.session() as s:
            rows = s.scalars(select(AuditLog).where(AuditLog.entity == "recon_line",
                                                    AuditLog.entity_id == f"{run_id}:{line_no}")
                             .order_by(AuditLog.id))
            return [{"at": r.at, "user": r.user, "action": r.action, "details": json.loads(r.details_json)}
                    for r in rows]


def default_report_name(client: Client, run: ReconRun, ext: str) -> str:
    return f"FINTAXPRO_GSTRecon_{client.gstin}_FY{run.financial_year}_{run.period_from}_to_{run.period_to}_run{run.id}.{ext}"


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
