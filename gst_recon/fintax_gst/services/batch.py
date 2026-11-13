"""Batch processing: import a folder of many clients' files, reconcile, and write the reports.

Folder layout (one folder per client, holding one folder per month)::

    <batch folder>/
        Shree Ganesh Traders 27AAPFU0939F1ZV/   <- any name containing the client's GSTIN
            2025-04/                            <- the tax period (YYYY-MM, or e.g. Apr-2025)
                purchase_register.xlsx
                gstr2b.json
                sales_register.xlsx
                gstr1.json
                gstr3b.json
                ...

**What each file is** is decided by the first keyword its name contains:

| Keyword | Imported as |
|---|---|
| `2b`, `gstr2b` | GSTR-2B |
| `2a`, `gstr2a` | GSTR-2A |
| `8a`, `table8a` | GSTR-9 Table 8A |
| `3b`, `gstr3b` | GSTR-3B |
| `gstr1`, `gstr-1`, `r1` | GSTR-1 |
| `ims` | IMS |
| `einv`, `e-invoice`, `irn` | e-invoice report |
| `ewb`, `eway`, `e-way` | e-way bill report |
| `tds`, `tcs` | TDS / TCS credit received |
| `sale` | sales register |
| `purchase`, `books`, `tally` | purchase register |

The importer still checks the contents against that type (a GSTR-2B named *purchase.xlsx* is refused).
A file whose name matches no keyword is listed with the reason, never guessed.

**For each client and month:**

1. Import every file not imported before. A file already imported is skipped.
2. When something new was imported (or with ``rerun``), run the reconciliations the month's data
   allows: purchase register vs GSTR-2B, sales register vs GSTR-1, vs e-invoices and vs e-way bills.
3. Write each run's Excel report (and PDF if asked) into a ``reports`` folder inside the month's folder.

A problem with one file or run (an unreadable file, headings that need a mapping, an unknown client)
is recorded with its reason and the batch carries on. The result is also written as
``batch_summary_<time>.csv`` in the batch folder.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..core.gstin import validate_gstin
from ..core.models import Source
from ..db.database import Database
from ..db.models import utcnow
from ..engine.matcher import OperationCancelled
from ..importers.parsing import parse_period
from ..importers.readers import SUPPORTED_EXTENSIONS
from .common import ServiceError, audit

_B = r"(?<![a-z0-9])"  # keyword boundaries: "gstr2b_2025-04" and "2B.json" match, "a2b3" does not
_E = r"(?![a-z0-9])"
KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"(?:gstr[-_ ]?|{_B})2b{_E}", re.I), "GSTR2B"),
    (re.compile(rf"(?:gstr[-_ ]?|{_B})2a{_E}", re.I), "GSTR2A"),
    (re.compile(rf"(?:table[-_ ]?|{_B})8a{_E}", re.I), "GSTR8A"),
    (re.compile(rf"(?:gstr[-_ ]?|{_B})3b{_E}", re.I), "GSTR3B"),
    (re.compile(rf"gstr[-_ ]?1{_E}|{_B}r1{_E}", re.I), "GSTR1"),
    (re.compile(rf"{_B}ims{_E}", re.I), "IMS"),
    (re.compile(r"e[-_ ]?inv|irn", re.I), "EINV"),
    (re.compile(r"ewb|e[-_ ]?way", re.I), "EWB"),
    (re.compile(rf"{_B}(?:tds|tcs){_E}", re.I), "TDSTCS"),
    (re.compile(r"sale", re.I), "SALES"),
    (re.compile(r"purchase|books|tally", re.I), "BOOKS"),
]
COMPARISONS = [(Source.BOOKS, Source.GSTR2B), (Source.SALES, Source.GSTR1), (Source.SALES, Source.EINV),
               (Source.SALES, Source.EWB)]
LABELS = {Source.BOOKS: "Purchase", Source.SALES: "Sales", Source.GSTR2B: "GSTR-2B", Source.GSTR1: "GSTR-1",
          Source.EINV: "e-Invoice", Source.EWB: "e-Way bill"}
_GSTIN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]")


def kind_of(name: str) -> str | None:
    stem = Path(name).stem
    return next((kind for rx, kind in KEYWORDS if rx.search(stem)), None)


@dataclass
class BatchRow:
    client: str
    period: str
    item: str  # file name, or the comparison of a run
    action: str  # planned, imported, skipped, reconciled, report, client, error, cancelled
    detail: str


@dataclass
class BatchResult:
    rows: list[BatchRow] = field(default_factory=list)
    run_ids: list[int] = field(default_factory=list)
    summary_path: Path | None = None
    cancelled: bool = False

    def count(self, action: str) -> int:
        return sum(1 for r in self.rows if r.action == action)

    def text(self) -> str:
        parts = [f"{self.count('imported')} file(s) imported", f"{self.count('skipped')} skipped",
                 f"{self.count('reconciled')} reconciliation(s)", f"{self.count('error')} problem(s)"]
        if self.count("client"):
            parts.insert(0, f"{self.count('client')} client(s) added")
        return ", ".join(parts) + (" – cancelled before the end" if self.cancelled else "")


class _Skip(Exception):
    """A file that needs no import (identical file already imported)."""


class BatchService:
    def __init__(self, db: Database):
        self.db = db

    def plan(self, root: str | Path) -> list[tuple[str, str, Path, str | None]]:
        """(client folder, period, file, kind) for every file; period '' / kind None mark problems."""
        root = Path(root)
        if not root.is_dir():
            raise ServiceError(f"{root} is not a folder")
        out = []
        for cdir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for item in sorted(cdir.iterdir()):
                if item.name.startswith(("~$", ".")):
                    continue
                if item.is_file():
                    out.append((cdir.name, "", item, None))
                    continue
                period = parse_period(item.name) or ""
                for f in sorted(item.iterdir()):
                    if f.is_file() and not f.name.startswith(("~$", ".")):
                        out.append((cdir.name, period, f, kind_of(f.name) if period else None))
        return out

    def _client_for(self, folder: str, create: bool, user: str | None):
        """The client named by the folder's GSTIN, and whether it was added now."""
        from .clients import ClientService

        m = _GSTIN.search(folder.upper())
        if not m or not validate_gstin(m.group(0))[0]:
            raise ServiceError(f"folder name '{folder}' has no valid GSTIN – name it e.g. "
                               "'Client name 27AAPFU0939F1ZV'")
        svc = ClientService(self.db)
        try:
            return svc.by_gstin(m.group(0)), False
        except ServiceError:
            if not create:
                raise ServiceError(f"no client with GSTIN {m.group(0)} – add the client first, or tick "
                                   "'Add clients that do not exist yet'") from None
        name = re.sub(r"[\s_\-–]+", " ", folder[:m.start()] + " " + folder[m.end():]).strip() or m.group(0)
        return svc.create(m.group(0), user, name=name), True

    def _import(self, client_id: int, path: Path, kind: str, period: str, user: str | None) -> str:
        """Import one file; returns a description. Raises _Skip when the file needs no import."""
        if kind == "GSTR3B":
            from .gstr3b import Gstr3bService

            try:
                _sf, pv = Gstr3bService(self.db).import_file(client_id, path, period, user)
            except ServiceError as exc:
                if "already imported" in str(exc):
                    raise _Skip(str(exc)) from None
                raise
            return f"GSTR-3B for {', '.join(pv.periods) or period}"
        if kind == "TDSTCS":
            from .tds_tcs import TdsTcsService

            try:
                pv = TdsTcsService(self.db).import_file(client_id, path, user)
            except ServiceError as exc:
                if "no new TDS/TCS credits" in str(exc):
                    raise _Skip(str(exc)) from None
                raise
            return f"{len(pv.new)} TDS/TCS credit(s), {len(pv.changed)} changed action(s)"
        from .imports import ImportService

        svc = ImportService(self.db)
        preview = svc.preview_auto(client_id, path, Source(kind), period)
        if preview.already_imported_file_id:
            raise _Skip(f"already imported (import #{preview.already_imported_file_id})")
        sf = svc.commit(client_id, preview, user)
        return (f"{Source(kind).value}: {sf.documents_imported} document(s), {sf.rows_rejected} row(s) rejected, "
                f"{sf.documents_skipped_existing} already present")

    def run(self, root: str | Path, user: str | None = None, pdf: bool = False, rerun: bool = False,
            dry_run: bool = False, create_clients: bool = False, progress=None, cancel=None) -> BatchResult:
        from ..importers.pipeline import MappingRequired
        from ..importers.readers import UnsupportedFileError
        from .reconciliation import ReconciliationService
        from .reports import export_run

        progress = progress or (lambda pct, msg: None)
        root = Path(root)
        plan = self.plan(root)
        res = BatchResult()
        if not plan:
            raise ServiceError(f"{root} has no client folders with files – see the folder layout in the help")
        touched: dict[tuple[int, str], bool] = {}  # (client, period) -> something new imported
        clients: dict[str, object] = {}
        to_add: set[str] = set()  # check only: folders whose client would be added
        try:
            for i, (folder, period, path, kind) in enumerate(plan, start=1):
                if cancel:
                    cancel.check()
                progress(int(70 * i / len(plan)), f"{folder} – {path.name}")
                if not period:
                    res.rows.append(BatchRow(folder, "", path.name, "skipped",
                                             "not in a month folder (e.g. 2025-04) – not imported"))
                    continue
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    res.rows.append(BatchRow(folder, period, path.name, "skipped",
                                             f"file type {path.suffix or '(none)'} is not imported"))
                    continue
                if kind is None:
                    res.rows.append(BatchRow(folder, period, path.name, "skipped",
                                             "cannot tell what the file is from its name – include e.g. purchase, "
                                             "sales, gstr2b, gstr1, gstr3b, einvoice or ewb in the name"))
                    continue
                if folder not in clients:
                    try:
                        if dry_run:
                            clients[folder], added = self._client_for(folder, False, user)[0], False
                        else:
                            clients[folder], added = self._client_for(folder, create_clients, user)
                        if added:
                            res.rows.append(BatchRow(folder, "", "", "client",
                                                     f"client added: {clients[folder].name} "
                                                     f"({clients[folder].gstin})"))
                    except ServiceError as exc:
                        clients[folder] = None
                        if dry_run and create_clients and "no client with GSTIN" in str(exc):
                            to_add.add(folder)
                            res.rows.append(BatchRow(folder, "", "", "planned", "client would be added"))
                        else:
                            res.rows.append(BatchRow(folder, "", "", "error", str(exc)))
                client = clients[folder]
                if dry_run and (client is not None or folder in to_add):
                    res.rows.append(BatchRow(folder, period, path.name, "planned", f"would import as {kind}"))
                    continue
                if client is None:
                    res.rows.append(BatchRow(folder, period, path.name, "skipped", "client not found (see above)"))
                    continue
                if dry_run:
                    continue
                touched.setdefault((client.id, period), False)
                try:
                    detail = self._import(client.id, path, kind, period, user)
                    res.rows.append(BatchRow(folder, period, path.name, "imported", detail))
                    touched[(client.id, period)] = True
                except _Skip as exc:
                    res.rows.append(BatchRow(folder, period, path.name, "skipped", str(exc)))
                except MappingRequired as exc:
                    res.rows.append(BatchRow(
                        folder, period, path.name, "error",
                        f"column headings not recognised ({', '.join(exc.mapping.missing_required)}) – import it "
                        "once on its own, match the columns and save a template; the batch then reuses it"))
                except (ServiceError, UnsupportedFileError, ValueError, OSError) as exc:
                    res.rows.append(BatchRow(folder, period, path.name, "error", str(exc)))
            if dry_run:
                return res
            recon = ReconciliationService(self.db)
            names = {c.id: f for f, c in clients.items() if c is not None}
            todo = [(cid, p) for (cid, p), new in sorted(touched.items()) if new or rerun]
            for j, (cid, period) in enumerate(todo, start=1):
                if cancel:
                    cancel.check()
                progress(70 + int(29 * j / len(todo)), f"Reconciling {names[cid]} {period}")
                have = self._sources(cid, period)
                for left, right in COMPARISONS:
                    if left not in have or right not in have:
                        continue
                    label = f"{LABELS[left]} vs {LABELS[right]}"
                    try:
                        run_id = recon.run(cid, period, compare_with=right, user=user)
                        res.run_ids.append(run_id)
                        s = json.loads(recon.load(run_id).run.summary_json or "{}")
                        res.rows.append(BatchRow(names[cid], period, label, "reconciled",
                                                 f"run #{run_id}: {s.get('total_lines', 0)} line(s), "
                                                 f"{s.get('pending_cases', 0)} to review"))
                        out = root / names[cid] / self._period_dir(root / names[cid], period) / "reports"
                        paths = []
                        for p in export_run(self.db, run_id, out, pdf=pdf, user=user):
                            named = p.with_name(f"{label} – {p.name}")  # four runs of a month are told apart
                            p.replace(named)
                            paths.append(named)
                        res.rows.append(BatchRow(names[cid], period, label, "report",
                                                 ", ".join(p.name for p in paths)))
                    except (ServiceError, ValueError, OSError) as exc:
                        res.rows.append(BatchRow(names[cid], period, label, "error", str(exc)))
        except OperationCancelled:
            res.cancelled = True
            res.rows.append(BatchRow("", "", "", "cancelled", "batch cancelled – the work listed above was done"))
        res.summary_path = root / f"batch_summary_{utcnow():%Y%m%d_%H%M%S}.csv"
        with res.summary_path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Client folder", "Period", "File / reconciliation", "Result", "Detail"])
            for r in res.rows:
                w.writerow([r.client, r.period, r.item, r.action, r.detail])
        with self.db.session() as s:
            audit(s, "BATCH", "batch", root.name, {
                "folder": str(root), "imported": res.count("imported"), "skipped": res.count("skipped"),
                "errors": res.count("error"), "runs": res.run_ids, "cancelled": res.cancelled,
                "summary": str(res.summary_path)}, user)
        progress(100, "Batch complete")
        return res

    def _sources(self, client_id: int, period: str) -> set[Source]:
        from sqlalchemy import select

        from ..db.models import Invoice

        with self.db.session() as s:
            kinds = set(s.scalars(select(Invoice.source_type).where(Invoice.client_id == client_id,
                                                                    Invoice.period == period).distinct()))
        return {Source(k) for k in kinds if k in Source.__members__}

    @staticmethod
    def _period_dir(cdir: Path, period: str) -> str:
        return next((p.name for p in sorted(cdir.iterdir()) if p.is_dir() and parse_period(p.name) == period), period)


