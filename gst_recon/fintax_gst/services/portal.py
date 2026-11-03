"""GST portal section: links to the official portal, recognition of the files the user downloads there, and the
electronic cash / credit ledgers.

Nothing here logs in to the portal or stores a portal password: the user signs in on the official site in
their own browser and downloads the reports. The program only reads files the user saved on this computer.
"""
from __future__ import annotations

import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, LedgerEntry, SourceFile
from ..importers.gstn_json import detect_json_kind
from ..importers.ledgers import HEADS, LedgerFile, ledger_kind, read_ledger
from ..importers.parsing import parse_period
from ..importers.pipeline import _layout_for_tables, detect_excel_period, sha256_of
from ..importers.readers import UnsupportedFileError, read_csv, read_excel, read_json, zip_members
from .common import ServiceError, audit, dumps

PORTAL_HOME = "https://www.gst.gov.in/"
PORTAL_LOGIN = "https://services.gst.gov.in/services/login"
RETURNS_DASHBOARD = "https://return.gst.gov.in/returns/auth/dashboard"

#: report -> (label, page to open, where to find it after signing in)
REPORTS = {
    "GSTR1": ("GSTR-1", RETURNS_DASHBOARD, "Returns Dashboard → choose the year and month → GSTR-1 → View → "
                                           "Download (JSON)"),
    "GSTR2B": ("GSTR-2B", RETURNS_DASHBOARD, "Returns Dashboard → choose the year and month → GSTR-2B → Download → "
                                             "Generate JSON / Excel"),
    "GSTR2A": ("GSTR-2A", RETURNS_DASHBOARD, "Returns Dashboard → choose the year and month → GSTR-2A → Download "
                                             "→ Generate JSON / Excel"),
    "GSTR3B": ("GSTR-3B", RETURNS_DASHBOARD, "Returns Dashboard → choose the year and month → GSTR-3B → View → "
                                             "Download (JSON / Excel)"),
    "CASH": ("Electronic cash ledger", PORTAL_LOGIN, "Services → Ledgers → Electronic Cash Ledger → choose the "
                                                     "dates → Save as Excel"),
    "CREDIT": ("Electronic credit ledger", PORTAL_LOGIN, "Services → Ledgers → Electronic Credit Ledger → choose "
                                                         "the dates → Save as Excel"),
    "TDSTCS": ("TDS and TCS credit received", RETURNS_DASHBOARD, "Returns Dashboard → choose the year and month → "
                                                                 "TDS and TCS Credit Received → Download"),
    "GSTR8A": ("GSTR-8A / GSTR-9 Table 8A", RETURNS_DASHBOARD, "Returns Dashboard → Annual Return → GSTR-9 → "
                                                               "Download Table 8A document details"),
}
SOURCE_OF = {"GSTR1": "GSTR1", "GSTR2B": "GSTR2B", "GSTR2A": "GSTR2A", "GSTR8A": "GSTR8A", "IMS": "IMS"}
LABELS = {**{k: v[0] for k, v in REPORTS.items()}, "IMS": "IMS download"}
FILE_TYPES = {".json", ".zip", ".xlsx", ".xls", ".xlsm", ".csv"}
_GSTIN = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
_LEDGER_TYPE = {"CASH": "CASHLEDGER", "CREDIT": "CREDITLEDGER"}


def is_online(host: str = "www.gst.gov.in", timeout: float = 3.0) -> bool:
    """True when the GST portal can be reached (used only to tell the user; nothing is sent)."""
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


def default_downloads() -> Path:
    return Path(os.path.expanduser("~")) / "Downloads"


@dataclass
class PortalFile:
    path: Path
    kind: str  # GSTR1 / GSTR2B / GSTR2A / GSTR3B / GSTR8A / IMS / CASH / CREDIT / TDSTCS
    gstin: str = ""
    period: str | None = None
    client_id: int | None = None
    client_name: str = ""
    status: str = ""  # Ready / Already imported / reason it cannot be imported
    modified: float = 0.0

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)

    @property
    def ready(self) -> bool:
        return self.status == "Ready"


def _mmyyyy(v) -> str | None:
    return parse_period(str(v)) if v not in (None, "") else None


def _json_facts(js, name: str) -> tuple[str | None, str, str | None]:
    hint = "GSTR8A" if re.search(r"8a|gstr[-_ ]?9", name, re.I) else (
        "GSTR1" if re.search(r"gstr[-_ ]?1(?!\d)|_r1_", name, re.I) else None)
    kind = detect_json_kind(js, hint) if isinstance(js, dict) else None
    data = js.get("data", js) if isinstance(js, dict) else {}
    data = data if isinstance(data, dict) else {}
    gstin = str(js.get("gstin") or data.get("gstin") or "").upper() if isinstance(js, dict) else ""
    period = None
    for src in (js if isinstance(js, dict) else {}, data):
        for key in ("rtnprd", "fp", "ret_period", "ret_prd", "taxprd"):
            period = period or _mmyyyy(src.get(key))
    return kind, gstin, period


