"""Annual return pack for many clients: for each chosen client and financial year, bring the classification up to
date and write the annual working papers, then list what is still pending.

For each client (a problem with one client is recorded and the run carries on):

1. ITC classification – rebuild the register from the purchase register and tax ledgers (manual classifications and
   recorded claims stay), suggestions from the client's master and the firm template;
2. Ledger classification – suggestions for the trial balance's pending ledgers (nothing is approved);
3. claims that could be proposed from the GSTR-2B reconciliation and GSTR-3B are counted, not recorded – they need
   the user's confirmation in ITC classification;
4. files in ``<folder>/<client> <GSTIN>/``: ITC classification workbook + review PDF, ledger bifurcation workbook +
   PDF (when a trial balance is imported), draft GSTR-9 JSON + mapping;
5. a summary workbook ``Annual_pack_<FY>.xlsx`` with one line per client and what is pending.

Nothing is filed and nothing is approved on the user's behalf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

from ..db.database import Database
from ..db.models import Client, Invoice, TaxPosting, TbLedger
from ..itc.annual import fy_months
from .common import ServiceError, audit


@dataclass
class PackRow:
    client_id: int
    name: str
    gstin: str
    txns: int = 0
    unclassified: int = 0
    to_review: int = 0
    claims_unverified: int = 0
    claims_proposable: int = 0
    ledgers: int = 0
    ledgers_pending: int = 0
    unallocated: str = ""
    failed_controls: list[str] = field(default_factory=list)
    final: bool = False
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def pending(self) -> list[str]:
        out = []
        if not self.txns and not self.ledgers:
            out.append("no purchase register / tax ledgers / trial balance for the year")
        if self.unclassified:
            out.append(f"{self.unclassified} transaction(s) unclassified")
        if self.to_review:
            out.append(f"{self.to_review} low-confidence suggestion(s)")
        if self.claims_proposable:
            out.append(f"{self.claims_proposable} claim(s) to confirm (proposed from GSTR-3B)")
        if self.claims_unverified - self.claims_proposable > 0:
            out.append(f"{self.claims_unverified - self.claims_proposable} claim(s) to record by hand")
        if self.ledgers_pending:
            out.append(f"{self.ledgers_pending} trial-balance ledger(s) not approved")
        if self.unallocated:
            out.append(f"₹{self.unallocated} not classified in the trial balance")
        out += [f"control {c}" for c in self.failed_controls]
        out += [f"error: {e}" for e in self.errors]
        return out

    @property
    def status(self) -> str:
        if self.errors:
            return "Error"
        if self.final:
            return "Final"
        return "Ready to review" if not self.pending else "Pending"


class AnnualPackService:
    def __init__(self, db: Database):
        self.db = db

    def run(self, client_ids: list[int], fy: str, out_dir: str | Path, user: str, progress=None, cancel=None,
            pdf: bool = True) -> tuple[list[PackRow], Path]:
        from ..letters.render import safe_name
        from .bifurcation import BifurcationService
        from .gstr9 import Gstr9Service
        from .itc_register import ItcRegisterService

        progress = progress or (lambda pct, msg: None)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if not client_ids:
            raise ServiceError("Choose at least one client")
        reg, bif, g9 = ItcRegisterService(self.db), BifurcationService(self.db), Gstr9Service(self.db)
        months = fy_months(fy)
        rows: list[PackRow] = []
        for i, cid in enumerate(client_ids):
            if cancel:
                cancel.check()
            with self.db.session() as s:
                c = s.get(Client, cid)
                if c is None:
                    continue
                name, gstin = c.name, c.gstin
                has_books = bool(s.scalar(select(func.count()).select_from(Invoice).where(
                    Invoice.client_id == cid, Invoice.source_type == "BOOKS", Invoice.period.in_(months))))
                has_tax = bool(s.scalar(select(func.count()).select_from(TaxPosting).where(
                    TaxPosting.client_id == cid, TaxPosting.financial_year == fy)))
                has_tb = bool(s.scalar(select(func.count()).select_from(TbLedger).where(
                    TbLedger.client_id == cid, TbLedger.financial_year == fy)))
            row = PackRow(cid, name, gstin)
            rows.append(row)
            progress(int(100 * i / len(client_ids)), f"{name} ({i + 1} of {len(client_ids)})")
            folder = out_dir / safe_name(f"{name} {gstin}")
            try:
                if has_books or has_tax:
                    reg.build(cid, fy, user)
                    w = reg.working(cid, fy)
                    row.txns, row.unclassified, row.to_review = len(w.txns), w.unclassified, w.to_review
                    row.claims_unverified = w.by_claim.get("unknown").count if w.by_claim.get("unknown") else 0
                    row.claims_proposable = sum(1 for x in reg.propose_claims(cid, fy) if x.usable)
                    row.failed_controls = [f"{x.code} {x.title}" for x in w.controls if x.status == "fail"]
                    row.final = bool(w.final)
                    folder.mkdir(parents=True, exist_ok=True)
                    row.files.append(reg.export_xlsx(cid, fy, folder / f"ITC_classification_{gstin}_{fy}.xlsx"))
                    if pdf:
                        row.files.append(reg.export_pdf(cid, fy, folder / f"ITC_classification_{gstin}_{fy}.pdf"))
                if has_tb:
                    bif.suggest_all(cid, fy, user)
                    sm = bif.summary(cid, fy)
                    row.ledgers = len(sm.in_scope)
                    row.ledgers_pending = sum(1 for v in sm.in_scope if v.state != "Approved")
                    row.unallocated = f"{sm.unallocated:,.2f}" if sm.unallocated else ""
                    folder.mkdir(parents=True, exist_ok=True)
                    row.files.append(bif.export_xlsx(cid, fy, folder / f"Ledger_bifurcation_{gstin}_{fy}.xlsx"))
                    if pdf:
                        row.files.append(bif.export_pdf(cid, fy, folder / f"Ledger_bifurcation_{gstin}_{fy}.pdf"))
                if has_books or has_tb:
                    js, mp = g9.draft_json(cid, fy, folder, user=user)
                    row.files += [js, mp]
            except Exception as exc:  # noqa: BLE001 - one client's problem does not stop the batch
                row.errors.append(str(exc) or type(exc).__name__)
        summary = self._summary(rows, fy, out_dir)
        with self.db.session() as s:
            audit(s, "ANNUAL_PACK", "annual_pack", fy, {"clients": len(rows), "folder": str(out_dir),
                                                        "summary": str(summary)}, user)
        progress(100, "Done")
        return rows, summary

    @staticmethod
    def _summary(rows: list[PackRow], fy: str, out_dir: Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = f"Annual pack {fy}"
        head = ["Client", "GSTIN", "Status", "Transactions", "Unclassified", "Low confidence", "Claims not verified",
                "Claims to confirm", "TB ledgers", "TB pending", "Unallocated (Rs.)", "Pending / remarks", "Folder"]
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
        fills = {"Final": "C8E6C9", "Ready to review": "E3F2FD", "Pending": "FFF3C4", "Error": "FFCDD2"}
        for r in rows:
            ws.append([r.name, r.gstin, r.status, r.txns, r.unclassified, r.to_review, r.claims_unverified,
                       r.claims_proposable, r.ledgers, r.ledgers_pending, r.unallocated, "; ".join(r.pending),
                       str(r.files[0].parent) if r.files else ""])
            ws.cell(ws.max_row, 3).fill = PatternFill("solid", fgColor=fills[r.status])
        for col, w in zip("ABCDEFGHIJKLM", (32, 17, 15, 12, 12, 13, 15, 15, 10, 10, 15, 90, 40)):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:M{ws.max_row}"
        path = out_dir / f"Annual_pack_{fy}_{datetime.now():%Y%m%d_%H%M}.xlsx"
        wb.save(path)
        return path
