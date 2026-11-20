"""ITC claim plan of a GSTR-3B month (see itc/claim_plan.py): build it, record the claims, write off documents
that will not be claimed, and export the plan."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import delete, select

from ..core.models import Source
from ..db.database import Database
from ..db.models import Client, ItcClaim, ItcReview
from ..importers.parsing import parse_period
from ..itc.claim_plan import BARRED, CHECK, CLAIM, HOLD, ORDER, WRITTEN_OFF, ClaimPlan, build_plan
from .common import ServiceError, audit

WRITE_OFF_RULE = "PLAN_WRITE_OFF"


def _prev_fy_start(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    start = y if m >= 4 else y - 1
    return f"{start - 1}-04"


class ClaimPlanService:
    def __init__(self, db: Database):
        self.db = db

    def build(self, client_id: int, period: str, as_of: date | None = None) -> ClaimPlan:
        from .itc import ItcService
        from .reconciliation import months_between

        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        as_of = as_of or date.today()
        itc = ItcService(self.db)
        start = _prev_fy_start(p)
        months = months_between(start, p)
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            books = itc._docs(s, client_id, Source.BOOKS, months)
            gstr2b = itc._docs(s, client_id, Source.GSTR2B, months)
            claimed = set(s.scalars(select(ItcClaim.invoice_id).where(ItcClaim.client_id == client_id,
                                                                     ItcClaim.action == "CLAIM")))
            written = {r.invoice_id: r.remarks for r in s.scalars(select(ItcReview).where(
                ItcReview.client_id == client_id, ItcReview.rule_code == WRITE_OFF_RULE))}
            runs = itc._latest_month_runs(s, client_id, months)
        flags: dict[int, str] = {}
        for run_id in runs.values():
            reviews, _ = itc.review_run(run_id, as_of)
            for rv in reviews:
                if rv.record.db_id and rv.worst in ("high", "medium"):
                    flags[rv.record.db_id] = ", ".join(h.title for h in rv.open_hits)[:200]
        booked = {b.period for b in books if b.db_id not in claimed}
        plan = build_plan(p, books, gstr2b, claimed, flags, written, as_of,
                          unreviewed_periods=booked - set(runs))
        if not gstr2b:
            plan.notes.append("No GSTR-2B imported – every document stays on hold until GSTR-2B is imported.")
        missing = [m for m in months_between(f"{int(p[:4]) - (0 if int(p[5:]) >= 4 else 1)}-04", p)
                   if m not in {g.period for g in gstr2b}]
        if gstr2b and missing:
            plan.notes.append("GSTR-2B not imported for " + ", ".join(missing) + " – documents reported there show "
                              "as 'hold'.")
        return plan

    def record_claims(self, client_id: int, period: str, invoice_ids: list[int], user: str | None = None,
                      as_of: date | None = None):
        """Record the chosen 'claim now' / 'check first' documents as claimed in the month's GSTR-3B."""
        from .itc import ItcService

        plan = self.build(client_id, period, as_of)
        allowed = {ln.doc.db_id for ln in plan.lines if ln.bucket in (CLAIM, CHECK)}
        bad = [i for i in invoice_ids if i not in allowed]
        if bad:
            raise ServiceError(f"{len(bad)} document(s) cannot be claimed in {period} (on hold, time-barred, written "
                               "off or already claimed)")
        return ItcService(self.db).claim(client_id, invoice_ids, period, user,
                                         reason=f"ITC claim plan {period}: in GSTR-2B")

    def write_off(self, client_id: int, invoice_ids: list[int], reason: str, user: str | None = None) -> int:
        if not reason.strip():
            raise ServiceError("Give the reason for not claiming (e.g. supplier will not file, blocked credit)")
        from .itc import ItcService

        svc = ItcService(self.db)
        for i in invoice_ids:
            svc.set_review(client_id, i, WRITE_OFF_RULE, "CONFIRMED", reason.strip(), user)
        return len(invoice_ids)

    def undo_write_off(self, client_id: int, invoice_ids: list[int], user: str | None = None) -> int:
        with self.db.session() as s:
            n = s.execute(delete(ItcReview).where(ItcReview.client_id == client_id,
                                                  ItcReview.rule_code == WRITE_OFF_RULE,
                                                  ItcReview.invoice_id.in_(invoice_ids))).rowcount
            audit(s, "ITC_REVIEW", "invoice", ",".join(map(str, invoice_ids)), {"rule": WRITE_OFF_RULE,
                                                                               "after": "removed"}, user, client_id)
        return n

    def export_xlsx(self, plan: ClaimPlan, client_name: str, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append([f"ITC claim plan – {client_name} – GSTR-3B {plan.period}"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append(["", "Documents", "ITC (₹)"])
        for b in ORDER:
            ws.append([b, len(plan.bucket(b)), float(plan.total(b))])
        ws.append(["In GSTR-2B, not in books", len(plan.not_in_books),
                   float(sum(g.igst + g.cgst + g.sgst + g.cess for g in plan.not_in_books))])
        for n in plan.notes:
            ws.append([n])
        ws.column_dimensions["A"].width = 30
        fills = {CLAIM: "C8E6C9", CHECK: "FFF3C4", HOLD: "E3F2FD", BARRED: "FFCDD2", WRITTEN_OFF: "EEEEEE"}
        d = wb.create_sheet("Documents")
        head = ["Plan", "Supplier GSTIN", "Supplier", "Invoice no", "Date", "Booked in", "In GSTR-2B of", "ITC",
                "Last date (16(4))", "Days left", "Reason"]
        d.append(head)
        for c in d[1]:
            c.font = Font(bold=True)
        for ln in plan.lines:
            d.append([ln.bucket, ln.doc.supplier_gstin, ln.doc.supplier_name, ln.doc.invoice_no, ln.doc.invoice_date,
                      ln.doc.period, ln.gstr2b_period, float(ln.itc), ln.deadline, ln.days_left, ln.reason])
            for c in d[d.max_row]:
                c.fill = PatternFill("solid", fgColor=fills[ln.bucket])
        for col, w in zip("ABCDEFGHIJK", (12, 18, 28, 16, 11, 10, 12, 12, 14, 9, 70)):
            d.column_dimensions[col].width = w
        n = wb.create_sheet("Not in books")
        n.append(["Supplier GSTIN", "Supplier", "Invoice no", "Date", "GSTR-2B of", "ITC"])
        for g in plan.not_in_books:
            n.append([g.supplier_gstin, g.supplier_name, g.invoice_no, g.invoice_date, g.period,
                      float(g.igst + g.cgst + g.sgst + g.cess)])
        path = Path(path)
        wb.save(path)
        return path
