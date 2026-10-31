"""GSTR-9 annual return working for a client and financial year."""
from __future__ import annotations

from pathlib import Path

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
        with self.db.session() as s:
            purchases = [invoice_to_record(r) for r in s.execute(
                select(it).where(it.c.client_id == client_id, it.c.source_type == Source.BOOKS.value,
                                 it.c.period.in_(months)).order_by(it.c.id))]
        filed = Gstr3bService(self.db).values(client_id, months)
        actions = ItcService(self.db)._claim_actions(client_id, next_months)
        w = build_gstr9(fy, months, summaries, this_year, sales, filed, hsn, next_year, actions, cutoff, purchases)
        from ..gstr9.entered import entered_tables
        from .gstr9c import Gstr9cService

        w.table15, w.table16 = entered_tables(Gstr9cService(self.db).inputs(client_id, fy))
        return w

    def draft_json(self, client_id: int, fy: str, out_dir, cutoff: str | None = None,
                   user: str | None = None) -> tuple[Path, Path]:
        """Write the draft GSTR-9 JSON for the offline tool and its mapping (CSV). Audited."""
        import csv
        import json

        from ..gstr9.offline_json import build_draft
        from .clients import ClientService
        from .common import audit
        from .itc import ItcService

        client = ClientService(self.db).get(client_id)
        w = self.working(client_id, fy, cutoff)
        t8 = ItcService(self.db).annual(client_id, fy, cutoff)
        payload, rows = build_draft(w, t8, client.gstin, fy)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"FINTAXPRO_GSTR9_DRAFT_{client.gstin}_FY{fy}"
        js, mp = out_dir / f"{stem}.json", out_dir / f"{stem}_mapping.csv"
        js.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        with mp.open("w", newline="", encoding="utf-8-sig") as fh:
            wr = csv.writer(fh)
            wr.writerow(["DRAFT for review – import into the GST offline tool, which validates it; check every "
                         "table there before filing. Nothing is filed by FIN TAX PRO."])
            wr.writerow(["Table", "Description", "JSON path", "Value", "Status", "Note"])
            for r in rows:
                wr.writerow([r.table, r.description, r.json_path, r.value, r.status, r.note])
        with self.db.session() as s:
            audit(s, "EXPORT", "gstr9_draft_json", f"{client_id}:{fy}", {
                "files": [str(js), str(mp)], "included": sum(1 for r in rows if r.status == "included"),
                "manual": sum(1 for r in rows if r.status.startswith("enter"))}, user, client_id)
        return js, mp
