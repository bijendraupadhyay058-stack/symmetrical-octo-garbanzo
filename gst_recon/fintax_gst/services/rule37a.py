"""Rule 37A: reversal of ITC where the supplier has not furnished GSTR-3B.

ITC availed on a supplier's documents of a tax period (as shown in GSTR-2B) must be reversed when the supplier has
not furnished its GSTR-3B for that period by **30 September** following the end of the financial year; the reversal
is made in a GSTR-3B filed on or before **30 November** (Table 4B(2)), and the ITC may be re-availed (Table 4A(5))
once the supplier furnishes the return.

Filing status comes from the supplier filing register (table ``supplier_filings``): imported from GSTR-2A (JSON
``cfs3b``, or Excel *GSTR-3B Filing Status*), from a list (GSTIN, period, filed, date of filing) or entered by a
user. Where it is not known the line says so – nothing is assumed. The register only lists and records; the
reversal itself is made in GSTR-3B by the user.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from ..core.money import ZERO
from ..db.database import Database
from ..db.models import Client, Invoice, Rule37aAction, SupplierFiling
from ..itc.annual import fy_months
from .common import ServiceError, audit

HEADS = ("igst", "cgst", "sgst", "cess")
STATES = {"filed": "Filed in time", "filed_late": "Filed after 30 Sep – reverse, then re-avail",
          "not_filed": "Not filed – reverse", "unknown": "Filing status not known – check"}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"], start=1)}


def check_date(fy: str) -> date:
    return date(int(fy[:4]) + 1, 9, 30)


def reverse_by(fy: str) -> date:
    return date(int(fy[:4]) + 1, 11, 30)


def parse_period(v) -> str | None:
    """A tax period in any usual form → ``YYYY-MM``: 2025-06, 06-2025, 062025 (portal), Jun-25, June 2025, a date."""
    if v in (None, ""):
        return None
    if isinstance(v, (date, datetime)):
        return f"{v:%Y-%m}"
    t = str(v).strip().lower()
    if m := re.fullmatch(r"(\d{4})[-/ ](\d{1,2})", t):
        y, mo = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[-/ ]?(\d{4})", t):
        mo, y = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"([a-z]{3})[a-z]*[-/ ']*(\d{2}|\d{4})", t):
        mo, y = _MONTHS.get(m.group(1), 0), int(m.group(2))
        y += 2000 if y < 100 else 0
    else:
        return None
    return f"{y}-{mo:02d}" if 1 <= mo <= 12 and 2017 <= y <= 2100 else None


def _filed(v) -> bool | None:
    t = str(v or "").strip().lower()
    if t in ("y", "yes", "filed", "true", "1", "submitted"):
        return True
    if t in ("n", "no", "not filed", "false", "0", "not submitted", "pending"):
        return False
    return None


def _quarter_end(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{y}-{((m - 1) // 3 + 1) * 3:02d}"


@dataclass
class Line:
    gstin: str
    name: str
    period: str
    docs: int
    tax: dict[str, Decimal]
    state: str
    filed_on: date | None = None
    status_source: str = ""
    reversed_in: str = ""
    reclaimed_in: str = ""
    note: str = ""
    invoices: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum(self.tax.values(), ZERO)

    @property
    def to_reverse(self) -> bool:
        return self.state in ("not_filed", "filed_late")

    @property
    def action(self) -> str:
        if self.state == "unknown":
            return "Find the supplier's GSTR-3B filing status (import GSTR-2A or enter it)"
        if self.state == "filed":
            return "No reversal"
        if not self.reversed_in:
            return "Reverse in GSTR-3B Table 4B(2)"
        if self.state == "filed_late" and not self.reclaimed_in:
            return "Supplier has filed – re-avail in GSTR-3B Table 4A(5)"
        return "Reclaimed" if self.reclaimed_in else "Reversed – re-avail when the supplier files"


@dataclass
class Rule37aWorking:
    client: str
    gstin: str
    fy: str
    today: date
    lines: list[Line] = field(default_factory=list)

    @property
    def check_date(self) -> date:
        return check_date(self.fy)

    @property
    def reverse_by(self) -> date:
        return reverse_by(self.fy)

    @property
    def provisional(self) -> bool:
        return self.today <= self.check_date

    def total(self, which: str) -> Decimal:
        pick = {"reverse": lambda ln: ln.to_reverse, "pending": lambda ln: ln.to_reverse and not ln.reversed_in,
                "reversed": lambda ln: bool(ln.reversed_in) and not ln.reclaimed_in,
                "reclaim": lambda ln: ln.state == "filed_late" and bool(ln.reversed_in) and not ln.reclaimed_in,
                "unknown": lambda ln: ln.state == "unknown"}[which]
        return sum((ln.total for ln in self.lines if pick(ln)), ZERO)


class Rule37aService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ filing register
    def set_status(self, gstin: str, period: str, filed: bool | None, filed_on: date | None = None,
                   source: str = "entered", user: str = "", checked_on: date | None = None) -> None:
        gstin = gstin.strip().upper()
        p = parse_period(period)
        if len(gstin) != 15 or p is None:
            raise ServiceError(f"Give a 15-character GSTIN and a tax period (not {gstin!r} / {period!r})")
        with self.db.session() as s:
            self._put(s, gstin, p, filed, filed_on, source, user, checked_on or date.today())
            s.commit()

    @staticmethod
    def _put(s, gstin, period, filed, filed_on, source, user, checked_on):
        row = s.scalars(select(SupplierFiling).where(SupplierFiling.gstin == gstin,
                                                     SupplierFiling.period == period)).first()
        if row is None:
            row = SupplierFiling(gstin=gstin, period=period, checked_on=checked_on)
            s.add(row)
        elif filed is None and row.gstr3b_filed is not None:
            return  # an unknown status never overwrites a known one
        if filed_on and filed is None:
            filed = True
        row.gstr3b_filed, row.filed_on = filed, filed_on if filed else None
        row.checked_on, row.source, row.updated_by = checked_on, source[:120], (user or "")[:80]

    def import_file(self, path: str | Path, user: str = "") -> tuple[int, list[str]]:
        """GSTR-2A (JSON / Excel) or a filing list (Excel / CSV: GSTIN, period, GSTR-3B filed, date of filing)."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        rows, notes = (self._from_json(path) if path.suffix.lower() == ".json" else self._from_table(path))
        if not rows:
            raise ServiceError("No GSTR-3B filing status found – use the GSTR-2A download (JSON or Excel), or a list "
                               "with columns GSTIN, Tax period, GSTR-3B filed (Y/N) and Date of filing")
        with self.db.session() as s:
            today = date.today()
            for gstin, period, filed, on in rows:
                self._put(s, gstin, period, filed, on, f"{path.name}", user, today)
            s.commit()
        return len(rows), notes

    @staticmethod
    def _from_json(path: Path):
        try:
            js = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceError(f"Not a JSON file: {exc}") from None
        data = js.get("data", js) if isinstance(js, dict) else {}
        fp = parse_period(data.get("fp") or data.get("rtnprd"))
        rows, notes = {}, []
        for key in ("b2b", "b2ba", "cdn", "cdna"):
            for sup in data.get(key) or []:
                if not isinstance(sup, dict) or "cfs3b" not in sup:
                    continue
                period = parse_period(sup.get("flprdr1")) or fp
                if not sup.get("ctin") or not period:
                    continue
                rows[(sup["ctin"].upper(), period)] = (sup["ctin"].upper(), period, _filed(sup.get("cfs3b")), None)
        if not rows:
            notes.append("The JSON has no 'cfs3b' (GSTR-3B filing status) – download GSTR-2A, not GSTR-2B")
        return list(rows.values()), notes

    @staticmethod
    def _from_table(path: Path):
        from ..importers.column_mapping import normalize_header
        from ..importers.parsing import parse_date
        from ..importers.readers import read_csv, read_excel

        tables = [read_csv(path, path.name)] if path.suffix.lower() == ".csv" else read_excel(path)
        cols = {"gstin": ("gstin of supplier", "supplier gstin", "gstin", "gstin/uin of supplier"),
                "period": ("tax period", "return period", "period", "gstr-3b period", "filing period",
                           "gstr-1/iff/gstr-5 filing period", "gstr-1/iff/gstr-1a/5 filing period"),
                "status": ("gstr-3b filing status", "gstr-3b filed", "gstr 3b filing status", "gstr-3b status",
                           "3b filed", "filed", "status"),
                "date": ("gstr-3b filing date", "date of filing", "filed on", "date of filing of gstr-3b")}
        rows, notes = {}, []
        for t in tables:
            found, at = {}, None
            for i, (_n, values) in enumerate(t.rows[:15]):
                names = [normalize_header(v) for v in values]
                found = {}
                for k, opts in cols.items():
                    hit = next((names.index(normalize_header(o)) for o in opts if normalize_header(o) in names), None)
                    if hit is not None and hit not in found.values():
                        found[k] = hit
                if "gstin" in found and ("status" in found or "date" in found):
                    at = i
                    break
            if at is None:
                continue
            for n, values in t.rows[at + 1:]:
                def cell(k, values=values):
                    i = found.get(k)
                    return values[i] if i is not None and i < len(values) else None

                g = str(cell("gstin") or "").strip().upper()
                p = parse_period(cell("period"))
                if len(g) != 15:
                    continue
                if p is None:
                    notes.append(f"{t.name} row {n}: no tax period – skipped")
                    continue
                on = cell("date")
                try:
                    on = on if isinstance(on, date) else (parse_date(on) if on not in (None, "") else None)
                except (ValueError, TypeError):
                    on = None
                if isinstance(on, datetime):
                    on = on.date()
                filed = _filed(cell("status")) if "status" in found else None
                if filed is None and on:
                    filed = True
                rows[(g, p)] = (g, p, filed, on)
        return list(rows.values()), notes

    def statuses(self, gstins: list[str]) -> dict[tuple[str, str], SupplierFiling]:
        out = {}
        with self.db.session() as s:
            for i in range(0, len(gstins), 500):
                for r in s.scalars(select(SupplierFiling).where(SupplierFiling.gstin.in_(gstins[i:i + 500]))):
                    out[(r.gstin, r.period)] = r
        return out

    # ------------------------------------------------------------ working
    def working(self, client_id: int, fy: str, today: date | None = None) -> Rule37aWorking:
        today = today or date.today()
        return self.db.cached(("rule37a", client_id, fy, today), lambda: self._working(client_id, fy, today))

    def _working(self, client_id: int, fy: str, today: date) -> Rule37aWorking:
        months = fy_months(fy)
        with self.db.session() as s:
            c = s.get(Client, client_id)
            if c is None:
                raise ServiceError(f"Client {client_id} not found")
            docs = s.execute(select(Invoice.supplier_gstin, Invoice.supplier_name, Invoice.period,
                                    Invoice.doc_type, Invoice.invoice_no, Invoice.igst, Invoice.cgst,
                                    Invoice.sgst, Invoice.cess, Invoice.itc_availability, Invoice.reverse_charge)
                             .where(Invoice.client_id == client_id, Invoice.source_type == "GSTR2B",
                                    Invoice.period.in_(months))).all()
            actions = {(a.gstin, a.period): a for a in s.scalars(select(Rule37aAction).where(
                Rule37aAction.client_id == client_id))}
            w = Rule37aWorking(c.name, c.gstin, fy, today)
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for d in docs:
            if d.reverse_charge or (d.itc_availability or "").upper() == "N" or not d.supplier_gstin:
                continue
            groups[(d.supplier_gstin, d.period)].append(d)
        status = self.statuses(sorted({g for g, _p in groups}))
        limit = check_date(fy)
        for (g, p), ds in sorted(groups.items()):
            tax = {h: ZERO for h in HEADS}
            for d in ds:
                sign = -1 if d.doc_type == "CRN" else 1
                for h in HEADS:
                    tax[h] += sign * (getattr(d, h) or ZERO)
            if sum(tax.values(), ZERO) <= 0:
                continue
            st = status.get((g, p)) or status.get((g, _quarter_end(p)))
            if st is None or st.gstr3b_filed is None:
                state = "unknown"
            elif not st.gstr3b_filed:
                state = "not_filed"
            elif st.filed_on and st.filed_on > limit:
                state = "filed_late"
            else:
                state = "filed"
            a = actions.get((g, p))
            w.lines.append(Line(g, next((d.supplier_name for d in ds if d.supplier_name), ""), p, len(ds), tax,
                                state, st.filed_on if st else None, st.source if st else "",
                                a.reversed_in if a else "", a.reclaimed_in if a else "", a.note if a else "",
                                [d.invoice_no for d in ds][:20]))
        order = {"not_filed": 0, "filed_late": 1, "unknown": 2, "filed": 3}
        w.lines.sort(key=lambda ln: (order[ln.state], -ln.total, ln.gstin, ln.period))
        return w

    def record(self, client_id: int, gstin: str, period: str, reversed_in: str | None = None,
               reclaimed_in: str | None = None, note: str = "", user: str = "") -> None:
        """Record the GSTR-3B month of the reversal / re-availment ('' clears it)."""
        vals = {}
        for k, v in (("reversed_in", reversed_in), ("reclaimed_in", reclaimed_in)):
            if v is None:
                continue
            p = parse_period(v) if v else ""
            if p is None:
                raise ServiceError(f"Not a month: {v!r} (use e.g. 2026-10)")
            vals[k] = p
        with self.db.session() as s:
            a = s.scalars(select(Rule37aAction).where(Rule37aAction.client_id == client_id,
                                                      Rule37aAction.gstin == gstin,
                                                      Rule37aAction.period == period)).first()
            if a is None:
                a = Rule37aAction(client_id=client_id, gstin=gstin, period=period)
                s.add(a)
            for k, v in vals.items():
                setattr(a, k, v)
            if a.reclaimed_in and not a.reversed_in:
                raise ServiceError("Record the reversal before the re-availment")
            if a.reclaimed_in and a.reversed_in and a.reclaimed_in < a.reversed_in:
                raise ServiceError("Re-availment cannot be in a month before the reversal")
            if note:
                a.note = note
            a.updated_by = (user or "")[:80]
            audit(s, "rule37a", "rule37a_actions", f"{gstin} {period}", vals | {"note": note}, user=user or None,
                  client_id=client_id)
            s.commit()

    # ------------------------------------------------------------ export
    def export_xlsx(self, client_id: int, fy: str, path: str | Path, today: date | None = None) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        w = self.working(client_id, fy, today)
        wb = Workbook()
        ws = wb.active
        ws.title = "Rule 37A"
        ws.append([f"{w.client} ({w.gstin}) – Rule 37A reversal working – FY {fy}"])
        ws["A1"].font = Font(bold=True, size=12)
        ws.append([f"Supplier GSTR-3B to be filed by {w.check_date:%d-%m-%Y}; reverse in GSTR-3B Table 4B(2) by "
                   f"{w.reverse_by:%d-%m-%Y}; re-avail in Table 4A(5) after the supplier files."
                   + (" PROVISIONAL – the 30 September date has not passed." if w.provisional else "")])
        ws.append([])
        heads = ["Supplier GSTIN", "Name", "Tax period", "Documents", "IGST", "CGST", "SGST", "Cess", "Total ITC",
                   "GSTR-3B status", "Filed on", "Status from", "Reversed in", "Re-availed in", "Action", "Note"]
        ws.append(heads)
        for c in ws[4]:
            c.font = Font(bold=True)
        for ln in w.lines:
            ws.append([ln.gstin, ln.name, ln.period, ln.docs, *[float(ln.tax[h]) for h in HEADS], float(ln.total),
                       STATES[ln.state], ln.filed_on, ln.status_source, ln.reversed_in, ln.reclaimed_in, ln.action,
                       ln.note])
        ws.append([])
        for label, k in (("To reverse (not filed / filed late)", "reverse"), ("Not yet reversed", "pending"),
                         ("Reversed, not re-availed", "reversed"), ("Can be re-availed now", "reclaim"),
                         ("Status not known", "unknown")):
            ws.append([label, "", "", "", "", "", "", "", float(w.total(k))])
        for col, wd in zip("ABCDEFGHIJKLMNOP", (18, 30, 10, 10, 12, 12, 12, 10, 14, 34, 12, 24, 12, 12, 44, 30)):
            ws.column_dimensions[col].width = wd
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        return path
