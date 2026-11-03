"""Import TallyPrime statutory reports: GSTR-1 (as the sales register), GSTR-2A / 2B reconciliation (as the purchase
register) and GSTR-3B (as GSTR-3B per books, compared with the draft and the return filed)."""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from sqlalchemy import select

from ..core.models import Source
from ..db.database import Database
from ..db.models import BooksGstr3b, Client, SourceFile
from ..importers.gstr3b import Gstr3bValues, preview_gstr3b
from ..importers.parsing import parse_period
from ..importers.pipeline import ImportPreview, sha256_of
from ..importers.readers import UnsupportedFileError, read_excel, read_json
from ..importers.tally_statutory import (
    SALES_HEADERS, gstr1_json_rows, gstr1_offline_rows, is_gstr1_offline, recon_report_rows,
)
from .common import ServiceError, audit, dumps

KINDS = {"gstr1": "GSTR-1 report (sales)", "recon": "GSTR-2A / 2B reconciliation (purchases)",
         "gstr3b": "GSTR-3B report"}


class TallyStatutoryService:
    def __init__(self, db: Database):
        self.db = db

    def _client(self, client_id: int) -> Client:
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            return c

    def preview(self, client_id: int, path: str | Path, kind: str, period: str | None = None) -> ImportPreview:
        """An ordinary import preview of the report (GSTR-1 as sales, reconciliation as purchases)."""
        from .imports import ImportService

        path = Path(path)
        client = self._client(client_id)
        p = parse_period(period) if period else None
        suffix = path.suffix.lower()
        ignored: list[tuple[int, str]] = []
        warnings: list[str] = []
        if kind == "gstr1":
            if not p:
                raise ServiceError("Choose the month of the GSTR-1 report")
            if suffix == ".json":
                headers, rows = SALES_HEADERS, gstr1_json_rows(read_json(path), client.state_code, p)
            elif suffix in (".xlsx", ".xlsm", ".xls"):
                tables = read_excel(path)
                if not is_gstr1_offline(tables):
                    raise UnsupportedFileError(f"{path.name} is not a GSTR-1 export in the GST Offline Tool format "
                                               "(sheets b2b, b2cs, cdnr …)")
                rows, warnings = gstr1_offline_rows(tables, client.state_code, p)
                headers = SALES_HEADERS
            else:
                raise UnsupportedFileError("GSTR-1 report: use TallyPrime's export as Excel or JSON")
            source = Source.SALES
        elif kind == "recon":
            if suffix not in (".xlsx", ".xlsm", ".xls"):
                raise UnsupportedFileError("GSTR-2A / 2B reconciliation: use TallyPrime's export as Excel")
            headers, rows, ignored = recon_report_rows(read_excel(path))
            if not headers:
                raise UnsupportedFileError(f"{path.name}: no reconciliation report found (it needs a GSTIN and a "
                                           "status column)")
            source = Source.BOOKS
        else:
            raise ServiceError(f"Unknown report {kind}")
        if not rows:
            raise ServiceError(f"{path.name}: no documents found in the report")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / f"{path.stem}.csv"
            with work.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                w.writerows([["" if v is None else (f"{v:%d-%m-%Y}" if hasattr(v, "strftime") else v) for v in r]
                              for r in rows])
            pv = ImportService(self.db).preview(client_id, work, source, p)
        # the import is of the original report: its name, location and fingerprint
        pv.file_name, pv.file_path, pv.sha256 = path.name, path, sha256_of(path)
        pv.layout = f"tally_{kind}"
        with self.db.session() as s:
            pv.already_imported_file_id = s.scalar(select(SourceFile.id).where(
                SourceFile.client_id == client_id, SourceFile.sha256 == pv.sha256,
                SourceFile.source_type == source.value))
        pv.file_warnings = [*warnings, *pv.file_warnings]
        from ..importers.pipeline import RowIssue

        pv.issues = [RowIssue("", str(n), "ignored", why) for n, why in ignored] + pv.issues
        return pv

    # --------------------------------------------------------------- 3B
    def import_gstr3b(self, client_id: int, path: str | Path, period: str | None = None,
                      user: str | None = None) -> tuple[SourceFile, list[str]]:
        path = Path(path)
        self._client(client_id)
        preview = preview_gstr3b(path, period)
        digest = sha256_of(path)
        with self.db.session() as s:
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client_id, SourceFile.sha256 == digest,
                                                       SourceFile.source_type == "TALLY3B"))
            if dup:
                raise ServiceError(f"{path.name} was already imported (import #{dup})")
            sf = SourceFile(client_id=client_id, source_type="TALLY3B", file_name=path.name,
                            file_path=str(path.resolve()), sha256=digest, layout="tally_gstr3b",
                            period=preview.periods[0] if len(preview.periods) == 1 else None,
                            rows_read=sum(len(t) for t in preview.entries.values()),
                            documents_imported=sum(len(t) for t in preview.entries.values()),
                            warnings_json=dumps(preview.warnings), imported_by=user or "")
            s.add(sf)
            s.flush()
            for p, table in preview.entries.items():
                for code, v in table.items():
                    s.add(BooksGstr3b(client_id=client_id, source_file_id=sf.id, period=p, table_code=code,
                                      taxable=v.taxable, igst=v.igst, cgst=v.cgst, sgst=v.sgst, cess=v.cess))
            audit(s, "IMPORT", "tally_gstr3b", sf.id, {"periods": preview.periods}, user, client_id)
            s.expunge(sf)
        return sf, preview.periods

    def books_3b(self, client_id: int, period: str) -> dict[str, Gstr3bValues]:
        """The latest TallyPrime GSTR-3B of the month: table code -> values."""
        with self.db.session() as s:
            latest = s.scalar(select(BooksGstr3b.source_file_id).where(
                BooksGstr3b.client_id == client_id, BooksGstr3b.period == period)
                .order_by(BooksGstr3b.source_file_id.desc()).limit(1))
            if latest is None:
                return {}
            return {r.table_code: Gstr3bValues(r.igst, r.cgst, r.sgst, r.cess, r.taxable) for r in s.scalars(
                select(BooksGstr3b).where(BooksGstr3b.source_file_id == latest, BooksGstr3b.period == period))}

    def compare_3b(self, client_id: int, period: str, draft) -> list[tuple[str, Gstr3bValues, Gstr3bValues]]:
        """Draft vs TallyPrime GSTR-3B, table by table: (code, draft, books); empty when nothing was imported."""
        books = self.books_3b(client_id, period)
        if not books:
            return []
        ours = {**draft.t31, **draft.t4}
        out = []
        for code in sorted(set(ours) | set(books)):
            a, b = ours.get(code, Gstr3bValues()), books.get(code, Gstr3bValues())
            if any(getattr(a, f) or getattr(b, f) for f in ("taxable", "igst", "cgst", "sgst", "cess")):
                out.append((code, a, b))
        return out

