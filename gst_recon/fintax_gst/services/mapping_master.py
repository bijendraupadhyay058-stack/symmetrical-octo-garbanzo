"""Ledger Mapping Master: one permanent list per client of how each Tally ledger is classified – accounting class,
GST nature (inputs / input services / capital goods / exempt / no GST), source of supply, GSTR-9C Table 14 head and
ITC eligibility.

It is filled by every approval in Ledger classification, by ledger rules in ITC classification, by hand, from an Excel
file or by copying another client's master; it is used every year as the first suggestion in both screens.

The firm's mapping template (``client_id=None`` in this service) holds the usual classification of common ledger
names for every client; a client's own master always comes before it. A
transaction or ledger classified by hand in a year always keeps its own classification. The master never records
whether ITC was claimed – that is a fact of each year's GSTR-3B.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from ..db.database import Database
from ..db.models import Client, FirmMapping, ItcTxn, LedgerMapping, TbLedger
from ..gstr9.expenses import TABLE14
from ..ledgers.classify import ACCT_CLASSES, ELIGIBILITY, GST_CLASSES, GST_SOURCES, ledger_key
from ..ledgers.itc_classes import NATURES, nature_from_bifurcation
from .common import ServiceError, audit

HEAD = ["Ledger", "Accounting classification", "GST classification", "Source of supply", "GSTR-9C Table 14 head",
        "ITC eligibility", "Active", "Note"]


@dataclass
class MasterEntry:
    m: LedgerMapping
    tb_years: list[str]
    txns: int

    @property
    def nature(self) -> str:
        return NATURES[nature_from_bifurcation(self.m.acct_class, self.m.gst_class)]


def _code(value: str, options: dict[str, str], what: str, allow_blank: bool = False) -> str:
    v = str(value or "").strip()
    if not v and allow_blank:
        return ""
    if v in options:
        return v
    for k, label in options.items():
        if label.lower() == v.lower():
            return k
    raise ServiceError(f"Unknown {what} '{v}'")


class MappingMasterService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _q(client_id: int | None):
        if client_id is None:
            return FirmMapping, select(FirmMapping)
        return LedgerMapping, select(LedgerMapping).where(LedgerMapping.client_id == client_id)

    def entries(self, client_id: int | None, include_inactive: bool = True) -> list[MasterEntry]:
        model, q = self._q(client_id)
        with self.db.session() as s:
            if not include_inactive:
                q = q.where(model.active.is_(True))
            rows = list(s.scalars(q.order_by(model.ledger_key)))
            if client_id is None:
                s.expunge_all()
                return [MasterEntry(m, [], 0) for m in rows]
            years: dict[str, set] = {}
            for name, fy in s.execute(select(TbLedger.name, TbLedger.financial_year).where(
                    TbLedger.client_id == client_id)):
                years.setdefault(ledger_key(name), set()).add(fy)
            txns = {ledger_key(k or ""): n for k, n in s.execute(
                select(ItcTxn.ledger, func.count()).where(ItcTxn.client_id == client_id).group_by(ItcTxn.ledger))}
            s.expunge_all()
        return [MasterEntry(m, sorted(years.get(m.ledger_key, ())), txns.get(m.ledger_key, 0)) for m in rows]

    def save(self, client_id: int | None, ledger: str, acct_class: str, gst_class: str, user: str,
             gst_source: str = "regular", head_9c: str = "", eligibility: str = "", note: str = "", active: bool = True,
             source: str = "master") -> LedgerMapping:
        if not ledger.strip():
            raise ServiceError("Give the ledger name")
        if not acct_class.strip():
            raise ServiceError("Give the accounting classification")
        if gst_class not in GST_CLASSES:
            raise ServiceError(f"Unknown GST classification '{gst_class}'")
        if gst_source not in GST_SOURCES:
            raise ServiceError(f"Unknown source of supply '{gst_source}'")
        if eligibility and eligibility not in ELIGIBILITY:
            raise ServiceError(f"Unknown ITC eligibility '{eligibility}'")
        if head_9c and head_9c not in dict(TABLE14):
            raise ServiceError(f"Unknown Table 14 head '{head_9c}'")
        key = ledger_key(ledger)[:200]
        model, q = self._q(client_id)
        with self.db.session() as s:
            if client_id is not None and s.get(Client, client_id) is None:
                raise ServiceError(f"Client {client_id} not found")
            m = s.scalar(q.where(model.ledger_key == key))
            before = None
            if m is None:
                m = model(ledger_key=key) if client_id is None else model(client_id=client_id, ledger_key=key)
                s.add(m)
            else:
                before = {"acct_class": m.acct_class, "gst_class": m.gst_class, "gst_source": m.gst_source,
                          "head_9c": m.head_9c, "eligibility": m.eligibility, "active": m.active}
            m.acct_class, m.gst_class, m.gst_source = acct_class.strip()[:60], gst_class, gst_source
            m.head_9c, m.eligibility, m.note, m.active = head_9c, eligibility, note.strip(), active
            m.approved_by, m.source = user[:80], "firm" if client_id is None else source
            s.flush()
            audit(s, "MAPPING_MASTER" if client_id else "FIRM_MAPPING", "ledger_mapping", m.id, {"ledger": key, "before": before, "after": {
                "acct_class": acct_class, "gst_class": gst_class, "gst_source": gst_source, "head_9c": head_9c,
                "eligibility": eligibility, "active": active, "source": source}}, user, client_id)
            s.expunge(m)
        return m

    def set_active(self, ids: list[int], active: bool, user: str, firm: bool = False) -> int:
        model = FirmMapping if firm else LedgerMapping
        with self.db.session() as s:
            rows = list(s.scalars(select(model).where(model.id.in_(ids))))
            for m in rows:
                m.active = active
                audit(s, "FIRM_MAPPING" if firm else "MAPPING_MASTER", "ledger_mapping", m.id,
                      {"ledger": m.ledger_key, "active": active}, user, getattr(m, "client_id", None))
        return len(rows)

    def to_firm(self, client_id: int, ids: list[int], user: str) -> int:
        """Add a client's entries to the firm template (for ledger names common to many clients)."""
        n = 0
        for e in self.entries(client_id):
            if e.m.id in ids:
                self.save(None, e.m.ledger_key, e.m.acct_class, e.m.gst_class, user, e.m.gst_source, e.m.head_9c,
                          e.m.eligibility, e.m.note)
                n += 1
        return n

    def apply(self, client_id: int, fy: str, user: str) -> dict:
        """Use the master now: suggestions for the year's pending ledgers and for every transaction not classified by
        hand (approved / manual classifications are left as they are)."""
        from .bifurcation import BifurcationService
        from .itc_register import ItcRegisterService

        return {"ledgers": BifurcationService(self.db).suggest_all(client_id, fy, user),
                "transactions": ItcRegisterService(self.db).classify_auto(client_id, fy)}

    # ------------------------------------------------------------ Excel
    def export_xlsx(self, client_id: int | None, path: str | Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.worksheet.datavalidation import DataValidation

        wb = Workbook()
        ws = wb.active
        ws.title = "Ledger mapping master"
        ws.append(HEAD)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
        for e in self.entries(client_id):
            m = e.m
            ws.append([m.ledger_key, m.acct_class, GST_CLASSES.get(m.gst_class, m.gst_class),
                       GST_SOURCES.get(m.gst_source, m.gst_source), m.head_9c, ELIGIBILITY.get(m.eligibility, ""),
                       "yes" if m.active else "no", m.note])
        n = max(ws.max_row, 200)
        for col, options in (("C", GST_CLASSES.values()), ("D", GST_SOURCES.values()),
                             ("E", [c for c, _l in TABLE14]), ("F", ELIGIBILITY.values()), ("G", ["yes", "no"])):
            dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{col}2:{col}{n}")
        for col, w in zip("ABCDEFGH", (36, 32, 26, 22, 10, 30, 8, 40)):
            ws.column_dimensions[col].width = w
        lists = wb.create_sheet("Lists")
        lists.append(["Accounting classifications (any text is allowed)"])
        for a in ACCT_CLASSES:
            lists.append([a])
        path = Path(path)
        wb.save(path)
        return path

    def import_xlsx(self, client_id: int | None, path: str | Path, user: str) -> tuple[int, list[str]]:
        from ..importers.column_mapping import normalize_header
        from ..importers.readers import read_excel

        tables = read_excel(Path(path))
        if not tables or not tables[0].rows:
            raise ServiceError("The file is empty")
        rows = tables[0].rows
        names = [normalize_header(v) for v in rows[0][1]]
        want = [normalize_header(h) for h in HEAD]
        if names[:2] != want[:2]:
            raise ServiceError("Use the layout of 'Export to Excel' (Ledger, Accounting classification, …)")
        idx = {h: names.index(h) for h in want if h in names}
        n, errors = 0, []
        for r, values in rows[1:]:
            def cell(h, values=values):
                i = idx.get(normalize_header(h))
                return values[i] if i is not None and i < len(values) and values[i] is not None else ""

            if not str(cell("Ledger")).strip():
                continue
            try:
                self.save(client_id, str(cell("Ledger")), str(cell("Accounting classification")),
                          _code(cell("GST classification"), GST_CLASSES, "GST classification"), user,
                          _code(cell("Source of supply") or "regular", GST_SOURCES, "source of supply"),
                          str(cell("GSTR-9C Table 14 head")).strip(),
                          _code(cell("ITC eligibility"), ELIGIBILITY, "ITC eligibility", allow_blank=True),
                          str(cell("Note")), str(cell("Active") or "yes").strip().lower() not in ("no", "n", "0",
                                                                                                 "false"),
                          source="imported")
                n += 1
            except ServiceError as exc:
                errors.append(f"row {r}: {exc}")
        return n, errors

    def copy_from(self, client_id: int, from_client_id: int, user: str, overwrite: bool = False) -> tuple[int, int]:
        """Copy another client's active master entries (e.g. a group company with the same chart of accounts).
        Entries this client already has are kept unless ``overwrite``. Returns (copied, kept)."""
        if client_id is None or from_client_id is None or client_id == from_client_id:
            raise ServiceError("Choose another client to copy from")
        mine = {e.m.ledger_key for e in self.entries(client_id)}
        copied = kept = 0
        for e in self.entries(from_client_id, include_inactive=False):
            m = e.m
            if m.ledger_key in mine and not overwrite:
                kept += 1
                continue
            self.save(client_id, m.ledger_key, m.acct_class, m.gst_class, user, m.gst_source, m.head_9c,
                      m.eligibility, f"copied from client #{from_client_id}" + (f" – {m.note}" if m.note else ""),
                      source="copied")
            copied += 1
        return copied, kept