def recognise(path: str | Path) -> tuple[str | None, list[str], str | None]:
    """(kind, GSTINs seen in the file, period) of a file downloaded from the portal; kind None if unknown."""
    path = Path(path)
    suffix = path.suffix.lower()
    seen = _GSTIN.findall(path.name.upper())
    try:
        if suffix in (".json", ".zip"):
            if suffix == ".zip":
                member = next(((n, b) for n, b in zip_members(path) if n.lower().endswith(".json")), None)
                if member is None:
                    return None, seen, None
                js, name = read_json(member[1]), f"{path.name} {member[0]}"
            else:
                js, name = read_json(path), path.name
            kind, gstin, period = _json_facts(js, name)
            return kind, ([gstin] if gstin else []) + seen, period
        if suffix not in (".xlsx", ".xls", ".xlsm", ".csv"):
            return None, seen, None
        tables = [read_csv(path, path.name)] if suffix == ".csv" else read_excel(path)
    except (UnsupportedFileError, OSError, ValueError, KeyError):
        return None, seen, None
    head_text = " ".join(str(v) for t in tables for _n, vals in t.rows[:15] for v in vals if v)
    seen += _GSTIN.findall(head_text.upper())
    period = detect_excel_period(tables) or next((parse_period(m) for m in re.findall(r"(?<!\d)(\d{6})(?!\d)",
                                                                                         path.name)
                                                  if parse_period(m)), None)
    led = ledger_kind(tables, path.name)
    if led:
        return led, seen, None
    low = (path.name + " " + head_text).lower()
    if re.search(r"\btds\b|\btcs\b|tds and tcs|tds_tcs|tdstcs", low):
        return "TDSTCS", seen, period
    layout = _layout_for_tables(tables)
    kind = {"gstr2b_excel": "GSTR2B", "gstr2a_excel": "GSTR2A", "gstr8a_excel": "GSTR8A"}.get(layout)
    if kind is None and re.search(r"gstr[-_ ]?3b", low) and suffix != ".csv":
        kind = "GSTR3B"
    return kind, seen, period


