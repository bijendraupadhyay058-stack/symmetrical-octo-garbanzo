"""Supplier compliance scores of a client for a financial year (see itc/supplier_score.py)."""
from __future__ import annotations

from pathlib import Path

from ..core.models import Source
from ..db.database import Database
from ..itc.annual import fy_months
from ..itc.supplier_score import SupplierScore, score_suppliers


class SupplierScoreService:
    def __init__(self, db: Database):
        self.db = db

    def scores(self, client_id: int, fy: str, months: list[str] | None = None) -> tuple[list[SupplierScore],
                                                                                         list[str]]:
        from .followup import VendorService
        from .itc import ItcService

        months = months or fy_months(fy)
        itc = ItcService(self.db)
        with self.db.session() as s:
            books = itc._docs(s, client_id, Source.BOOKS, months)
            gstr2b = itc._docs(s, client_id, Source.GSTR2B, months)
            runs = itc._latest_month_runs(s, client_id, months)
        notes = []
        unreconciled = sorted({r.period for r in books} - set(runs))
        if unreconciled:
            notes.append("No books vs GSTR-2B reconciliation for " + ", ".join(unreconciled)
                         + " – documents missing in GSTR-2B and value differences are not counted for those months.")
        if not gstr2b:
            notes.append("No GSTR-2B imported for the year – late reporting cannot be measured.")
        monthly = [itc.recon.load(runs[m]).result.lines for m in months if m in runs]
        followups = {g: v.followup_status for g, v in VendorService(self.db).all(client_id).items()}
        return score_suppliers(books, gstr2b, monthly, followups), notes

    def export(self, client_id: int, fy: str, out_dir, user: str | None = None) -> Path:
        from openpyxl import Workbook

        from ..reports.excel_report import _register_styles, _Sheet, _write_table
        from .clients import ClientService
        from .common import audit

        client = ClientService(self.db).get(client_id)
        rows, notes = self.scores(client_id, fy)
        wb = Workbook(write_only=True)
        _register_styles(wb)
        sh = _Sheet(wb, "Supplier Scores", [17, 34, 8, 13, 14, 8, 8, 12, 8, 8, 8, 8, 8, 16, 70])
        sh.banner(f"Supplier compliance scores – {client.name} ({client.gstin}) – FY {fy}",
                  "From the purchase register, GSTR-2B and the monthly reconciliations. 100 = no issue found; points "
                  "are deducted for missing, late, mismatched, unavailable and amended documents.", 15)
        _write_table(sh, ["GSTIN", "Supplier", "Score", "Risk", "ITC at risk", "Books docs", "2B docs",
                          "Missing in 2B", "Late", "Max lag (months)", "Mismatched", "ITC N/A", "Amended",
                          "Follow-up", "Why"],
                     [[x.gstin, x.name, x.score, x.band, x.itc_at_risk, x.books_docs, x.gstr2b_docs, x.missing_docs,
                       x.late_docs, x.max_lag, x.mismatched, x.unavailable, x.amended, x.followup,
                       "; ".join(x.reasons)] for x in rows],
                     ["text", "wrap", "int", "text", "money", "int", "int", "int", "int", "int", "int", "int", "int",
                      "text", "wrap"], name="SupplierScores", totals=False)
        sh.append([])
        for n in notes:
            sh.append([sh.cell(n, "ftp_note")])
        out = Path(out_dir) / f"FINTAXPRO_Supplier_Scores_{client.gstin}_FY{fy}.xlsx"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.xlsx")
        wb.save(tmp)
        tmp.replace(out)
        with self.db.session() as s:
            audit(s, "EXPORT", "supplier_scores", f"{client_id}:{fy}", {"file": str(out)}, user, client_id)
        return out
