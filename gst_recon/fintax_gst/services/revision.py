"""Replace an import with a revised file (e.g. the client's corrected register for the same month).

The documents of the two files are paired by party GSTIN, document type and number:

* **unchanged** – kept as they are (same database record): review statuses, matches, ITC claims and evidence
  stay with them;
* **changed** – the stored record is corrected in place (its history stays; the change is audited);
* **added** – saved as new documents (unless the same document is already in another import);
* **removed** – deleted. If a reconciliation, a manual match decision or the ITC claim register uses one of
  them, the replacement is refused unless the user agrees to remove those too (as when removing an import).

Everything happens in one transaction, and the audit log keeps the old file's name and every change.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, func, insert, select

from ..core.models import Source
from ..db.database import Database
from ..db.models import (
    Gstr1Hsn, Gstr1Summary, ImportIssue, Invoice, ItcClaim, ItcReview, MatchDecision, OtherItc, ReconLineRow,
    ReconRun, SourceFile,
)
from ..importers.pipeline import ImportPreview
from .common import ServiceError, audit, dumps
from .imports import ImportService, record_fields

_COMPARED = ("supplier_name", "invoice_date", "period", "taxable", "igst", "cgst", "sgst", "cess", "invoice_value",
             "place_of_supply", "reverse_charge", "supply_type", "itc_availability", "description", "hsn_json")
INVOICE_SOURCES = {s.value for s in Source}


def _key(gstin: str, doc_type: str, number_norm: str, amendment: bool) -> tuple:
    return (gstin or "", doc_type, number_norm, bool(amendment))


@dataclass
class Change:
    invoice_id: int
    number: str
    party: str
    differences: dict[str, tuple]  # field -> (old, new)


@dataclass
class RevisionDiff:
    old_file_id: int
    old_file: str
    new_file: str
    unchanged: list[tuple[int, object]] = field(default_factory=list)  # (invoice id, new record)
    changed: list[tuple[Change, object]] = field(default_factory=list)
    added: list[object] = field(default_factory=list)  # new records
    already_elsewhere: list[object] = field(default_factory=list)  # added, but present in another import
    removed: list[Invoice] = field(default_factory=list)
    runs_affected: list[ReconRun] = field(default_factory=list)  # runs using removed documents
    removed_in_use: int = 0  # removed documents with match decisions / ITC reviews / claims

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.runs_affected or self.removed_in_use)


class RevisionService:
    def __init__(self, db: Database):
        self.db = db

    def compare(self, client_id: int, old_file_id: int, preview: ImportPreview) -> RevisionDiff:
        with self.db.session() as s:
            old = s.get(SourceFile, old_file_id)
            if old is None or old.client_id != client_id:
                raise ServiceError(f"Import #{old_file_id} not found for this client")
            if old.source_type != preview.source.value or old.source_type not in INVOICE_SOURCES:
                raise ServiceError(f"Import #{old_file_id} is a {old.source_type} file – the revised file must be of "
                                   f"the same kind (read as {preview.source.value})")
            if preview.already_imported_file_id:
                raise ServiceError(f"{preview.file_name} is already imported (import #"
                                   f"{preview.already_imported_file_id})")
            olds = list(s.scalars(select(Invoice).where(Invoice.source_file_id == old_file_id).order_by(Invoice.id)))
            diff = RevisionDiff(old_file_id, old.file_name, preview.file_name)
            pool: dict[tuple, list[Invoice]] = defaultdict(list)
            for inv in olds:
                pool[_key(inv.supplier_gstin, inv.doc_type, inv.invoice_no_norm, inv.is_amendment)].append(inv)
            elsewhere = set(s.scalars(select(Invoice.identity_hash).where(
                Invoice.client_id == client_id, Invoice.source_file_id != old_file_id)))
            for rec in preview.records:
                k = _key(rec.supplier_gstin, rec.doc_type.value, rec.invoice_no_norm, rec.is_amendment)
                if pool.get(k):
                    inv = pool[k].pop(0)
                    new_vals = record_fields(rec)
                    differences = {f: (getattr(inv, f), new_vals[f]) for f in _COMPARED
                                   if (getattr(inv, f) or None) != (new_vals[f] or None)}
                    if differences:
                        diff.changed.append((Change(inv.id, inv.invoice_no, inv.supplier_name or inv.supplier_gstin,
                                                    differences), rec))
                    else:
                        diff.unchanged.append((inv.id, rec))
                elif rec.identity_hash() in elsewhere:
                    diff.already_elsewhere.append(rec)
                else:
                    diff.added.append(rec)
            diff.removed = [inv for rest in pool.values() for inv in rest]
            ids = [inv.id for inv in diff.removed]
            if ids:
                run_ids = select(ReconLineRow.run_id).where(ReconLineRow.books_invoice_id.in_(ids) |
                                                            ReconLineRow.gstr2b_invoice_id.in_(ids)).distinct()
                diff.runs_affected = list(s.scalars(select(ReconRun).where(ReconRun.id.in_(run_ids))
                                                    .order_by(ReconRun.id)))
                diff.removed_in_use = sum(s.scalar(select(func.count()).select_from(m).where(c)) or 0 for m, c in (
                    (MatchDecision, MatchDecision.books_invoice_id.in_(ids) | MatchDecision.gstr2b_invoice_id.in_(ids)),
                    (ItcReview, ItcReview.invoice_id.in_(ids)), (ItcClaim, ItcClaim.invoice_id.in_(ids))))
            s.expunge_all()
        return diff

    def replace(self, client_id: int, old_file_id: int, preview: ImportPreview, user: str | None = None,
                confirmed: bool = False):
        """Apply the revision; returns (new source file, diff)."""
        from .reconciliation import delete_runs

        diff = self.compare(client_id, old_file_id, preview)
        if diff.needs_confirmation and not confirmed:
            raise ServiceError(f"{len(diff.removed)} document(s) are no longer in the revised file, and "
                               f"{len(diff.runs_affected)} reconciliation(s) / {diff.removed_in_use} decision(s) or ITC "
                               "record(s) use them – confirm to remove those too.")
        with self.db.session() as s:
            sf = SourceFile(client_id=client_id, source_type=preview.source.value, file_name=preview.file_name,
                            file_path=str(preview.file_path.resolve()), sha256=preview.sha256, layout=preview.layout,
                            period=preview.period, rows_read=preview.total_rows,
                            documents_imported=len(diff.unchanged) + len(diff.changed) + len(diff.added),
                            rows_rejected=preview.rejected_rows, documents_skipped_existing=len(diff.already_elsewhere),
                            mapping_json=dumps({k: v.fields for k, v in preview.mappings.items()}),
                            warnings_json=dumps(preview.file_warnings), imported_by=user or "")
            s.add(sf)
            s.flush()
            removed_ids = [inv.id for inv in diff.removed]
            if removed_ids:
                if diff.runs_affected:
                    delete_runs(s, [s.get(ReconRun, r.id) for r in diff.runs_affected], user)
                for model, cond in (
                        (MatchDecision, MatchDecision.books_invoice_id.in_(removed_ids) |
                         MatchDecision.gstr2b_invoice_id.in_(removed_ids)),
                        (ItcReview, ItcReview.invoice_id.in_(removed_ids)),
                        (ItcClaim, ItcClaim.invoice_id.in_(removed_ids))):
                    s.execute(delete(model).where(cond))
                s.execute(delete(Invoice).where(Invoice.id.in_(removed_ids)))
            for inv_id, rec in diff.unchanged:
                inv = s.get(Invoice, inv_id)
                inv.source_file_id, inv.source_rows = sf.id, rec.source_rows[:200]
            for change, rec in diff.changed:
                inv = s.get(Invoice, change.invoice_id)
                for k, v in record_fields(rec).items():
                    setattr(inv, k, v)
                inv.source_file_id = sf.id
            if diff.added:
                s.execute(insert(Invoice), [{"client_id": client_id, "source_file_id": sf.id,
                                             "source_type": r.source.value, **record_fields(r)} for r in diff.added])
            # the old file's own records (import log, GSTR-1 summaries, ISD / import ITC) give way to the new file's
            for model in (ImportIssue, OtherItc, Gstr1Summary, Gstr1Hsn):
                s.execute(delete(model).where(model.source_file_id == old_file_id))
            issues = [{"source_file_id": sf.id, "sheet": i.sheet, "row_ref": i.row[:200], "severity": i.severity,
                       "message": i.message, "raw_json": dumps(i.raw)} for i in preview.issues]
            if issues:
                s.execute(insert(ImportIssue), issues)
            ImportService._save_other_itc(s, client_id, sf.id, preview)
            if preview.outward_summary:
                s.execute(insert(Gstr1Summary), [{"client_id": client_id, "source_file_id": sf.id,
                                                  "period": preview.period, **row} for row in preview.outward_summary])
            if preview.hsn_summary:
                s.execute(insert(Gstr1Hsn), [{"client_id": client_id, "source_file_id": sf.id,
                                              "period": preview.period, **row} for row in preview.hsn_summary])
            s.execute(delete(SourceFile).where(SourceFile.id == old_file_id))
            audit(s, "REPLACE", "source_file", sf.id, {
                "old_file": diff.old_file, "old_import": old_file_id, "new_file": preview.file_name,
                "unchanged": len(diff.unchanged), "added": len(diff.added), "removed": len(removed_ids),
                "runs_deleted": [r.id for r in diff.runs_affected],
                "changed": [{"invoice": c.number, "party": c.party,
                             **{f: [str(a), str(b)] for f, (a, b) in c.differences.items()}} for c, _r in diff.changed],
                "removed_documents": [f"{inv.supplier_gstin} {inv.invoice_no}" for inv in diff.removed]},
                  user, client_id)
            s.flush()
            s.expunge(sf)
        return sf, diff
