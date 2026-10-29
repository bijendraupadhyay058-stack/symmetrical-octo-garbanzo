"""Client compliance summary and the annual dashboard across clients (read-only)."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from ..compliance.summary import ClientCompliance, MonthStatus, assess
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Gstr1Summary, Gstr3bEntry, Invoice, ReconRun, Vendor
from ..importers.gstr3b import Gstr3bValues
from ..itc.annual import fy_months
from .common import ServiceError
from .outward import OutwardService

ITC_4A = ("4A1", "4A2", "4A3", "4A4", "4A5")


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


class ComplianceService:
    def __init__(self, db: Database):
        self.db = db

    def client_summary(self, client_id: int, fy: str, today: date | None = None) -> ClientCompliance:
        today = today or date.today()
        months = fy_months(fy)
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            counts: dict[tuple[str, str], int] = {
                (p, src): n for p, src, n in s.execute(
                    select(Invoice.period, Invoice.source_type, func.count())
                    .where(Invoice.client_id == client_id, Invoice.period.in_(months))
                    .group_by(Invoice.period, Invoice.source_type))}
            g1_periods = set(s.scalars(select(Gstr1Summary.period).where(
                Gstr1Summary.client_id == client_id, Gstr1Summary.period.in_(months)).distinct()))
            filed = {(e.period, e.table_code): e for e in s.scalars(select(Gstr3bEntry).where(
                Gstr3bEntry.client_id == client_id, Gstr3bEntry.active.is_(True), Gstr3bEntry.period.in_(months)))}
            runs = s.scalars(select(ReconRun).where(ReconRun.client_id == client_id,
                                                    ReconRun.period_from == ReconRun.period_to,
                                                    ReconRun.period_from.in_(months)).order_by(ReconRun.id)).all()
            latest = {(r.period_from, r.comparison.split("_")[0]): r for r in runs}
            due = s.scalar(select(func.count()).select_from(Vendor).where(
                Vendor.client_id == client_id, Vendor.next_followup.is_not(None), Vendor.next_followup <= today))
            name, gstin = client.name, client.gstin
        out_periods = [p for p in months if (p, "SALES") in counts or p in g1_periods]
        liability = {w.period: w for w in OutwardService(self.db).liability(client_id, out_periods)} \
            if out_periods else {}
        result = []
        for p in months:
            m = MonthStatus(p, counts.get((p, "BOOKS"), 0), counts.get((p, "GSTR2B"), 0),
                            counts.get((p, "SALES"), 0), counts.get((p, "GSTR1"), 0), p in g1_periods,
                            any(k[0] == p for k in filed))
            inward, outward = latest.get((p, "BOOKS")), latest.get((p, "SALES"))
            if inward:
                m.inward_run_id, m.inward = inward.id, json.loads(inward.summary_json or "{}")
                m.itc_2b = _dec(m.inward.get("itc_as_per_gstr2b"))
                m.itc_books = _dec(m.inward.get("itc_as_per_books"))
            if outward:
                m.outward_run_id, m.outward = outward.id, json.loads(outward.summary_json or "{}")
            if m.gstr3b_imported:
                if any((p, c) in filed for c in ITC_4A):
                    m.itc_3b = sum((filed[(p, c)].igst + filed[(p, c)].cgst + filed[(p, c)].sgst + filed[(p, c)].cess
                                    for c in ITC_4A if (p, c) in filed), ZERO)
            w = liability.get(p)
            if w is not None:
                if p in g1_periods:
                    m.output_gstr1 = w.row("31A").gstr1.total + w.row("31B").gstr1.total
                if m.sales_docs:
                    m.output_sales = w.row("31A").sales.total + w.row("31B").sales.total
                f = [w.row(c).filed for c in ("31A", "31B")]
                if any((p, c) in filed for c in ("31A", "31B")):
                    m.output_3b = sum(((x or Gstr3bValues()).total for x in f), ZERO)
            result.append(assess(m, today))
        return ClientCompliance(client_id, name, gstin, fy, result, due or 0)

    def annual_dashboard(self, fy: str, client_ids: list[int] | None = None,
                         today: date | None = None) -> list[ClientCompliance]:
        with self.db.session() as s:
            q = select(Client.id).where(Client.active.is_(True)).order_by(Client.name)
            ids = [i for i in s.scalars(q) if client_ids is None or i in client_ids]
        return [self.client_summary(i, fy, today) for i in ids]
