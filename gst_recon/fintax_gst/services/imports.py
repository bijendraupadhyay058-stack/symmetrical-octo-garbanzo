"""Import use-cases: preview, commit, repeated-import protection, mapping templates."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, func, insert, select

from ..core.models import Source
from ..db.database import Database
from ..db.models import (
    Gstr1Hsn, Gstr1Summary, TdsTcsCredit, Gstr3bEntry, ImportIssue, ImportTemplate, Invoice, ItcClaim, ItcReview,
    MatchDecision, OtherItc, ReconLineRow, ReconRun, SourceFile,
)
from ..importers.parsing import parse_date
from ..engine.matcher import CancelToken
from ..importers.pipeline import ImportPreview, preview_file
from .common import ServiceError, audit, dumps

BATCH = 2000


class ImportService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ templates
    def save_template(self, name: str, source: Source | str, mapping: dict, user: str | None = None) -> None:
        if "fields" not in mapping:
            mapping = {"fields": mapping}
        with self.db.session() as s:
            existing = s.scalar(select(ImportTemplate).where(ImportTemplate.name == name))
            if existing:
                existing.mapping_json = json.dumps(mapping)
                existing.source_type = Source(source).value
            else:
                s.add(ImportTemplate(name=name, source_type=Source(source).value, mapping_json=json.dumps(mapping)))
            audit(s, "SAVE", "import_template", name, mapping, user)

    def get_template(self, name: str) -> dict:
        with self.db.session() as s:
            t = s.scalar(select(ImportTemplate).where(ImportTemplate.name == name))
        if t is None:
            raise ServiceError(f"Import template '{name}' not found")
        return json.loads(t.mapping_json)

    def list_templates(self) -> list[ImportTemplate]:
        with self.db.session() as s:
            return list(s.scalars(select(ImportTemplate).order_by(ImportTemplate.name)))

    # -------------------------------------------------------------- preview
    def preview_auto(self, client_id: int, path: str | Path, source: Source | str, period: str | None = None,
                     sheet: str | None = None) -> ImportPreview:
        """Preview with automatic heading detection; if the headings are not recognised, try the saved
        templates of this source type (newest first). The template used is noted in the preview."""
        from ..importers.pipeline import MappingRequired, RowIssue

        try:
            return self.preview(client_id, path, source, period, sheet=sheet)
        except MappingRequired as first:
            source = Source(source)
            with self.db.session() as s:
                templates = list(s.scalars(select(ImportTemplate).where(ImportTemplate.source_type == source.value)
                                           .order_by(ImportTemplate.id.desc())))
            for t in templates:
                try:
                    preview = self.preview(client_id, path, source, period, json.loads(t.mapping_json), sheet)
                except MappingRequired:
                    continue
                preview.issues.insert(0, RowIssue("", "", "info", f"Column mapping from saved template '{t.name}'"))
                return preview
            raise first

    def preview(self, client_id: int, path: str | Path, source: Source | str, period: str | None = None,
                template: str | dict | None = None, sheet: str | None = None) -> ImportPreview:
        if isinstance(template, str):
            template = self.get_template(template)
        preview = preview_file(path, source, period=period, template=template, sheet=sheet)
        with self.db.session() as s:
            prior = s.scalar(select(SourceFile.id).where(
                SourceFile.client_id == client_id, SourceFile.sha256 == preview.sha256,
                SourceFile.source_type == preview.source.value))
            preview.already_imported_file_id = prior
            hashes = [r.identity_hash() for r in preview.records]
            existing: set[str] = set()
            for i in range(0, len(hashes), 900):
                existing.update(s.scalars(select(Invoice.identity_hash).where(
                    Invoice.client_id == client_id, Invoice.identity_hash.in_(hashes[i:i + 900]))))
            preview.existing_record_hashes = existing
        return preview

    # --------------------------------------------------------------- commit
    def commit(self, client_id: int, preview: ImportPreview, user: str | None = None,
               cancel: CancelToken | None = None, progress=None) -> SourceFile:
        """Persist a preview in one transaction. Documents already present for the
        client are skipped and logged; rejected rows are stored with their raw values."""
        if preview.already_imported_file_id:
            raise ServiceError(
                f"{preview.file_name} was already imported (source file #{preview.already_imported_file_id}). "
                "Remove that import first if you want to re-import it.")
        if not preview.records and not preview.issues:
            raise ServiceError(f"{preview.file_name}: nothing to import")
        progress = progress or (lambda pct, msg: None)
        new_records = preview.new_records
        skipped = [r for r in preview.records if r.identity_hash() in preview.existing_record_hashes]
        with self.db.session() as s:
            sf = SourceFile(
                client_id=client_id, source_type=preview.source.value, file_name=preview.file_name,
                file_path=str(preview.file_path.resolve()), sha256=preview.sha256, layout=preview.layout,
                period=preview.period, rows_read=preview.total_rows, documents_imported=len(new_records),
                rows_rejected=preview.rejected_rows, documents_skipped_existing=len(skipped),
                mapping_json=dumps({k: v.fields for k, v in preview.mappings.items()}),
                warnings_json=dumps(preview.file_warnings), imported_by=user or "",
            )
            s.add(sf)
            s.flush()
            rows = [{
                "client_id": client_id, "source_file_id": sf.id, "source_type": r.source.value,
                "source_rows": r.source_rows[:200], "supplier_gstin": r.supplier_gstin,
                "supplier_name": r.supplier_name[:200], "doc_type": r.doc_type.value, "invoice_no": r.invoice_no[:100],
                "invoice_no_norm": r.invoice_no_norm[:100], "invoice_date": r.invoice_date, "period": r.period,
                "taxable": r.taxable, "igst": r.igst, "cgst": r.cgst, "sgst": r.sgst, "cess": r.cess,
                "invoice_value": r.invoice_value, "place_of_supply": r.place_of_supply[:60],
                "reverse_charge": r.reverse_charge, "itc_availability": r.itc_availability,
                "itc_reason": r.itc_reason, "is_amendment": r.is_amendment,
                "original_invoice_no": r.original_invoice_no[:100], "original_invoice_date": r.original_invoice_date,
                "supplier_period": r.supplier_period[:20], "identity_hash": r.identity_hash(),
                "description": r.description, "ims_action": r.ims_action, "supply_type": r.supply_type[:40],
                "hsn_json": json.dumps(r.hsn_lines) if r.hsn_lines else "",
                "irn": r.irn, "ref_no": r.ref_no, "ref_status": r.ref_status,
            } for r in new_records]
            for i in range(0, len(rows), BATCH):
                if cancel:
                    cancel.check()  # raises -> whole transaction rolled back
                s.execute(insert(Invoice), rows[i:i + BATCH])
                progress(int(90 * min(i + BATCH, len(rows)) / max(len(rows), 1)), "Saving documents")
            issues = [{"source_file_id": sf.id, "sheet": i.sheet, "row_ref": i.row[:200], "severity": i.severity,
                       "message": i.message, "raw_json": dumps(i.raw)} for i in preview.issues]
            issues += [{"source_file_id": sf.id, "sheet": "", "row_ref": r.source_rows[:200], "severity": "existing",
                        "message": f"Document '{r.invoice_no}' ({r.supplier_gstin}) already imported earlier – skipped",
                        "raw_json": "{}"} for r in skipped]
            if issues:
                s.execute(insert(ImportIssue), issues)
            self._save_other_itc(s, client_id, sf.id, preview)
            if preview.outward_summary:
                s.execute(insert(Gstr1Summary), [{"client_id": client_id, "source_file_id": sf.id,
                                                  "period": preview.period, **row} for row in preview.outward_summary])
            if preview.hsn_summary:
                s.execute(insert(Gstr1Hsn), [{"client_id": client_id, "source_file_id": sf.id,
                                              "period": preview.period, **row} for row in preview.hsn_summary])
            audit(s, "IMPORT", "source_file", sf.id, preview.summary(), user, client_id)
        progress(100, "Import complete")
        return sf

    @staticmethod
    def _save_other_itc(s, client_id: int, file_id: int, preview: ImportPreview) -> None:
        """Store GSTR-2B ISD credits and imports; the same record in a re-downloaded file is skipped."""
        import hashlib

        if not preview.other_itc:
            return
        existing = set(s.scalars(select(OtherItc.identity_hash).where(OtherItc.client_id == client_id)))
        rows = []
        for o in preview.other_itc:
            try:
                doc_date = parse_date(o.get("doc_date"))
            except ValueError:
                doc_date = None
            key = "|".join(str(x) for x in (preview.period, o["section"], o["party"], o["doc_type"], o["doc_no"],
                                           doc_date, o["igst"], o["cgst"], o["sgst"], o["cess"]))
            h = hashlib.sha256(key.encode()).hexdigest()[:32]
            if h in existing:
                continue
            existing.add(h)
            rows.append({"client_id": client_id, "source_file_id": file_id, "period": preview.period,
                         "section": o["section"], "party": str(o["party"])[:60], "doc_type": str(o["doc_type"])[:10],
                         "doc_no": str(o["doc_no"])[:60], "doc_date": doc_date, "taxable": o["taxable"],
                         "igst": o["igst"], "cgst": o["cgst"], "sgst": o["sgst"], "cess": o["cess"],
                         "itc_availability": o.get("itc_availability", ""), "identity_hash": h})
        if rows:
            s.execute(insert(OtherItc), rows)

    def import_file(self, client_id: int, path, source, period=None, template=None, user=None) -> tuple[SourceFile, ImportPreview]:
        preview = self.preview(client_id, path, source, period, template)
        return self.commit(client_id, preview, user), preview

    # ---------------------------------------------------------------- query
    def list_files(self, client_id: int) -> list[SourceFile]:
        with self.db.session() as s:
            return list(s.scalars(select(SourceFile).where(SourceFile.client_id == client_id)
                                  .order_by(SourceFile.imported_at, SourceFile.id)))

    def issues_for(self, file_ids: list[int]) -> list[ImportIssue]:
        if not file_ids:
            return []
        with self.db.session() as s:
            return list(s.scalars(select(ImportIssue).where(ImportIssue.source_file_id.in_(file_ids))
                                  .order_by(ImportIssue.source_file_id, ImportIssue.id)))

    @staticmethod
    def _usage(s, file_id: int) -> dict:
        ids = select(Invoice.id).where(Invoice.source_file_id == file_id)
        run_ids = select(ReconLineRow.run_id).where(
            (ReconLineRow.books_invoice_id.in_(ids)) | (ReconLineRow.gstr2b_invoice_id.in_(ids))).distinct()
        return {
            "runs": list(s.scalars(select(ReconRun).where(ReconRun.id.in_(run_ids)).order_by(ReconRun.id))),
            "decisions": s.scalar(select(func.count()).select_from(MatchDecision).where(
                (MatchDecision.books_invoice_id.in_(ids)) | (MatchDecision.gstr2b_invoice_id.in_(ids)))) or 0,
            "reviews": s.scalar(select(func.count()).select_from(ItcReview).where(ItcReview.invoice_id.in_(ids))) or 0,
            "claims": s.scalar(select(func.count()).select_from(ItcClaim).where(ItcClaim.invoice_id.in_(ids))) or 0,
        }

    def usage(self, client_id: int, file_id: int) -> dict:
        """What depends on an import: reconciliation runs, manual match decisions, ITC reviews and claims."""
        with self.db.session() as s:
            sf = s.get(SourceFile, file_id)
            if sf is None or sf.client_id != client_id:
                raise ServiceError(f"Import #{file_id} not found for this client")
            u = self._usage(s, file_id)
            s.expunge_all()
            return u

    def remove_import(self, client_id: int, file_id: int, user: str | None = None, *,
                      with_dependants: bool = False) -> int:
        """Remove an import and its documents (audited). If reconciliations, match decisions or ITC records use
        its documents, they are removed too only with ``with_dependants``; otherwise the import is refused."""
        from .reconciliation import delete_runs

        with self.db.session() as s:
            sf = s.get(SourceFile, file_id)
            if sf is None or sf.client_id != client_id:
                raise ServiceError(f"Import #{file_id} not found for this client")
            u = self._usage(s, file_id)
            if (u["runs"] or u["decisions"] or u["reviews"] or u["claims"]) and not with_dependants:
                used = [f"{len(u['runs'])} reconciliation(s) (#{', #'.join(str(r.id) for r in u['runs'])})"
                        if u["runs"] else "", f"{u['decisions']} manual match decision(s)" if u["decisions"] else "",
                        f"{u['reviews']} ITC review decision(s)" if u["reviews"] else "",
                        f"{u['claims']} ITC claim register entr(ies)" if u["claims"] else ""]
                raise ServiceError(f"Import #{file_id} is used by " + ", ".join(x for x in used if x) +
                                   ". Delete those reconciliations first (History page), or remove the import "
                                   "together with everything that uses it.")
            ids = select(Invoice.id).where(Invoice.source_file_id == file_id)
            if u["runs"]:
                delete_runs(s, u["runs"], user)
            removed = {}
            for model, cond in ((MatchDecision, (MatchDecision.books_invoice_id.in_(ids)) |
                                 (MatchDecision.gstr2b_invoice_id.in_(ids))),
                                (ItcReview, ItcReview.invoice_id.in_(ids)), (ItcClaim, ItcClaim.invoice_id.in_(ids))):
                rows = list(s.scalars(select(model).where(cond)))
                if rows:  # the audit log keeps each removed record in full
                    removed[model.__tablename__] = [
                        {a.key: str(getattr(r, a.key)) for a in model.__mapper__.column_attrs} for r in rows]
                    s.execute(delete(model).where(model.id.in_([r.id for r in rows])))
            count = s.scalar(select(func.count()).select_from(Invoice).where(Invoice.source_file_id == file_id))
            s.execute(delete(ImportIssue).where(ImportIssue.source_file_id == file_id))
            s.execute(delete(OtherItc).where(OtherItc.source_file_id == file_id))
            s.execute(delete(Gstr1Summary).where(Gstr1Summary.source_file_id == file_id))
            s.execute(delete(Gstr1Hsn).where(Gstr1Hsn.source_file_id == file_id))
            s.execute(delete(TdsTcsCredit).where(TdsTcsCredit.source_file_id == file_id))
            keys = set(s.execute(select(Gstr3bEntry.period, Gstr3bEntry.table_code)
                                 .where(Gstr3bEntry.source_file_id == file_id)).all())
            s.execute(delete(Gstr3bEntry).where(Gstr3bEntry.source_file_id == file_id))
            for p, code in keys:  # the previous import of that table becomes current again
                latest = s.scalar(select(Gstr3bEntry).where(
                    Gstr3bEntry.client_id == client_id, Gstr3bEntry.period == p, Gstr3bEntry.table_code == code)
                    .order_by(Gstr3bEntry.source_file_id.desc()).limit(1))
                if latest is not None:
                    latest.active = True
            s.execute(delete(Invoice).where(Invoice.source_file_id == file_id))
            audit(s, "DELETE", "source_file", file_id, {"file": sf.file_name, "documents": count,
                                                        "runs_deleted": [r.id for r in u["runs"]], **removed},
                  user, client_id)
            s.delete(sf)
        return count
