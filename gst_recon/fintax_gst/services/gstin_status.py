"""Supplier GSTIN status: registration status (active / cancelled / suspended), cancellation date, taxpayer type
and filing frequency, kept from lists the user downloads (portal 'Search Taxpayer' results, a verification
service's export) or enters. The program does not query the portal itself.

ITC from a supplier whose registration was cancelled is not available on invoices dated after the cancellation;
a suspended registration puts its invoices on hold; a composition supplier cannot charge tax.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.gstin import normalize_gstin, validate_gstin
from ..core.models import DocType, Source
from ..core.money import ZERO
from ..db.database import Database
from ..db.models import GstinStatus
from ..importers.parsing import parse_date
from ..importers.readers import UnsupportedFileError, read_csv, read_excel, read_json
from .common import ServiceError, audit

COLS = {"gstin": ("gstin", "gstin/uin", "gstin uin", "gst no", "gst number"),
        "legal": ("legal name", "legal name of business", "lgnm", "name"),
        "trade": ("trade name", "tradenam", "trade name of business"),
        "status": ("status", "gstin status", "sts", "registration status"),
        "cancelled": ("date of cancellation", "cancellation date", "cxdt", "cancelled on", "effective date of "
                                                                                           "cancellation"),
        "registered": ("date of registration", "registration date", "rgdt", "effective date of registration"),
        "type": ("taxpayer type", "type", "dty", "constitution", "nature of taxpayer"),
        "frequency": ("filing frequency", "return filing frequency", "frequency")}
STALE_DAYS = 90


def _norm(v) -> str:
    return " ".join(re.sub(r"[^a-z0-9/ ]", " ", str(v or "").lower()).split())


def _status(text: str) -> str:
    t = (text or "").strip().lower()
    for word, out in (("cancel", "Cancelled"), ("suspend", "Suspended"), ("inactive", "Inactive"),
                      ("provisional", "Provisional"), ("active", "Active")):
        if word in t:
            return out
    return text.strip().title()


@dataclass
class StatusFlag:
    gstin: str
    name: str
    status: str
    cancelled_on: date | None
    invoices: int
    itc: Decimal
    message: str
    severity: str  # high / medium / info


class GstinStatusService:
    def __init__(self, db: Database):
        self.db = db

    def save(self, gstin: str, status: str, user: str = "", cancelled_on: date | None = None, legal_name: str = "",
             trade_name: str = "", taxpayer_type: str = "", filing_frequency: str = "",
             registered_on: date | None = None, checked_on: date | None = None, source: str = "entered",
             _session=None) -> GstinStatus:
        g = normalize_gstin(gstin)
        ok, problem = validate_gstin(g)
        if not ok or problem:  # a wrong check digit is a typing mistake: not kept
            raise ServiceError(f"{gstin}: {problem}")
        values = dict(legal_name=legal_name.strip()[:200], trade_name=trade_name.strip()[:200],
                      status=_status(status)[:20], cancelled_on=cancelled_on, registered_on=registered_on,
                      taxpayer_type=taxpayer_type.strip()[:40], filing_frequency=filing_frequency.strip().title()[:20],
                      checked_on=checked_on or date.today(), source=source[:120], updated_by=user[:80])

        def apply(s):
            row = s.get(GstinStatus, g)
            if row is None:
                row = GstinStatus(gstin=g, **values)
                s.add(row)
            else:
                for k, v in values.items():
                    if v not in ("", None) or k in ("cancelled_on",):
                        setattr(row, k, v)
            return row

        if _session is not None:
            return apply(_session)
        with self.db.session() as s:
            row = apply(s)
            audit(s, "GSTIN_STATUS", "gstin_status", g, {"status": row.status, "cancelled_on": row.cancelled_on},
                  user)
            s.flush()
            s.expunge(row)
        return row

    def import_file(self, path: str | Path, user: str = "") -> tuple[int, list[str]]:
        """Excel / CSV list with a GSTIN and a status column, or portal search JSON (one record or a list)."""
        path = Path(path)
        records: list[dict] = []
        problems: list[str] = []
        if path.suffix.lower() == ".json":
            js = read_json(path)
            items = js if isinstance(js, list) else js.get("data", js) if isinstance(js, dict) else []
            items = items if isinstance(items, list) else [items]
            for it in items:
                if isinstance(it, dict) and it.get("gstin"):
                    records.append({"gstin": it.get("gstin"), "legal": it.get("lgnm", ""),
                                    "trade": it.get("tradeNam", ""), "status": it.get("sts", ""),
                                    "cancelled": it.get("cxdt", ""), "registered": it.get("rgdt", ""),
                                    "type": it.get("dty", ""), "frequency": it.get("frequency", ""), "row": "json"})
        else:
            tables = [read_csv(path, path.name)] if path.suffix.lower() == ".csv" else read_excel(path)
            for t in tables:
                cols = None
                for n, vals in t.rows:
                    if cols is None:
                        names = [_norm(v) for v in vals]
                        found = {k: next((names.index(o) for o in opts if o in names), None) for k, opts in COLS.items()}
                        if found["gstin"] is not None and found["status"] is not None:
                            cols = found
                        continue
                    rec = {k: (vals[i] if i is not None and i < len(vals) else None) for k, i in cols.items()}
                    rec["row"] = f"{t.name}!{n}"
                    if rec.get("gstin"):
                        records.append(rec)
        if not records:
            raise UnsupportedFileError(f"{path.name}: no GSTIN status list found – it needs GSTIN and status columns")
        saved = 0
        with self.db.session() as s:
            for r in records:
                try:
                    def d(v):
                        try:
                            return parse_date(v) if v not in (None, "", "NA") else None
                        except ValueError:
                            return None

                    self.save(str(r["gstin"]), str(r.get("status") or ""), user, d(r.get("cancelled")),
                              str(r.get("legal") or ""), str(r.get("trade") or ""), str(r.get("type") or ""),
                              str(r.get("frequency") or ""), d(r.get("registered")), source=path.name[:120],
                              _session=s)
                    saved += 1
                except ServiceError as exc:
                    problems.append(f"{r['row']}: {exc}")
            audit(s, "IMPORT", "gstin_status", path.name, {"saved": saved, "problems": len(problems)}, user)
        return saved, problems

    def get(self, gstins: list[str] | None = None) -> dict[str, GstinStatus]:
        with self.db.session() as s:
            q = select(GstinStatus)
            if gstins is not None:
                q = q.where(GstinStatus.gstin.in_(list(gstins)))
            return {r.gstin: r for r in s.scalars(q)}

    def client_suppliers(self, client_id: int, months: list[str] | None = None) -> dict[str, list]:
        """GSTIN -> the client's purchase-register documents from that supplier."""
        from .itc import ItcService

        with self.db.session() as s:
            docs = ItcService(self.db)._docs(s, client_id, Source.BOOKS, months)
        out: dict[str, list] = {}
        for d in docs:
            out.setdefault(d.supplier_gstin, []).append(d)
        return out

    def flags(self, client_id: int, months: list[str] | None = None, today: date | None = None) -> list[StatusFlag]:
        today = today or date.today()
        by = self.client_suppliers(client_id, months)
        st = self.get(list(by))
        out = []
        for g, docs in by.items():
            name = next((d.supplier_name for d in docs if d.supplier_name), "")

            def itc(ds):
                return sum(((-1 if d.doc_type == DocType.CREDIT_NOTE else 1) * (d.igst + d.cgst + d.sgst + d.cess)
                            for d in ds), ZERO)

            row = st.get(g)
            if row is None:
                out.append(StatusFlag(g, name, "Not checked", None, len(docs), itc(docs),
                                      "status not checked – include it in the list to verify", "info"))
                continue
            if row.status == "Cancelled":
                after = [d for d in docs if row.cancelled_on and d.invoice_date > row.cancelled_on]
                if after:
                    out.append(StatusFlag(g, name, row.status, row.cancelled_on, len(after), itc(after),
                                          f"{len(after)} bill(s) dated after cancellation on "
                                          f"{row.cancelled_on:%d-%m-%Y} – ITC not available", "high"))
                else:
                    out.append(StatusFlag(g, name, row.status, row.cancelled_on, len(docs), itc(docs),
                                          "registration cancelled" + (f" on {row.cancelled_on:%d-%m-%Y}" if
                                                                      row.cancelled_on else "") +
                                          " – check the bills appear in GSTR-2B before claiming", "medium"))
            elif row.status in ("Suspended", "Inactive"):
                out.append(StatusFlag(g, name, row.status, None, len(docs), itc(docs),
                                      f"registration {row.status.lower()} – hold the ITC until it is restored",
                                      "high"))
            elif "composition" in row.taxpayer_type.lower() and itc(docs) > 0:
                out.append(StatusFlag(g, name, row.status, None, len(docs), itc(docs),
                                      "composition dealer cannot charge GST – ITC on its bills is not available",
                                      "high"))
            elif (today - row.checked_on).days > STALE_DAYS:
                out.append(StatusFlag(g, name, row.status, None, len(docs), itc(docs),
                                      f"last checked on {row.checked_on:%d-%m-%Y} – check again", "info"))
        order = {"high": 0, "medium": 1, "info": 2}
        return sorted(out, key=lambda f: (order[f.severity], -f.itc))

    def to_verify_csv(self, client_id: int, path: str | Path, today: date | None = None) -> tuple[Path, int]:
        """The client's suppliers not checked (or checked long ago), ready to check on the portal."""
        flags = [f for f in self.flags(client_id, today=today) if f.severity == "info"]
        path = Path(path)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            import csv

            w = csv.writer(fh)
            w.writerow(["GSTIN", "Supplier", "Status", "Legal Name", "Trade Name", "Date of Cancellation",
                        "Taxpayer Type", "Filing Frequency"])
            for f in flags:
                w.writerow([f.gstin, f.name, "", "", "", "", "", ""])
        return path, len(flags)


__all__ = ["GstinStatusService", "json"]
