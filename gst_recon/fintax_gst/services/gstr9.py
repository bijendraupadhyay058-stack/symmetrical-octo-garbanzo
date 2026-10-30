"""GSTR-9 annual return working for a client and financial year."""
from __future__ import annotations

from sqlalchemy import select

from ..core.models import Source
from ..db.database import Database
from ..db.models import Gstr1Hsn, Invoice
from ..gstr9.working import Gstr9Working, build_gstr9
from ..itc.annual import default_cutoff, fy_months
from .common import invoice_to_record
from .gstr3b import Gstr3bService
from .outward import OutwardService
from .reconciliation import months_between


class Gstr9Service:
    def __init__(self, db: Database):
        self.db = db

    def working(self, client_id: int, fy: str, cutoff: str | None = None) -> Gstr9Working:
        """``cutoff``: last month of the next year whose returns can still carry this year's
        supplies and ITC (default November, as for the annual return)."""
        from .itc import ItcService

        months = fy_months(fy)
        cutoff = cutoff or default_cutoff(fy)
        next_months = months_between(f"{int(fy[:4]) + 1}-04", cutoff)
        out = OutwardService(self.db)
        summaries = [{**s, "period": p} for p, rows in out.summaries(client_id, months).items() for s in rows]
        it = Invoice.__table__
        with self.db.session() as s:
            docs = [invoice_to_record(r) for r in s.execute(
                select(it).where(it.c.client_id == client_id, it.c.source_type == Source.GSTR1.value,
                                 it.c.period.in_(months + next_months)).order_by(it.c.id))]
            hsn = [{"hsn": h.hsn, "description": h.description, "uqc": h.uqc, "rate": h.rate, "qty": h.qty,
                    "taxable": h.taxable, "igst": h.igst, "cgst": h.cgst, "sgst": h.sgst, "cess": h.cess}
                   for h in s.scalars(select(Gstr1Hsn).where(Gstr1Hsn.client_id == client_id,
                                                             Gstr1Hsn.period.in_(months)))]
        this_year = [d for d in docs if d.period in months]
        next_year = [d for d in docs if d.period in next_months]
        sales = out.sales(client_id, months)
        filed = Gstr3bService(self.db).values(client_id, months)
        actions = ItcService(self.db)._claim_actions(client_id, next_months)
        return build_gstr9(fy, months, summaries, this_year, sales, filed, hsn, next_year, actions, cutoff)
