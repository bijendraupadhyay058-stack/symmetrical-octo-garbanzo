"""GSTR-3B import and retrieval. Re-importing a period supersedes earlier values (kept, audited)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..db.database import Database
from ..db.models import Gstr3bEntry, SourceFile
from ..importers.gstr3b import Gstr3bPreview, Gstr3bValues, preview_gstr3b
from ..importers.pipeline import sha256_of
from .common import ServiceError, audit, dumps


class Gstr3bService:
    def __init__(self, db: Database):
        self.db = db

    def preview(self, path: str | Path, period: str | None = None) -> Gstr3bPreview:
        return preview_gstr3b(path, period)

    def import_file(self, client_id: int, path: str | Path, period: str | None = None,
                    user: str | None = None) -> tuple[SourceFile, Gstr3bPreview]:
        preview = self.preview(path, period)
        path = Path(path)
        digest = sha256_of(path)
        with self.db.session() as s:
            dup = s.scalar(select(SourceFile.id).where(SourceFile.client_id == client_id,
                                                       SourceFile.sha256 == digest,
                                                       SourceFile.source_type == "GSTR3B"))
            if dup:
                raise ServiceError(f"{path.name} was already imported (import #{dup})")
            sf = SourceFile(client_id=client_id, source_type="GSTR3B", file_name=path.name,
                            file_path=str(path.resolve()), sha256=digest, layout=preview.layout,
                            period=preview.periods[0] if len(preview.periods) == 1 else None,
                            rows_read=sum(len(t) for t in preview.entries.values()),
                            documents_imported=sum(len(t) for t in preview.entries.values()),
                            warnings_json=dumps(preview.warnings), imported_by=user or "")
            s.add(sf)
            s.flush()
            superseded = 0
            for p, table in preview.entries.items():
                # only the tables present in the new file are superseded (a Table 3.1 file keeps Table 4)
                for old in s.scalars(select(Gstr3bEntry).where(Gstr3bEntry.client_id == client_id,
                                                               Gstr3bEntry.period == p,
                                                               Gstr3bEntry.table_code.in_(list(table)),
                                                               Gstr3bEntry.active.is_(True))):
                    old.active = False
                    superseded += 1
                for code, v in sorted(table.items()):
                    s.add(Gstr3bEntry(client_id=client_id, source_file_id=sf.id, period=p, table_code=code,
                                      igst=v.igst, cgst=v.cgst, sgst=v.sgst, cess=v.cess, taxable=v.taxable))
            audit(s, "IMPORT", "gstr3b", sf.id, {"periods": preview.periods, "superseded_rows": superseded,
                                                 "warnings": preview.warnings}, user, client_id)
        return sf, preview

    def values(self, client_id: int, periods: list[str] | None = None) -> dict[str, dict[str, Gstr3bValues]]:
        """Active GSTR-3B values (Tables 3.1 and 4): period -> table code -> values."""
        with self.db.session() as s:
            q = select(Gstr3bEntry).where(Gstr3bEntry.client_id == client_id, Gstr3bEntry.active.is_(True))
            if periods is not None:
                q = q.where(Gstr3bEntry.period.in_(periods))
            out: dict[str, dict[str, Gstr3bValues]] = {}
            for e in s.scalars(q):
                out.setdefault(e.period, {})[e.table_code] = Gstr3bValues(e.igst, e.cgst, e.sgst, e.cess,
                                                                          e.taxable or Decimal(0))
        return out
