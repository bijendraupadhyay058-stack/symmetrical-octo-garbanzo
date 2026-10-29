from __future__ import annotations

from pathlib import Path

from ..db.database import Database
from ..reports.excel_report import export_excel
from ..reports.pdf_report import export_pdf
from .common import audit
from .followup import AttachmentService, VendorService
from .imports import ImportService
from .reconciliation import ReconciliationService, default_report_name


def export_run(db: Database, run_id: int, out_dir: str | Path, pdf: bool = True,
               user: str | None = None) -> list[Path]:
    ctx = ReconciliationService(db).load(run_id)
    issues = ImportService(db).issues_for([f.id for f in ctx.source_files])
    out_dir = Path(out_dir)
    vendors = VendorService(db).all(ctx.client.id)
    evidence = AttachmentService(db).counts(run_id)
    paths = [export_excel(ctx, out_dir / default_report_name(ctx.client, ctx.run, "xlsx"), issues, vendors, evidence)]
    if pdf:
        paths.append(export_pdf(ctx, out_dir / default_report_name(ctx.client, ctx.run, "pdf")))
    with db.session() as s:
        audit(s, "EXPORT", "recon_run", run_id, {"files": [str(p) for p in paths]}, user, ctx.client.id)
    return paths
