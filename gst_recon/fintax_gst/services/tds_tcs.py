"""TDS / TCS credits received: import of the portal download and the statement.

Re-importing a later download does not duplicate credits: a credit already imported
(same kind, period, party and amounts) only takes the newer action (accepted /
rejected / pending), and that change is audited.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Invoice, SourceFile, TdsTcsCredit
from ..importers.pipeline import sha256_of
from ..itc.annual import fy_months
from ..outward.tds_tcs import CreditLine, TdsTcsStatement, build_statement, read_credits
from .common import ServiceError, audit, dumps


@dataclass
class CreditPreview:
    file_name: str
    lines: list[CreditLine]
    problems: list[str]
    new: list[CreditLine] = field(default_factory=list)
    changed: list[tuple[CreditLine, str]] = field(default_factory=list)  # (line, earlier action)
    unchanged: int = 0


def _line(r: TdsTcsCredit) -> CreditLine:
    return CreditLine(r.kind, r.period, r.party_gstin, r.party_name, r.value, r.igst, r.cgst, r.sgst, r.action,
                      r.source_row)


class TdsTcsService:
    def __init__(self, db: Database):
        self.db = db

    def _existing(self, s, client_id: int) -> dict[tuple, TdsTcsCredit]:
        rows = s.scalars(select(TdsTcsCredit).where(TdsTcsCredit.client_id == client_id).order_by(TdsTcsCredit.id))
        return {_line(r).key(): r for r in rows}

    def preview(self, client_id: int, path: str | Path) -> CreditPreview:
        lines, problems = read_credits(path)
        pv = CreditPreview(Path(path).name, lines, problems)
        with self.db.session() as s:
            existing = self._existing(s, client_id)
        seen = set()
        for c in lines:
            old = existing.get(c.key())
            if c.key() in seen:
                pv.problems.append(f"{c.row}: repeats an earlier row of the file – imported once")
            elif old is None:
                pv.new.append(c)
            elif old.action != c.action:
                pv.changed.append((c, old.action))
            else:
                pv.unchanged += 1
            seen.add(c.key())
        return pv

    def import_file(self, client_id: int, path: str | Path, user: str | None = None) -> CreditPreview:
        path = Path(path)
        pv = self.preview(client_id, path)
        if not pv.new and not pv.changed:
            raise ServiceError(f"{path.name}: no new TDS/TCS credits and no changed actions"
                               + (f" ({pv.unchanged} already imported)" if pv.unchanged else ""))
        with self.db.session() as s:
            sf = SourceFile(client_id=client_id, source_type="TDSTCS", file_name=path.name,
                            file_path=str(path.resolve()), sha256=sha256_of(path), layout="tds_tcs_credit",
                            period=None, rows_read=len(pv.lines), documents_imported=len(pv.new),
                            rows_rejected=sum(1 for p in pv.problems if "not imported" in p),
                            warnings_json=dumps(pv.problems), imported_by=user or "")
            s.add(sf)
            s.flush()
            for c in pv.new:
                s.add(TdsTcsCredit(client_id=client_id, source_file_id=sf.id, kind=c.kind, period=c.period,
                                   party_gstin=c.party_gstin, party_name=c.party_name, value=c.value, igst=c.igst,
                                   cgst=c.cgst, sgst=c.sgst, action=c.action, source_row=c.row[:80]))
            existing = self._existing(s, client_id)
            for c, before in pv.changed:
                existing[c.key()].action = c.action
            audit(s, "IMPORT", "source_file", sf.id, {
                "file": path.name, "credits": len(pv.new),
                "actions_changed": [{"kind": c.kind, "period": c.period, "party": c.party_gstin, "before": b,
                                     "after": c.action} for c, b in pv.changed]}, user, client_id)
        return pv

    def credits(self, client_id: int, months: list[str]) -> list[CreditLine]:
        with self.db.session() as s:
            return [_line(r) for r in s.scalars(select(TdsTcsCredit).where(
                TdsTcsCredit.client_id == client_id, TdsTcsCredit.period.in_(months)).order_by(TdsTcsCredit.id))]

    def statement(self, client_id: int, fy: str, months: list[str] | None = None) -> TdsTcsStatement:
        months = months or fy_months(fy)
        with self.db.session() as s:
            client = s.get(Client, client_id)
            if client is None:
                raise ServiceError(f"Client {client_id} not found")
            sales: dict[str, Decimal] = {}
            for gstin, doc, taxable in s.execute(
                    select(Invoice.supplier_gstin, Invoice.doc_type, Invoice.taxable).where(
                        Invoice.client_id == client_id, Invoice.source_type == "SALES",
                        Invoice.period.in_(months), Invoice.supplier_gstin != "")):
                sales[gstin] = sales.get(gstin, ZERO) + (-taxable if doc == "CRN" else taxable)
            gstin = client.gstin
        return build_statement(self.credits(client_id, months), months, gstin, sales)
