"""Encrypted backups, automatic backups with retention, client data purge and audit export.

Encrypted backup format: ``FTPBK1`` + 16-byte salt + Fernet token (AES-128-CBC with
HMAC-SHA256), the key derived from the password with scrypt. The SQLite database
itself is not encrypted; protect the computer with full-disk encryption (e.g.
BitLocker) and use encrypted backups for anything that leaves it.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select

from ..db.database import Database
from ..db.models import (
    AppSetting, Attachment, AuditLog, Client, Gstr1Summary, Gstr3bEntry, LetterRecord, SyncAuthorization,
    WorkingPaper, ImportIssue, Invoice, ItcClaim, ItcReview, ItcRuleRow,
    MatchDecision, OtherItc, ReconLineRow, ReconRun, SourceFile, Vendor,
)
from .auth import Session, require
from .common import ServiceError, audit

MAGIC = b"FTPBK1"
DEFAULTS = {"auto_backup": True, "backup_interval_hours": 24, "backup_keep": 14, "backup_retention_days": 90}


def _key(password: str, salt: bytes) -> bytes:
    return base64.urlsafe_b64encode(hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32))


class SecurityService:
    def __init__(self, db: Database):
        self.db = db
        self.backup_dir = Path(db.path).parent / "backups"

    # -------------------------------------------------------------- settings
    def setting(self, key: str):
        with self.db.session() as s:
            row = s.get(AppSetting, key)
        return json.loads(row.value_json) if row else DEFAULTS.get(key)

    def set_setting(self, key: str, value, by: Session | None) -> None:
        require(by, "settings")
        with self.db.session() as s:
            row = s.get(AppSetting, key)
            before = json.loads(row.value_json) if row else None
            if row is None:
                row = AppSetting(key=key, value_json="null")
                s.add(row)
            row.value_json = json.dumps(value)
            audit(s, "SETTING", "app_settings", key, {"before": before, "after": value}, by.username)

    # --------------------------------------------------------------- backups
    def encrypted_backup(self, target: str | Path, password: str, by: Session | None = None) -> Path:
        if len(password) < 8:
            raise ServiceError("Backup password must have at least 8 characters")
        target = Path(target)
        with tempfile.TemporaryDirectory() as tmp:
            plain = self.db.backup(Path(tmp) / "plain.db")
            data = plain.read_bytes()
        salt = os.urandom(16)
        token = Fernet(_key(password, salt)).encrypt(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(MAGIC + salt + token)
        with self.db.session() as s:
            audit(s, "BACKUP_ENCRYPTED", "database", str(target), {"bytes": len(data)}, by.username if by else "")
        return target

    def decrypt_backup(self, source: str | Path, password: str, target: str | Path) -> Path:
        raw = Path(source).read_bytes()
        if not raw.startswith(MAGIC):
            raise ServiceError("Not a FIN TAX PRO encrypted backup")
        salt, token = raw[len(MAGIC):len(MAGIC) + 16], raw[len(MAGIC) + 16:]
        try:
            data = Fernet(_key(password, salt)).decrypt(token)
        except InvalidToken:
            raise ServiceError("Wrong password or damaged backup file") from None
        target = Path(target)
        target.write_bytes(data)
        return target

    def restore_encrypted(self, source: str | Path, password: str, by: Session | None) -> Path:
        require(by, "restore")
        with tempfile.TemporaryDirectory() as tmp:
            plain = self.decrypt_backup(source, password, Path(tmp) / "restore.db")
            safety = self.db.restore(plain)
        with self.db.session() as s:
            audit(s, "RESTORE", "database", str(source), {"previous_saved_as": str(safety)},
                  by.username if by else "")
        return safety

    def auto_backup(self, force: bool = False) -> Path | None:
        """Take a backup if the last automatic one is older than the interval, then apply retention."""
        if not self.setting("auto_backup") and not force:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        autos = sorted(self.backup_dir.glob("fintaxpro-*-auto.db"), key=lambda p: p.stat().st_mtime)
        interval = timedelta(hours=float(self.setting("backup_interval_hours")))
        made = None
        if force or not autos or datetime.now() - datetime.fromtimestamp(autos[-1].stat().st_mtime) >= interval:
            made = self.db.backup(suffix="auto")
        self.apply_retention()
        return made

    def apply_retention(self) -> list[Path]:
        """Keep at most ``backup_keep`` automatic backups and none older than ``backup_retention_days``
        – except that the newest backup is always kept."""
        keep = int(self.setting("backup_keep"))
        cutoff = datetime.now() - timedelta(days=int(self.setting("backup_retention_days")))
        autos = sorted(self.backup_dir.glob("fintaxpro-*-auto.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = []
        for i, p in enumerate(autos):
            too_old = datetime.fromtimestamp(p.stat().st_mtime) < cutoff
            if i >= max(keep, 1) or (too_old and i >= 1):
                secure_unlink(p)
                removed.append(p)
        return removed

    # ------------------------------------------------------------ deletion
    def purge_client(self, client_id: int, confirm_gstin: str, by: Session | None) -> dict:
        """Permanently delete a client and all its data (secure delete + VACUUM)."""
        require(by, "delete_data")
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            if confirm_gstin.strip().upper() != client.gstin:
                raise ServiceError("Type the client's GSTIN to confirm deletion")
            files = [a.stored_path for a in s.scalars(select(Attachment).where(Attachment.client_id == client_id))]
            run_ids = select(ReconRun.id).where(ReconRun.client_id == client_id)
            file_ids = select(SourceFile.id).where(SourceFile.client_id == client_id)
            counts = {}
            for model, cond in (
                (ReconLineRow, ReconLineRow.run_id.in_(run_ids)), (Attachment, Attachment.client_id == client_id),
                (MatchDecision, MatchDecision.client_id == client_id), (ItcClaim, ItcClaim.client_id == client_id),
                (ItcReview, ItcReview.client_id == client_id), (ItcRuleRow, ItcRuleRow.client_id == client_id),
                (Vendor, Vendor.client_id == client_id), (ReconRun, ReconRun.client_id == client_id),
                (Gstr3bEntry, Gstr3bEntry.client_id == client_id), (OtherItc, OtherItc.client_id == client_id),
                (Gstr1Summary, Gstr1Summary.client_id == client_id),
                (SyncAuthorization, SyncAuthorization.client_id == client_id),
                (LetterRecord, LetterRecord.client_id == client_id),
                (WorkingPaper, WorkingPaper.client_id == client_id),
                (ImportIssue, ImportIssue.source_file_id.in_(file_ids)), (Invoice, Invoice.client_id == client_id),
                (SourceFile, SourceFile.client_id == client_id),
            ):
                counts[model.__tablename__] = s.execute(delete(model).where(cond)).rowcount
            # Audit entries of this client lose their details; the purge itself stays on record.
            for a in s.scalars(select(AuditLog).where(AuditLog.client_id == client_id)):
                a.details_json = "{}"
            gstin = client.gstin
            s.delete(client)
            audit(s, "PURGE_CLIENT", "client", client_id, {"gstin": gstin, "rows": counts}, by.username, None)
        for f in files:
            secure_unlink(Path(f))
        att_dir = Path(self.db.path).parent / "attachments" / str(client_id)
        if att_dir.exists():
            for p in sorted(att_dir.rglob("*"), reverse=True):
                p.rmdir() if p.is_dir() else secure_unlink(p)
            att_dir.rmdir()
        with self.db.engine.connect() as conn:
            conn.exec_driver_sql("VACUUM")
        return counts

    # ----------------------------------------------------------------- audit
    def audit_rows(self, client_id: int | None = None, since: datetime | None = None, limit: int = 5000):
        with self.db.session() as s:
            q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
            if client_id is not None:
                q = q.where(AuditLog.client_id == client_id)
            if since is not None:
                q = q.where(AuditLog.at >= since)
            return list(s.scalars(q))

    def export_audit(self, target: str | Path, client_id: int | None = None, by: Session | None = None) -> Path:
        require(by, "export")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self.audit_rows(client_id, limit=1_000_000)
        with open(target, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "at_utc", "user", "client_id", "action", "entity", "entity_id", "details"])
            for a in reversed(rows):
                w.writerow([a.id, f"{a.at:%Y-%m-%d %H:%M:%S}", a.user, a.client_id or "", a.action, a.entity,
                            a.entity_id, a.details_json])
        with self.db.session() as s:
            audit(s, "EXPORT_AUDIT", "audit_log", str(target), {"rows": len(rows), "client_id": client_id},
                  by.username if by else "")
        return target


def secure_unlink(path: Path) -> None:
    """Overwrite a file with random bytes before deleting it (best effort on SSDs/journaling filesystems)."""
    path = Path(path)
    if not path.exists():
        return
    size = path.stat().st_size
    with open(path, "r+b") as fh:
        fh.write(os.urandom(size))
        fh.flush()
        os.fsync(fh.fileno())
    path.unlink()


def integrity_ok(path: str | Path) -> bool:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

