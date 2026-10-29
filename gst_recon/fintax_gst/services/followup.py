"""Vendor follow-up register and supporting-evidence attachments."""
from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import select

from ..core.gstin import normalize_gstin, validate_gstin
from ..db.database import Database
from ..db.models import Attachment, ReconLineRow, ReconRun, Vendor
from .common import ServiceError, audit

FOLLOWUP_STATUSES = ["Not contacted", "Mail sent", "Reminder sent", "Supplier confirmed correction",
                     "Supplier disputes", "Closed"]
VENDOR_FIELDS = ("name", "contact_person", "email", "phone", "followup_status", "next_followup", "remarks")
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


class VendorService:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, client_id: int, gstin: str, user: str | None = None, **fields) -> Vendor:
        gstin = normalize_gstin(gstin)
        if not validate_gstin(gstin)[0]:
            raise ServiceError(f"Invalid supplier GSTIN {gstin}")
        unknown = set(fields) - set(VENDOR_FIELDS)
        if unknown:
            raise ServiceError(f"Unknown vendor field(s): {', '.join(sorted(unknown))}")
        status = fields.get("followup_status")
        if status and status not in FOLLOWUP_STATUSES:
            raise ServiceError(f"Follow-up status must be one of: {', '.join(FOLLOWUP_STATUSES)}")
        if isinstance(fields.get("next_followup"), str):
            fields["next_followup"] = date.fromisoformat(fields["next_followup"]) if fields["next_followup"] else None
        with self.db.session() as s:
            v = s.scalar(select(Vendor).where(Vendor.client_id == client_id, Vendor.gstin == gstin))
            before = {k: getattr(v, k) for k in fields} if v else {}
            if v is None:
                v = Vendor(client_id=client_id, gstin=gstin)
                s.add(v)
            for k, val in fields.items():
                setattr(v, k, val if val is not None or k == "next_followup" else "")
            s.flush()
            audit(s, "UPSERT", "vendor", gstin, {"before": before, "after": fields}, user, client_id)
        return v

    def get(self, client_id: int, gstin: str) -> Vendor | None:
        with self.db.session() as s:
            return s.scalar(select(Vendor).where(Vendor.client_id == client_id, Vendor.gstin == normalize_gstin(gstin)))

    def all(self, client_id: int) -> dict[str, Vendor]:
        with self.db.session() as s:
            return {v.gstin: v for v in s.scalars(select(Vendor).where(Vendor.client_id == client_id))}

    def due(self, client_id: int, on: date | None = None) -> list[Vendor]:
        on = on or date.today()
        with self.db.session() as s:
            return list(s.scalars(select(Vendor).where(
                Vendor.client_id == client_id, Vendor.next_followup.is_not(None), Vendor.next_followup <= on,
                Vendor.followup_status != "Closed").order_by(Vendor.next_followup)))


class AttachmentService:
    """Evidence files are copied into ``<database folder>/attachments`` and verified by SHA-256."""

    def __init__(self, db: Database):
        self.db = db
        self.root = Path(db.path).parent / "attachments"

    def add(self, run_id: int, line_no: int, path: str | Path, user: str | None = None,
            description: str = "") -> Attachment:
        path = Path(path)
        if not path.is_file():
            raise ServiceError(f"File not found: {path}")
        size = path.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise ServiceError("Attachment larger than 50 MB")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            row = s.scalar(select(ReconLineRow).where(ReconLineRow.run_id == run_id, ReconLineRow.line_no == line_no))
            if run is None or row is None:
                raise ServiceError(f"Line {line_no} not found in run {run_id}")
            target = self.root / str(run.client_id) / digest[:2] / f"{digest}{path.suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
            att = Attachment(client_id=run.client_id, run_id=run_id, line_no=line_no,
                             books_invoice_id=row.books_invoice_id, gstr2b_invoice_id=row.gstr2b_invoice_id,
                             file_name=path.name, stored_path=str(target), sha256=digest, size_bytes=size,
                             description=description, user=user or "")
            s.add(att)
            s.flush()
            audit(s, "ATTACH", "recon_line", f"{run_id}:{line_no}",
                  {"file": path.name, "sha256": digest, "description": description}, user, run.client_id)
        return att

    def for_line(self, run_id: int, line_no: int) -> list[Attachment]:
        """Evidence for the documents on this line, including files attached in earlier runs."""
        with self.db.session() as s:
            row = s.scalar(select(ReconLineRow).where(ReconLineRow.run_id == run_id, ReconLineRow.line_no == line_no))
            if row is None:
                return []
            cond = (Attachment.run_id == run_id) & (Attachment.line_no == line_no)
            if row.books_invoice_id:
                cond = cond | (Attachment.books_invoice_id == row.books_invoice_id)
            if row.gstr2b_invoice_id:
                cond = cond | (Attachment.gstr2b_invoice_id == row.gstr2b_invoice_id)
            run = s.get(ReconRun, run_id)
            return list(s.scalars(select(Attachment).where(Attachment.client_id == run.client_id, cond)
                                  .order_by(Attachment.id)))

    def counts(self, run_id: int) -> dict[int, int]:
        with self.db.session() as s:
            run = s.get(ReconRun, run_id)
            atts = s.scalars(select(Attachment).where(Attachment.client_id == run.client_id)).all()
            if not atts:
                return {}
            by_doc: dict[int, int] = {}
            for a in atts:
                for d in {a.books_invoice_id, a.gstr2b_invoice_id} - {None}:
                    by_doc[d] = by_doc.get(d, 0) + 1
            out = {}
            for r in s.scalars(select(ReconLineRow).where(ReconLineRow.run_id == run_id)):
                n = max(by_doc.get(r.books_invoice_id, 0), by_doc.get(r.gstr2b_invoice_id, 0))
                if n:
                    out[r.line_no] = n
            return out

    @staticmethod
    def verify(att: Attachment) -> bool:
        p = Path(att.stored_path)
        return p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == att.sha256
