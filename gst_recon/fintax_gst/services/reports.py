from __future__ import annotations

from datetime import date
from pathlib import Path

from ..db.database import Database
from ..reports.excel_report import export_excel
from ..reports.pdf_report import export_pdf
from .common import audit
from .followup import AttachmentService, VendorService
from .imports import ImportService
from .reconciliation import ReconciliationService, default_report_name


def itc_report_data(db: Database, run_id: int, as_of: date | None = None):
    from ..reports.itc_sheets import ItcReportData
    from .itc import ItcService
    from .reconciliation import months_between

    itc = ItcService(db)
    ctx = itc.recon.load(run_id)
    periods = months_between(ctx.run.period_from, ctx.run.period_to)
    as_of = as_of or date.today()
    reviews, buckets = itc.review_run(run_id, as_of)
    ims_rows, ims_notes = itc.ims_compare(ctx.client.id, periods)
    return ItcReportData(reviews, buckets, itc.table4(ctx.client.id, periods, as_of), ims_rows,
                         ims_notes if ims_rows else [], as_of)


def outward_report_data(db: Database, run_id: int):
    from ..reports.outward_sheets import OutwardReportData
    from .outward import OutwardService
    from .reconciliation import months_between

    ctx = ReconciliationService(db).load(run_id)
    periods = months_between(ctx.run.period_from, ctx.run.period_to)
    svc = OutwardService(db)
    return OutwardReportData(svc.liability(ctx.client.id, periods), svc.summaries(ctx.client.id, periods))


def export_run(db: Database, run_id: int, out_dir: str | Path, pdf: bool = True,
               user: str | None = None, as_of: date | None = None) -> list[Path]:
    ctx = ReconciliationService(db).load(run_id)
    issues = ImportService(db).issues_for([f.id for f in ctx.source_files])
    out_dir = Path(out_dir)
    vendors = VendorService(db).all(ctx.client.id)
    evidence = AttachmentService(db).counts(run_id)
    if ctx.run.comparison.startswith("SALES"):
        itc, outward = None, outward_report_data(db, run_id)
    else:
        itc, outward = itc_report_data(db, run_id, as_of), None
    paths = [export_excel(ctx, out_dir / default_report_name(ctx.client, ctx.run, "xlsx"), issues, vendors, evidence,
                          itc, outward)]
    if pdf:
        paths.append(export_pdf(ctx, out_dir / default_report_name(ctx.client, ctx.run, "pdf")))
    with db.session() as s:
        audit(s, "EXPORT", "recon_run", run_id, {"files": [str(p) for p in paths]}, user, ctx.client.id)
    return paths
