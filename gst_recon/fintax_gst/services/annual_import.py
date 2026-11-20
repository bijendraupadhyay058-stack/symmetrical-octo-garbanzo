"""GSTR-9 and GSTR-9C prepared elsewhere (offline tool, portal, a firm's template): saved for the client and year
and compared with this program's working, table by table."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..db.database import Database
from ..db.models import AppSetting
from ..gstr9.annual_import import AnnualFile, read_annual
from ..importers.gstr3b import Gstr3bValues as V
from ..importers.pipeline import sha256_of
from .common import ServiceError, audit

HEADS = ("taxable", "igst", "cgst", "sgst", "cess")


@dataclass
class CompareRow:
    code: str
    label: str
    file_taxable: Decimal | None
    file_tax: Decimal | None
    ours_taxable: Decimal | None
    ours_tax: Decimal | None

    @property
    def diff(self) -> Decimal | None:
        """File − working (tax; the taxable value where a table has no tax)."""
        if self.file_tax is None or self.ours_tax is None:
            return None
        if self.file_tax or self.ours_tax:
            return self.file_tax - self.ours_tax
        return (self.file_taxable or 0) - (self.ours_taxable or 0)


def _tax(v: V) -> Decimal:
    return v.igst + v.cgst + v.sgst + v.cess


class AnnualImportService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _key(kind: str, client_id: int, fy: str) -> str:
        return f"annual_file:{kind}:{client_id}:{fy}"

    def read(self, path: str | Path, kind: str) -> AnnualFile:
        if kind not in ("GSTR9", "GSTR9C"):
            raise ServiceError(f"Unknown return {kind}")
        return read_annual(path, kind)

    def save(self, client_id: int, fy: str, path: str | Path, kind: str, user: str | None = None) -> AnnualFile:
        """Keep the file's figures for the client and year (a later file replaces the earlier one)."""
        from .clients import ClientService

        path = Path(path)
        af = self.read(path, kind)
        client = ClientService(self.db).get(client_id)
        if af.gstin and af.gstin != client.gstin:
            raise ServiceError(f"{path.name} is for GSTIN {af.gstin}, not {client.gstin}")
        if af.fy and af.fy != fy:
            raise ServiceError(f"{path.name} is for {af.fy}, not {fy} – choose that year in the header")
        payload = {"file": path.name, "sha256": sha256_of(path),
                   "values": {c: [str(getattr(v, h)) for h in HEADS] for c, v in af.values.items()},
                   "amounts": {c: str(a) for c, a in af.amounts.items()}, "skipped": af.skipped}
        with self.db.session() as s:
            row = s.get(AppSetting, self._key(kind, client_id, fy))
            before = json.loads(row.value_json).get("file") if row else None
            if row is None:
                row = AppSetting(key=self._key(kind, client_id, fy), value_json="{}")
                s.add(row)
            row.value_json = json.dumps(payload)
            audit(s, "IMPORT", "annual_file", f"{kind}:{fy}", {"file": path.name, "replaces": before,
                                                              "tables": len(af.values) + len(af.amounts)},
                  user, client_id)
        return af

    def saved(self, client_id: int, fy: str, kind: str) -> tuple[str, AnnualFile] | None:
        with self.db.session() as s:
            row = s.get(AppSetting, self._key(kind, client_id, fy))
            if row is None:
                return None
            p = json.loads(row.value_json)
        af = AnnualFile(kind, values={c: V(*(Decimal(x) for x in (v[1], v[2], v[3], v[4], v[0])))
                                      for c, v in p.get("values", {}).items()},
                        amounts={c: Decimal(a) for c, a in p.get("amounts", {}).items()}, skipped=p.get("skipped", []))
        return p.get("file", ""), af

    # ------------------------------------------------------------ compare
    def compare_9(self, client_id: int, fy: str, af: AnnualFile | None = None) -> list[CompareRow]:
        from ..gstr9.working import LABELS
        from .gstr9 import Gstr9Service
        from .itc import ItcService

        if af is None:
            got = self.saved(client_id, fy, "GSTR9")
            if got is None:
                return []
            af = got[1]
        w = Gstr9Service(self.db).working(client_id, fy)
        ours: dict[str, V] = {}
        for r in w.table4 + w.table5 + w.table6 + w.table7 + w.table10_14:
            if r.gstr1 is not None:
                ours[r.code] = r.gstr1
        try:
            t8 = ItcService(self.db).annual(client_id, fy)
            ours.update({"8A": t8.a, "8B": t8.b, "8C": t8.c})
        except ServiceError:
            pass
        file_vals = dict(af.values)
        # the working shows 6C+6D and 7A–7G together
        for combined, parts in (("6C+6D", ("6C", "6D")), ("7A–7G", ("7A", "7B", "7C", "7D", "7E", "7F", "7G"))):
            if combined in ours and any(p in file_vals for p in parts):
                total = V()
                for p in parts:
                    v = file_vals.pop(p, V())
                    total = V(total.igst + v.igst, total.cgst + v.cgst, total.sgst + v.sgst, total.cess + v.cess,
                              total.taxable + v.taxable)
                file_vals[combined] = total

        def order(code):
            import re

            m = re.match(r"(\d+)(.*)", code)
            return (int(m.group(1)), m.group(2)) if m else (99, code)

        rows = []
        for code in sorted(set(file_vals) | set(ours), key=order):
            f, o = file_vals.get(code), ours.get(code)
            if f is None and (o is None or not (o.taxable or _tax(o))):
                continue
            rows.append(CompareRow(code, LABELS.get(code, {"8A": "ITC as per GSTR-2B (Table 8A)",
                                                           "8B": "ITC as per 6B and 6H", "8C": "ITC availed in the "
                                                           "next year"}.get(code, code)),
                                   f.taxable if f else None, _tax(f) if f else None,
                                   o.taxable if o else None, _tax(o) if o else None))
        return rows

    def compare_9c(self, client_id: int, fy: str, af: AnnualFile | None = None) -> list[CompareRow]:
        from ..gstr9.reconciliation_9c import LABELS
        from .gstr9c import Gstr9cService

        if af is None:
            got = self.saved(client_id, fy, "GSTR9C")
            if got is None:
                return []
            af = got[1]
        st = Gstr9cService(self.db).statement(client_id, fy)
        rows = []
        for code, amount in af.amounts.items():
            try:
                ours = st.line(code).amount
            except (StopIteration, KeyError):
                ours = None
            rows.append(CompareRow(code, LABELS.get(code, code), None, amount, None, ours))
        return rows

    def use_9c_amounts(self, client_id: int, fy: str, session, af: AnnualFile | None = None) -> int:
        """Record the GSTR-9C file's audited figures (Tables 5, 7B–7D, 12A–12C) as the entered amounts."""
        from ..gstr9.reconciliation_9c import INPUT_ITEMS
        from .gstr9c import Gstr9cService

        if af is None:
            got = self.saved(client_id, fy, "GSTR9C")
            if got is None:
                raise ServiceError("Import the GSTR-9C file first")
            af = got[1]
        svc = Gstr9cService(self.db)
        n = 0
        for code, amount in af.amounts.items():
            if code in INPUT_ITEMS:
                svc.set_input(client_id, fy, code, amount, "from the imported GSTR-9C", by=session)
                n += 1
        return n