class PortalService:
    def __init__(self, db: Database):
        self.db = db

    def _clients(self) -> dict[str, tuple[int, str]]:
        with self.db.session() as s:
            return {c.gstin: (c.id, c.name) for c in s.scalars(select(Client))}

    def inspect(self, path: str | Path, current_client_id: int | None = None,
                clients: dict[str, tuple[int, str]] | None = None) -> PortalFile | None:
        """What the file is and whose; None when it is not a GST portal file."""
        path = Path(path)
        kind, seen, period = recognise(path)
        if kind is None:
            return None
        clients = self._clients() if clients is None else clients
        pf = PortalFile(path, kind, period=period, modified=path.stat().st_mtime)
        own = [g for g in seen if g in clients]
        if own:
            pf.gstin = own[0]
            pf.client_id, pf.client_name = clients[own[0]]
        elif kind in ("CASH", "CREDIT", "TDSTCS") and current_client_id and not seen:
            # some downloads do not carry the GSTIN: offered for the client that is open
            pf.client_id = current_client_id
            pf.client_name = next((n for g, (i, n) in clients.items() if i == current_client_id), "")
            pf.gstin = next((g for g, (i, n) in clients.items() if i == current_client_id), "")
        if pf.client_id is None:
            first = next((g for g in seen), "")
            pf.status = (f"No client with GSTIN {first} – add the client first" if first and kind in (
                "GSTR1", "GSTR2B", "GSTR2A", "GSTR3B", "GSTR8A", "IMS", "CASH", "CREDIT") else
                "Client not known – select the client and import it from its page")
            return pf
        with self.db.session() as s:
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == pf.client_id,
                                                       SourceFile.sha256 == sha256_of(path)))
        pf.status = f"Already imported (import #{dup})" if dup else "Ready"
        return pf

    def scan(self, folder: str | Path, days: int = 7, current_client_id: int | None = None,
             limit: int = 200) -> list[PortalFile]:
        """GST portal files saved in the folder in the last few days, newest first."""
        folder = Path(folder)
        if not folder.is_dir():
            return []
        since = time.time() - days * 86400
        files = []
        for p in folder.iterdir():
            try:
                if (p.is_file() and p.suffix.lower() in FILE_TYPES and not p.name.startswith(("~$", "."))
                        and p.stat().st_mtime >= since and p.stat().st_size < 200 * 1024 * 1024):
                    files.append(p)
            except OSError:
                continue
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        clients = self._clients()
        out = []
        for p in files[:limit]:
            pf = self.inspect(p, current_client_id, clients)
            if pf is not None:
                out.append(pf)
        return out

    # ------------------------------------------------------------- ledgers
    def import_ledger(self, client_id: int, path: str | Path, kind: str | None = None,
                      user: str | None = None) -> tuple[SourceFile, LedgerFile, int]:
        """Save an electronic ledger download; lines already saved from an earlier (overlapping) download are not
        added again. Returns the import, the file read and the number of lines already present."""
        path = Path(path)
        led = read_ledger(path, kind)
        digest = sha256_of(path)
        stype = _LEDGER_TYPE[led.ledger]
        with self.db.session() as s:
            if s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client_id, SourceFile.sha256 == digest))
            if dup:
                raise ServiceError(f"{path.name} was already imported (import #{dup})")

            def key(d, ref, desc, txn, a):
                return (d, ref, desc, txn, *[Decimal(a[h]).quantize(Decimal("0.01")) for h in HEADS])

            have = {key(r.entry_date, r.reference, r.description, r.txn,
                        {h: getattr(r, h) for h in HEADS}) for r in s.scalars(
                select(LedgerEntry).where(LedgerEntry.client_id == client_id, LedgerEntry.ledger == led.ledger))}
            new = [ln for ln in led.lines if key(ln.entry_date, ln.reference, ln.description, ln.txn, ln.amounts)
                   not in have]
            repeated = len(led.lines) - len(new)
            dated = [ln.entry_date for ln in led.lines if ln.entry_date]
            sf = SourceFile(client_id=client_id, source_type=stype, file_name=path.name,
                            file_path=str(path.resolve()), sha256=digest, layout=f"{led.ledger.lower()}_ledger",
                            period=None, rows_read=len(led.lines) + len(led.skipped), documents_imported=len(new),
                            warnings_json=dumps(led.skipped + ([f"{repeated} line(s) were already saved from an "
                                                                "earlier download"] if repeated else [])),
                            imported_by=user or "")
            s.add(sf)
            s.flush()
            for ln in new:
                b = ln.balance or {}
                s.add(LedgerEntry(client_id=client_id, source_file_id=sf.id, ledger=led.ledger,
                                  entry_date=ln.entry_date, reference=ln.reference, tax_period=ln.tax_period,
                                  description=ln.description, txn=ln.txn, source_row=ln.row[:80],
                                  **{h: ln.amounts[h] for h in HEADS},
                                  **{f"bal_{h}": b.get(h) for h in HEADS}))
            audit(s, "IMPORT", "source_file", sf.id, {
                "file": path.name, "ledger": led.ledger, "lines": len(new), "repeated": repeated,
                "from": str(min(dated)) if dated else None, "to": str(max(dated)) if dated else None}, user, client_id)
            s.expunge(sf)
        return sf, led, repeated

    def ledger_rows(self, client_id: int, ledger: str) -> list[LedgerEntry]:
        with self.db.session() as s:
            return list(s.scalars(select(LedgerEntry).where(LedgerEntry.client_id == client_id,
                                                            LedgerEntry.ledger == ledger)
                                  .order_by(LedgerEntry.entry_date, LedgerEntry.id)))

    def balances(self, client_id: int) -> dict[str, tuple[date | None, dict[str, Decimal]]]:
        """Latest balance of each ledger as shown in the downloads: ledger -> (as on, head -> amount)."""
        out = {}
        for ledger in ("CASH", "CREDIT"):
            rows = [r for r in self.ledger_rows(client_id, ledger) if r.bal_igst is not None or r.bal_cgst is not None]
            if rows:
                last = max(rows, key=lambda r: (r.entry_date or date.min, r.id))
                out[ledger] = (last.entry_date, {h: getattr(last, f"bal_{h}") or ZERO for h in HEADS})
        return out

    # ------------------------------------------------------- one-click import
    def import_file(self, pf: PortalFile, user: str | None = None) -> str:
        """Import a recognised file for its client; returns a one-line result. Invoice-level returns (GSTR-1,
        2B, 2A, 8A, IMS) go through the ordinary import preview and are saved as shown there."""
        from ..core.models import Source
        from .gstr3b import Gstr3bService
        from .imports import ImportService
        from .tds_tcs import TdsTcsService

        if pf.client_id is None:
            raise ServiceError(pf.status or "Client not known")
        if pf.kind in ("CASH", "CREDIT"):
            _sf, led, repeated = self.import_ledger(pf.client_id, pf.path, pf.kind, user)
            return f"{pf.label}: {len(led.lines) - repeated} line(s) saved" + (
                f", {repeated} already saved earlier" if repeated else "")
        if pf.kind == "GSTR3B":
            _sf, pv = Gstr3bService(self.db).import_file(pf.client_id, pf.path, pf.period, user)
            return f"GSTR-3B saved for {', '.join(pv.periods)}"
        if pf.kind == "TDSTCS":
            pv = TdsTcsService(self.db).import_file(pf.client_id, pf.path, user)
            return f"TDS/TCS credit: {len(pv.new)} new, {len(pv.changed)} changed"
        svc = ImportService(self.db)
        preview = svc.preview(pf.client_id, pf.path, Source(SOURCE_OF[pf.kind]), pf.period)
        sf = svc.commit(pf.client_id, preview, user)
        return f"{pf.label}: {sf.documents_imported} document(s) saved"