def write_example(out_dir: str | Path) -> Path:
    """Create an example batch folder with the demo client's April 2025 files, to try batch processing."""
    import tempfile

    from ..samples import CLIENT, write_all

    out = Path(out_dir)
    month = out / f"{CLIENT['name']} {CLIENT['gstin']}" / "2025-04"
    month.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        files = write_all(tmp)
        for key, name in (("books_april", "purchase_register.xlsx"), ("gstr2b_april_json", "gstr2b.json"),
                          ("sales_april", "sales_register.xlsx"), ("gstr1_april_json", "gstr1.json"),
                          ("gstr3b_april_json", "gstr3b.json"), ("einv_april", "einvoice_report.csv"),
                          ("ewb_april", "ewaybill_report.csv")):
            shutil.copyfile(files[key], month / name)
    (out / "README.txt").write_text(
        "FIN TAX PRO batch folder\r\n\r\n"
        "One folder per client: its name must contain the client's GSTIN.\r\n"
        "Inside it, one folder per month named like 2025-04.\r\n"
        "Inside that, the month's files. The file name says what it is: purchase, sales, gstr2b, gstr1,\r\n"
        "gstr3b, einvoice, ewb, ims, tds.\r\n\r\n"
        "Reports are written to a 'reports' folder inside each month folder, and a batch_summary CSV\r\n"
        "is written here.\r\n", encoding="utf-8")
    return out
