"""Prepare the GSTR-1 JSON of a month from the imported sales register (see outward/gstr1_json.py)."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from ..db.database import Database
from ..db.models import Client, Invoice
from ..importers.parsing import parse_period
from ..outward.gstr1_json import Gstr1Draft, SaleDoc, build_gstr1
from .common import ServiceError, audit


class Gstr1PrepService:
    def __init__(self, db: Database):
        self.db = db

    def draft(self, client_id: int, period: str) -> Gstr1Draft:
        p = parse_period(period)
        if not p:
            raise ServiceError(f"Invalid period {period} – use YYYY-MM")
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            rows = list(s.scalars(select(Invoice).where(Invoice.client_id == client_id, Invoice.source_type == "SALES",
                                                        Invoice.period == p).order_by(Invoice.invoice_date,
                                                                                      Invoice.id)))
            gstin, state = client.gstin, client.state_code
        if not rows:
            raise ServiceError(f"No sales register imported for {p} – import it on the Sales & GSTR-1 page first")
        docs = [SaleDoc(r.id, r.supplier_gstin or "", r.supplier_name, r.doc_type, r.invoice_no, r.invoice_date,
                        r.taxable, r.igst, r.cgst, r.sgst, r.cess, r.invoice_value, r.place_of_supply or "",
                        r.supply_type or "", bool(r.reverse_charge),
                        json.loads(r.hsn_json) if r.hsn_json else []) for r in rows]
        return build_gstr1(gstin, p, docs, state)

    def save(self, client_id: int, draft: Gstr1Draft, path: str | Path, user: str | None = None) -> Path:
        out = Path(path)
        out.write_text(json.dumps(draft.payload, indent=1, ensure_ascii=False), encoding="utf-8")
        with self.db.session() as s:
            audit(s, "EXPORT", "gstr1_json", out.name, {"period": draft.payload.get("fp"), "counts": draft.counts,
                                                        "left_out": sum(1 for i in draft.issues
                                                                        if i.severity == "error")}, user, client_id)
        return out
