"""Outward supplies: GSTR-1 section totals, sales register and GSTR-3B Table 3.1."""
from __future__ import annotations

from sqlalchemy import select

from ..core.models import Source
from ..db.database import Database
from ..db.models import Gstr1Summary, Invoice
from ..outward.liability import LiabilityWorking, build_liability
from .common import invoice_to_record
from .gstr3b import Gstr3bService
from .itc import ItcService


class OutwardService:
    def __init__(self, db: Database):
        self.db = db
        self.gstr3b = Gstr3bService(db)

    def summaries(self, client_id: int, periods: list[str]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {p: [] for p in periods}
        with self.db.session() as s:
            for r in s.scalars(select(Gstr1Summary).where(Gstr1Summary.client_id == client_id,
                                                          Gstr1Summary.period.in_(periods))):
                out[r.period].append({"section": r.section, "supply": r.supply, "pos": r.pos, "rate": r.rate,
                                      "doc_count": r.doc_count, "taxable": r.taxable, "igst": r.igst,
                                      "cgst": r.cgst, "sgst": r.sgst, "cess": r.cess})
        return out

    def sales(self, client_id: int, periods: list[str]):
        it = Invoice.__table__
        with self.db.session() as s:
            rows = s.execute(select(it).where(it.c.client_id == client_id, it.c.source_type == Source.SALES.value,
                                              it.c.period.in_(periods))).all()
        return [invoice_to_record(r) for r in rows]

    def liability(self, client_id: int, periods: list[str]) -> list[LiabilityWorking]:
        summaries = self.summaries(client_id, periods)
        sales = self.sales(client_id, periods)
        filed = self.gstr3b.values(client_id, periods)
        rules = ItcService(self.db).rules(client_id)
        return [build_liability(p, summaries[p], [r for r in sales if r.period == p], filed.get(p), rules)
                for p in periods]
