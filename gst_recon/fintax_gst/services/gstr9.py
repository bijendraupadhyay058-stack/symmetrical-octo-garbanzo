"""GSTR-9 annual return working for a client and financial year."""
from __future__ import annotations

from sqlalchemy import select

from ..core.models import Source
from ..db.database import Database
from ..db.models import Invoice
from ..gstr9.working import Gstr9Working, build_gstr9
from ..itc.annual import fy_months
from .common import invoice_to_record
from .gstr3b import Gstr3bService
from .outward import OutwardService


class Gstr9Service:
    def __init__(self, db: Database):
        self.db = db

    def working(self, client_id: int, fy: str) -> Gstr9Working:
        months = fy_months(fy)
        out = OutwardService(self.db)
        summaries = [{**s, "period": p} for p, rows in out.summaries(client_id, months).items() for s in rows]
        it = Invoice.__table__
        with self.db.session() as s:
            docs = [invoice_to_record(r) for r in s.execute(
                select(it).where(it.c.client_id == client_id, it.c.source_type == Source.GSTR1.value,
                                 it.c.period.in_(months)).order_by(it.c.id))]
        sales = out.sales(client_id, months)
        filed = Gstr3bService(self.db).values(client_id, months)
        return build_gstr9(fy, months, summaries, docs, sales, filed)
