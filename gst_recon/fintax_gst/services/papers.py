"""Period-wise audit working papers: one ZIP per reconciliation run with a manifest.

Contents (only what exists for the run):

* ``01_Reconciliation`` – the Excel workbook and PDF summary of the run;
* ``02_Compliance`` – the client compliance summary for the financial year;
* ``03_Supplier_letters`` – letters issued from this run;
* ``04_Evidence`` – attachments on documents in the run (integrity checked);
* ``05_Source_files`` – register of imported files with SHA-256 (the files themselves
  are included only when ``include_sources`` is set);
* ``06_Audit_trail.csv`` – audit entries of the client for the period's work;
* ``00_Index.pdf`` with the preparer / reviewer sign-off block and ``manifest.json``
  listing every file with its SHA-256.

The ZIP is never modified after it is written. Review sign-off is recorded in the
database (and the audit log) against the ZIP's SHA-256; ``verify`` re-checks the file.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from .. import PRODUCT_FULL_NAME, __version__
from ..db.database import Database
from ..db.models import Attachment, AuditLog, LetterRecord, ReconLineRow, SourceFile, WorkingPaper
from .auth import Session, require
from .common import ServiceError, audit
from .compliance import ComplianceService
from .reconciliation import ReconciliationService
from .reports import export_run


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class WorkingPaperService:
    def __init__(self, db: Database):
        self.db = db
        self.recon = ReconciliationService(db)

    # ------------------------------------------------------------- prepare
    def prepare(self, run_id: int, out_dir: str | Path, by: Session, include_sources: bool = False) -> WorkingPaper:
        require(by, "prepare_papers")
        from ..reports.compliance_report import export_client_pdf

        ctx = self.recon.load(run_id)
        client, run = ctx.client, ctx.run
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now()
        name = f"WP_{client.gstin}_{run.period_from}_{run.period_to}_run{run.id}_{stamp:%Y%m%d%H%M%S}.zip"
        work = out_dir / f".{name}.parts"
        work.mkdir(exist_ok=True)
        entries: list[tuple[str, bytes]] = []
        try:
            for p in export_run(self.db, run_id, work, pdf=True, user=by.username):
                entries.append((f"01_Reconciliation/{p.name}", p.read_bytes()))
            cc = ComplianceService(self.db).client_summary(client.id, run.financial_year)
            pdf = export_client_pdf(cc, work / f"Compliance_{client.gstin}_{run.financial_year}.pdf")
            entries.append((f"02_Compliance/{pdf.name}", pdf.read_bytes()))
        finally:
            for f in work.glob("*"):
                f.unlink()
            work.rmdir()
        notes: list[str] = []
        with self.db.session() as s:
            for rec in s.scalars(select(LetterRecord).where(LetterRecord.run_id == run.id)):
                for f in json.loads(rec.files_json):
                    fp = Path(f)
                    if fp.is_file():
                        entries.append((f"03_Supplier_letters/{rec.id:04d}_{fp.name}", fp.read_bytes()))
                    else:
                        notes.append(f"Letter file no longer available: {fp.name}")
            docs = set()
            for r in s.scalars(select(ReconLineRow).where(ReconLineRow.run_id == run.id)):
                docs.update(d for d in (r.books_invoice_id, r.gstr2b_invoice_id) if d)
            for a in s.scalars(select(Attachment).where(Attachment.client_id == client.id)):
                if not ({a.books_invoice_id, a.gstr2b_invoice_id} & docs):
                    continue
                fp = Path(a.stored_path)
                data = fp.read_bytes() if fp.is_file() else None
                if data is None or _sha(data) != a.sha256:
                    notes.append(f"Evidence {a.file_name} (line {a.line_no}) missing or altered – not included")
                    continue
                entries.append((f"04_Evidence/line{a.line_no:05d}_{a.id}_{a.file_name}", data))
            files = [f for f in ctx.source_files]
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "source", "file_name", "period", "layout", "rows_read", "documents_imported",
                        "rows_rejected", "sha256", "imported_by", "imported_at_utc"])
            for f in files:
                w.writerow([f.id, f.source_type, f.file_name, f.period or "", f.layout, f.rows_read,
                            f.documents_imported, f.rows_rejected, f.sha256, f.imported_by,
                            f"{f.imported_at:%Y-%m-%d %H:%M:%S}"])
                if include_sources:
                    fp = Path(f.file_path)
                    if fp.is_file() and _file_sha(fp) == f.sha256:
                        entries.append((f"05_Source_files/{f.id}_{f.file_name}", fp.read_bytes()))
                    else:
                        notes.append(f"Source file {f.file_name} not found or changed since import – not included")
            entries.append(("05_Source_files/register.csv", buf.getvalue().encode("utf-8")))
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "at_utc", "user", "action", "entity", "entity_id", "details"])
            for a in s.scalars(select(AuditLog).where(AuditLog.client_id == client.id).order_by(AuditLog.id)):
                w.writerow([a.id, f"{a.at:%Y-%m-%d %H:%M:%S}", a.user, a.action, a.entity, a.entity_id,
                            a.details_json])
            entries.append(("06_Audit_trail.csv", buf.getvalue().encode("utf-8")))
        summary = json.loads(run.summary_json or "{}")
        manifest = {
            "product": PRODUCT_FULL_NAME, "version": __version__, "prepared_by": by.username,
            "prepared_at": stamp.isoformat(timespec="seconds"), "client": client.name, "gstin": client.gstin,
            "financial_year": run.financial_year, "period_from": run.period_from, "period_to": run.period_to,
            "run_id": run.id, "comparison": run.comparison, "run_fingerprint": run.fingerprint,
            "summary": summary, "notes": notes,
            "files": [{"path": p, "sha256": _sha(d), "bytes": len(d)} for p, d in entries],
        }
        index = self._index_pdf(manifest)
        entries.insert(0, ("00_Index.pdf", index))
        entries.append(("manifest.json", json.dumps(manifest, indent=2, default=str).encode("utf-8")))
        target = out_dir / name
        tmp = target.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for p, d in entries:
                z.writestr(p, d)
        tmp.replace(target)
        digest = _file_sha(target)
        with self.db.session() as s:
            wp = WorkingPaper(client_id=client.id, run_id=run.id, period_from=run.period_from,
                              period_to=run.period_to, prepared_by=by.username, package_path=str(target),
                              sha256=digest)
            s.add(wp)
            s.flush()
            audit(s, "PREPARE", "working_paper", wp.id, {"run_id": run.id, "sha256": digest,
                                                          "files": len(entries), "notes": notes},
                  by.username, client.id)
            s.expunge(wp)
        return wp

    @staticmethod
    def _index_pdf(m: dict) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        from ..reports.pdf_report import NAVY, _table

        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=NAVY, fontSize=16, alignment=0)
        small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8)
        s = m["summary"]
        story = [Paragraph("Audit working papers – GST reconciliation", h1),
                 Paragraph(f"<b>{m['client']}</b> &nbsp; GSTIN {m['gstin']} &nbsp; FY {m['financial_year']} &nbsp; "
                           f"Period {m['period_from']} to {m['period_to']} &nbsp; Run #{m['run_id']} "
                           f"({m['comparison'].replace('_', ' ')})", styles["Normal"]), Spacer(1, 3 * mm)]
        figures = [["Measure", "Value"]] + [[k.replace("_", " ").capitalize(), str(v)] for k, v in s.items()
                                            if k in ("total_lines", "fully_matched", "partially_matched",
                                                     "missing_in_gstr2b", "missing_in_books", "pending_cases",
                                                     "itc_at_risk", "match_percentage")]
        story += [_table(figures, [70 * mm, 50 * mm], money_cols=(1,)), Spacer(1, 4 * mm),
                  Paragraph("Contents", styles["Heading3"])]
        rows = [["File", "Bytes", "SHA-256"]] + [[f["path"], str(f["bytes"]), f["sha256"][:32] + "…"]
                                                 for f in m["files"]]
        story.append(_table(rows, [90 * mm, 18 * mm, 75 * mm], money_cols=(1,)))
        for n in m["notes"]:
            story.append(Paragraph("Note: " + n, small))
        sign = [["", "Name", "Date", "Signature"],
                ["Prepared by", m["prepared_by"], m["prepared_at"][:10], ""],
                ["Reviewed by", "", "", ""]]
        story += [Spacer(1, 6 * mm), Paragraph("Sign-off", styles["Heading3"]),
                  _table(sign, [30 * mm, 55 * mm, 30 * mm, 65 * mm]), Spacer(1, 3 * mm),
                  Paragraph("The complete list with full SHA-256 values is in manifest.json. Review sign-off is "
                            "also recorded in the application's audit trail against the package's SHA-256.", small)]
        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                          bottomMargin=12 * mm, title="Working papers index").build(story)
        return buf.getvalue()

    # -------------------------------------------------------------- review
    def review(self, paper_id: int, by: Session, notes: str = "") -> WorkingPaper:
        require(by, "review_papers")
        with self.db.session() as s:
            wp = s.get(WorkingPaper, paper_id)
            if wp is None:
                raise ServiceError(f"Working paper {paper_id} not found")
            if wp.reviewed_by:
                raise ServiceError(f"Already reviewed by {wp.reviewed_by} on {wp.reviewed_at:%d-%m-%Y}")
            if wp.prepared_by == by.username:
                raise ServiceError("The preparer cannot review their own working papers")
            ok, problem = self._check(wp)
            if not ok:
                raise ServiceError(f"Package failed the integrity check: {problem}")
            wp.reviewed_by, wp.reviewed_at, wp.review_notes = by.username, datetime.now(), notes
            audit(s, "REVIEW", "working_paper", wp.id, {"sha256": wp.sha256, "notes": notes}, by.username,
                  wp.client_id)
            s.flush()
            s.expunge(wp)
        return wp

    @staticmethod
    def _check(wp: WorkingPaper) -> tuple[bool, str]:
        p = Path(wp.package_path)
        if not p.is_file():
            return False, "package file not found"
        if _file_sha(p) != wp.sha256:
            return False, "package changed since it was prepared"
        with zipfile.ZipFile(p) as z:
            manifest = json.loads(z.read("manifest.json"))
            for f in manifest["files"]:
                if _sha(z.read(f["path"])) != f["sha256"]:
                    return False, f"{f['path']} does not match the manifest"
        return True, ""

    def verify(self, paper_id: int) -> tuple[bool, str]:
        with self.db.session() as s:
            wp = s.get(WorkingPaper, paper_id)
            if wp is None:
                raise ServiceError(f"Working paper {paper_id} not found")
            return self._check(wp)

    def list(self, client_id: int) -> list[WorkingPaper]:
        with self.db.session() as s:
            rows = list(s.scalars(select(WorkingPaper).where(WorkingPaper.client_id == client_id)
                                  .order_by(WorkingPaper.id.desc())))
            for r in rows:
                s.expunge(r)
        return rows


__all__ = ["WorkingPaperService", "SourceFile"]
