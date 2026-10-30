"""Client-authorised synchronisation through encrypted packages.

Data never leaves the computer unencrypted and is never sent anywhere by this
software. A sync package is written to a folder the user chooses – typically a
folder their own cloud drive (OneDrive, Google Drive, a NAS) already synchronises –
and read on the other computer. The cloud provider only ever stores ciphertext.

Rules
-----
* A package can be created only while the client's written authorisation
  (``SyncAuthorization``) is active – recorded with the signatory, scope, validity and
  the reference of the signed consent – and the authorisation travels in the package.
* Package format: ``FTPSY1`` + 16-byte salt + Fernet token (key derived from the
  password with scrypt) of a compressed JSON snapshot of the client's data, including
  evidence attachments.
* Import replaces the client's snapshot on the receiving computer with the package
  contents; database ids are remapped. Local work since the last sync is a conflict and
  the import stops unless the user explicitly chooses to replace it (an automatic
  backup is taken first). Older or repeated packages from the same origin are refused.
* Letters, working-paper packages and the audit log stay local to each computer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
import zlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Date, DateTime, delete, insert, select

from .. import __version__
from ..db.database import Database
from ..db.models import (
    AppSetting, Attachment, AuditLog, Client, DecimalText, Gstr1Hsn, Gstr1Summary, Gstr9cInput, Gstr3bEntry, ImportIssue, TdsTcsCredit, Invoice, ItcClaim,
    ItcReview, ItcRuleRow, MatchDecision, OtherItc, ReconLineRow, ReconRun, SourceFile, SyncAuthorization, SyncState,
    Vendor,
)
from .auth import Session, require
from .clients import FIELDS as CLIENT_FIELDS
from .common import ServiceError, audit
from .security import _key

MAGIC = b"FTPSY1"
FORMAT = 1
# Import order; parents first. Each entry: model, {column: referenced table} for ids to remap.
TABLES = [
    (SourceFile, {}),
    (ImportIssue, {"source_file_id": "source_files"}),
    (Invoice, {"source_file_id": "source_files"}),
    (Gstr1Summary, {"source_file_id": "source_files"}),
    (Gstr1Hsn, {"source_file_id": "source_files"}),
    (TdsTcsCredit, {"source_file_id": "source_files"}),
    (Gstr3bEntry, {"source_file_id": "source_files"}),
    (OtherItc, {"source_file_id": "source_files"}),
    (ReconRun, {}),
    (ReconLineRow, {"run_id": "recon_runs", "books_invoice_id": "invoices", "gstr2b_invoice_id": "invoices"}),
    (MatchDecision, {"run_id": "recon_runs", "books_invoice_id": "invoices", "gstr2b_invoice_id": "invoices"}),
    (ItcReview, {"invoice_id": "invoices"}),
    (ItcClaim, {"invoice_id": "invoices", "run_id": "recon_runs"}),
    (ItcRuleRow, {}),
    (Vendor, {}),
    (Attachment, {"run_id": "recon_runs", "books_invoice_id": "invoices", "gstr2b_invoice_id": "invoices"}),
    (Gstr9cInput, {}),
]
SYNC_ACTIONS = {"SYNC_EXPORT", "SYNC_IMPORT", "SYNC_AUTHORISE", "SYNC_REVOKE", "EXPORT", "EXPORT_AUDIT", "LOGIN",
                "LOGIN_FAILED"}


def _encode(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _decoder(col):
    t = col.type
    if isinstance(t, DecimalText):
        return lambda v: None if v is None else Decimal(v)
    if isinstance(t, DateTime):
        return lambda v: None if v is None else datetime.fromisoformat(v)
    if isinstance(t, Date):
        return lambda v: None if v is None else date.fromisoformat(v)
    return lambda v: v


def _client_filter(model, client_id: int, ids: dict[str, list[int]]):
    t = model.__table__
    if "client_id" in t.c:
        return t.c.client_id == client_id
    if model is ImportIssue:
        return t.c.source_file_id.in_(ids["source_files"] or [-1])
    if model is ReconLineRow:
        return t.c.run_id.in_(ids["recon_runs"] or [-1])
    raise AssertionError(model)


class SyncService:
    def __init__(self, db: Database):
        self.db = db
        self.attachments_root = db.data_dir / "attachments"

    # ------------------------------------------------------------ identity
    def installation_id(self) -> str:
        with self.db.session() as s:
            row = s.get(AppSetting, "installation_id")
            if row is None:
                row = AppSetting(key="installation_id", value_json=json.dumps(uuid.uuid4().hex))
                s.add(row)
            return json.loads(row.value_json)

    # ------------------------------------------------------- authorisation
    def authorise(self, client_id: int, granted_by: str, valid_until: date, evidence: str, by: Session,
                  scope: str = "Reconciliation data, reports and evidence for synchronisation between the firm's "
                               "computers through an encrypted cloud folder",
                  granted_on: date | None = None) -> SyncAuthorization:
        require(by, "sync")
        granted_on = granted_on or date.today()
        if not granted_by.strip() or not evidence.strip():
            raise ServiceError("Record the client's authorised signatory and the consent reference")
        if valid_until <= granted_on:
            raise ServiceError("The authorisation must be valid beyond the date it was granted")
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            a = SyncAuthorization(client_id=client_id, granted_by=granted_by.strip(), scope=scope,
                                  granted_on=granted_on, expires_on=valid_until, evidence=evidence.strip(),
                                  recorded_by=by.username)
            s.add(a)
            s.flush()
            audit(s, "SYNC_AUTHORISE", "client", client_id, {"granted_by": granted_by, "valid_until": valid_until,
                                                              "evidence": evidence}, by.username, client_id)
            s.expunge(a)
        return a

    def revoke(self, auth_id: int, by: Session) -> None:
        require(by, "sync")
        with self.db.session() as s:
            a = s.get(SyncAuthorization, auth_id)
            if a is None:
                raise ServiceError(f"Authorisation {auth_id} not found")
            a.revoked_at = datetime.now()
            audit(s, "SYNC_REVOKE", "client", a.client_id, {"authorisation": auth_id}, by.username, a.client_id)

    def active_authorisation(self, client_id: int, on: date | None = None) -> SyncAuthorization | None:
        on = on or date.today()
        with self.db.session() as s:
            a = s.scalar(select(SyncAuthorization).where(
                SyncAuthorization.client_id == client_id, SyncAuthorization.revoked_at.is_(None),
                SyncAuthorization.granted_on <= on, SyncAuthorization.expires_on >= on)
                .order_by(SyncAuthorization.expires_on.desc()).limit(1))
            if a is not None:
                s.expunge(a)
            return a

    def authorisations(self, client_id: int) -> list[SyncAuthorization]:
        with self.db.session() as s:
            rows = list(s.scalars(select(SyncAuthorization).where(SyncAuthorization.client_id == client_id)
                                  .order_by(SyncAuthorization.id.desc())))
            for r in rows:
                s.expunge(r)
        return rows

    # -------------------------------------------------------------- export
    def export_package(self, client_id: int, folder: str | Path, password: str, by: Session) -> Path:
        require(by, "sync")
        if len(password) < 10:
            raise ServiceError("Sync password must have at least 10 characters")
        auth = self.active_authorisation(client_id)
        if auth is None:
            raise ServiceError("No active client authorisation for synchronisation – record the client's consent "
                               "first")
        origin = self.installation_id()
        with self.db.session() as s:
            client = s.get(Client, client_id)
            ids: dict[str, list[int]] = {}
            tables = {}
            for model, _refs in TABLES:
                t = model.__table__
                rows = [dict(r._mapping) for r in s.execute(select(t).where(_client_filter(model, client_id, ids)))]
                ids[t.name] = [r["id"] for r in rows]
                tables[t.name] = [{k: _encode(v) for k, v in r.items()} for r in rows]
            files = {}
            for a in tables["attachments"]:
                p = Path(a["stored_path"])
                if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == a["sha256"]:
                    files[a["sha256"]] = base64.b64encode(p.read_bytes()).decode()
            state = s.get(SyncState, client.gstin) or SyncState(client_gstin=client.gstin, last_export_seq=0,
                                                                last_import_seq=0, last_import_origin="")
            s.add(state)
            seq = max(state.last_export_seq or 0, state.last_import_seq or 0) + 1
            state.last_export_seq = seq
            state.last_sync_at = datetime.now()
            payload = {
                "format": FORMAT, "app_version": __version__, "origin": origin, "seq": seq,
                "created_at": datetime.now().isoformat(timespec="seconds"), "created_by": by.username,
                "client": {"gstin": client.gstin, "pan": client.pan, "state_code": client.state_code,
                           **{k: getattr(client, k) for k in CLIENT_FIELDS}},
                "authorisation": {"granted_by": auth.granted_by, "scope": auth.scope,
                                  "granted_on": auth.granted_on.isoformat(), "expires_on": auth.expires_on.isoformat(),
                                  "evidence": auth.evidence, "recorded_by": auth.recorded_by},
                "tables": tables, "files": files,
            }
            raw = zlib.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 9)
            salt = os.urandom(16)
            token = Fernet(_key(password, salt)).encrypt(raw)
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"FTP_SYNC_{client.gstin}_{origin[:8]}_{seq:06d}.ftpsync"
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(MAGIC + salt + token)
            tmp.replace(target)
            audit(s, "SYNC_EXPORT", "client", client_id, {"file": target.name, "seq": seq, "bytes": len(raw),
                                                          "rows": {k: len(v) for k, v in tables.items()}},
                  by.username, client_id)
        return target

    # -------------------------------------------------------------- import
    @staticmethod
    def read_package(path: str | Path, password: str) -> dict:
        raw = Path(path).read_bytes()
        if not raw.startswith(MAGIC):
            raise ServiceError("Not a FIN TAX PRO sync package")
        salt, token = raw[len(MAGIC):len(MAGIC) + 16], raw[len(MAGIC) + 16:]
        try:
            data = json.loads(zlib.decompress(Fernet(_key(password, salt)).decrypt(token)))
        except InvalidToken:
            raise ServiceError("Wrong password or damaged sync package") from None
        if data.get("format") != FORMAT:
            raise ServiceError(f"Unsupported sync package format {data.get('format')}")
        return data

    def local_changes(self, gstin: str) -> int:
        """Audited changes to the client on this computer since its last sync."""
        with self.db.session() as s:
            client = s.scalar(select(Client).where(Client.gstin == gstin))
            if client is None:
                return 0
            state = s.get(SyncState, gstin)
            q = select(AuditLog).where(AuditLog.client_id == client.id, AuditLog.action.not_in(SYNC_ACTIONS))
            if state is not None and state.last_sync_at is not None:
                q = q.where(AuditLog.at > state.last_sync_at)
            return len(s.scalars(q).all())

    def inspect(self, path: str | Path, password: str) -> dict:
        d = self.read_package(path, password)
        return {"client": d["client"], "origin": d["origin"], "seq": d["seq"], "created_at": d["created_at"],
                "created_by": d["created_by"], "authorisation": d["authorisation"],
                "rows": {k: len(v) for k, v in d["tables"].items()},
                "local_changes": self.local_changes(d["client"]["gstin"])}

    def import_package(self, path: str | Path, password: str, by: Session, replace_local: bool = False) -> dict:
        require(by, "sync")
        data = self.read_package(path, password)
        auth = data["authorisation"]
        today = date.today()
        if not (date.fromisoformat(auth["granted_on"]) <= today <= date.fromisoformat(auth["expires_on"])):
            raise ServiceError(f"The client's authorisation in this package expired on {auth['expires_on']}")
        if data["origin"] == self.installation_id():
            raise ServiceError("This package was created on this computer")
        gstin = data["client"]["gstin"]
        with self.db.session() as s:
            state = s.get(SyncState, gstin)
            if state is not None and state.last_import_origin == data["origin"] and data["seq"] <= state.last_import_seq:
                raise ServiceError(f"Package {data['seq']} is not newer than the last one imported from that "
                                   f"computer ({state.last_import_seq})")
        changes = self.local_changes(gstin)
        if changes and not replace_local:
            raise ServiceError(f"Conflict: {changes} change(s) were made to this client on this computer since the "
                               "last sync. Export them first, or choose to replace the local data.")
        safety = self.db.backup(suffix="presync") if changes else None
        counts: dict[str, int] = {}
        with self.db.session() as s:
            client = s.scalar(select(Client).where(Client.gstin == gstin))
            info = data["client"]
            if client is None:
                client = Client(gstin=gstin, pan=info["pan"], state_code=info["state_code"],
                                **{k: info.get(k) or "" for k in CLIENT_FIELDS})
                s.add(client)
                s.flush()
            else:
                for k in CLIENT_FIELDS:
                    setattr(client, k, info.get(k) or "")
            cid = client.id
            # remove the current snapshot (children first)
            existing: dict[str, list[int]] = {}
            for model, _ in TABLES:
                t = model.__table__
                existing[t.name] = list(s.scalars(select(t.c.id).where(_client_filter(model, cid, existing))))
            for model, _ in reversed(TABLES):
                t = model.__table__
                if existing[t.name]:
                    s.execute(delete(t).where(t.c.id.in_(existing[t.name])))
            # insert the package snapshot with new ids
            id_map: dict[str, dict[int, int]] = {}
            for model, refs in TABLES:
                t = model.__table__
                dec = {c.name: _decoder(c) for c in t.columns}
                mapping = id_map.setdefault(t.name, {})
                for row in data["tables"].get(t.name, []):
                    vals = {k: dec[k](v) for k, v in row.items() if k in dec and k != "id"}
                    if "client_id" in t.c:
                        vals["client_id"] = cid
                    for col, ref in refs.items():
                        if vals.get(col) is not None:
                            vals[col] = id_map[ref].get(vals[col])
                    if model is ReconRun:
                        vals["source_file_ids"] = json.dumps(
                            [id_map["source_files"][i] for i in json.loads(vals.get("source_file_ids") or "[]")
                             if i in id_map["source_files"]])
                    if model is Attachment:
                        content = data["files"].get(vals["sha256"])
                        target = self.attachments_root / str(cid) / vals["sha256"][:2] / \
                            f"{vals['sha256']}{Path(vals['file_name']).suffix.lower()}"
                        if content is not None and not target.exists():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(base64.b64decode(content))
                        vals["stored_path"] = str(target)
                    new_id = s.execute(insert(t).values(**vals)).inserted_primary_key[0]
                    mapping[row["id"]] = new_id
                counts[t.name] = len(mapping)
            if not any(a.granted_on.isoformat() == auth["granted_on"] and a.granted_by == auth["granted_by"]
                       for a in s.scalars(select(SyncAuthorization).where(SyncAuthorization.client_id == cid))):
                s.add(SyncAuthorization(client_id=cid, granted_by=auth["granted_by"], scope=auth["scope"],
                                        granted_on=date.fromisoformat(auth["granted_on"]),
                                        expires_on=date.fromisoformat(auth["expires_on"]),
                                        evidence=auth["evidence"], recorded_by=auth["recorded_by"]))
            state = s.get(SyncState, gstin) or SyncState(client_gstin=gstin, last_export_seq=0)
            s.add(state)
            state.last_import_seq, state.last_import_origin = data["seq"], data["origin"]
            state.last_sync_at = datetime.now()
            audit(s, "SYNC_IMPORT", "client", cid, {"file": Path(path).name, "origin": data["origin"],
                                                    "seq": data["seq"], "rows": counts, "replaced_local": changes,
                                                    "safety_backup": str(safety) if safety else None},
                  by.username, cid)
        return {"client_id": cid, "rows": counts, "replaced_local_changes": changes,
                "safety_backup": str(safety) if safety else None}
