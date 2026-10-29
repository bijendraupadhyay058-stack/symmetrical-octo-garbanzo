"""GSTR-3B Table 4 (eligible ITC) import.

Accepted inputs:

* GST portal / offline-tool JSON (``ret_period`` + ``itc_elg`` with ``itc_avl``,
  ``itc_rev``, ``itc_net`` and ``itc_inelg``).
* A standard template (CSV or Excel) with the columns
  ``Period, Table, IGST, CGST, SGST, Cess`` (an optional ``Description`` column is
  ignored). One file may hold several periods.

Table codes follow the GSTR-3B form as amended by Notification 14/2022-CT (see ``TABLE4``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, AmountParseError, parse_amount
from .column_mapping import normalize_header
from .parsing import parse_period
from .readers import UnsupportedFileError, read_csv, read_excel, read_json

TABLE4 = {
    "4A1": "4(A)(1) Import of goods",
    "4A2": "4(A)(2) Import of services",
    "4A3": "4(A)(3) Inward supplies liable to reverse charge (other than 1 & 2)",
    "4A4": "4(A)(4) Inward supplies from ISD",
    "4A5": "4(A)(5) All other ITC",
    "4B1": "4(B)(1) Reversed as per rules 38, 42 & 43 of CGST Rules and section 17(5)",
    "4B2": "4(B)(2) Reversed – others",
    "4C": "4(C) Net ITC available (A) − (B)",
    "4D1": "4(D)(1) ITC reclaimed which was reversed under 4(B)(2) in an earlier period",
    "4D2": "4(D)(2) Ineligible ITC under section 16(4) & ITC restricted due to PoS rules",
}
_JSON_AVL = {"IMPG": "4A1", "IMPS": "4A2", "ISRC": "4A3", "ISD": "4A4", "OTH": "4A5"}
_JSON_REV = {"RUL": "4B1", "OTH": "4B2"}
_JSON_INELG = {"RUL": "4D1", "OTH": "4D2"}
_HEADERS = {"period": ["period", "tax period", "return period", "month"],
            "table": ["table", "table code", "row", "gstr 3b table"],
            "igst": ["igst", "integrated tax"], "cgst": ["cgst", "central tax"],
            "sgst": ["sgst", "state ut tax", "state tax", "sgst utgst"], "cess": ["cess"]}


@dataclass
class Gstr3bValues:
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def __add__(self, other: "Gstr3bValues") -> "Gstr3bValues":
        return Gstr3bValues(self.igst + other.igst, self.cgst + other.cgst, self.sgst + other.sgst,
                            self.cess + other.cess)

    def __sub__(self, other: "Gstr3bValues") -> "Gstr3bValues":
        return Gstr3bValues(self.igst - other.igst, self.cgst - other.cgst, self.sgst - other.sgst,
                            self.cess - other.cess)


@dataclass
class Gstr3bPreview:
    file_path: Path
    layout: str
    entries: dict[str, dict[str, Gstr3bValues]] = field(default_factory=dict)  # period -> table -> values
    warnings: list[str] = field(default_factory=list)

    @property
    def periods(self) -> list[str]:
        return sorted(self.entries)


def normalize_table_code(text) -> str | None:
    code = "".join(ch for ch in str(text or "").upper() if ch.isalnum())
    code = code.replace("TABLE", "")
    return code if code in TABLE4 else None


def _amount(value, where: str) -> Decimal:
    try:
        return parse_amount(value) or ZERO
    except AmountParseError as exc:
        raise ValueError(f"{where}: {exc}") from exc


def _from_json(js: dict, period: str | None, preview: Gstr3bPreview) -> None:
    data = js.get("data", js)
    p = parse_period(data.get("ret_period") or data.get("rtnprd")) or period
    if not p:
        raise ValueError("GSTR-3B JSON has no ret_period – specify the period (YYYY-MM)")
    elg = data.get("itc_elg")
    if not isinstance(elg, dict):
        raise UnsupportedFileError("JSON has no 'itc_elg' (GSTR-3B Table 4) section")
    table: dict[str, Gstr3bValues] = {}

    def vals(d, where):
        return Gstr3bValues(_amount(d.get("iamt"), where), _amount(d.get("camt"), where),
                            _amount(d.get("samt"), where), _amount(d.get("csamt"), where))

    for key, mapping in (("itc_avl", _JSON_AVL), ("itc_rev", _JSON_REV), ("itc_inelg", _JSON_INELG)):
        for item in elg.get(key, []) or []:
            code = mapping.get(str(item.get("ty", "")).upper())
            if code is None:
                preview.warnings.append(f"Unknown {key} type '{item.get('ty')}' ignored")
                continue
            table[code] = table.get(code, Gstr3bValues()) + vals(item, f"{key}/{item.get('ty')}")
    if isinstance(elg.get("itc_net"), dict):
        table["4C"] = vals(elg["itc_net"], "itc_net")
    preview.entries[p] = table


def _from_table(rows: list[tuple[int, list]], period: str | None, preview: Gstr3bPreview) -> None:
    header_at, cols = None, {}
    for i, (_n, values) in enumerate(rows[:20]):
        names = [normalize_header(v) for v in values]
        found = {f: names.index(s) for f, syns in _HEADERS.items() for s in syns if s in names}
        if "table" in found and ("igst" in found or "cgst" in found):
            header_at, cols = i, found
            break
    if header_at is None:
        raise UnsupportedFileError("No GSTR-3B template heading row (Period, Table, IGST, CGST, SGST, Cess) found")
    for n, values in rows[header_at + 1:]:
        if not any(v not in (None, "") for v in values):
            continue

        def cell(f):
            i = cols.get(f)
            return values[i] if i is not None and i < len(values) else None

        code = normalize_table_code(cell("table"))
        if code is None:
            preview.warnings.append(f"Row {n}: table '{cell('table')}' is not a GSTR-3B Table 4 code – skipped")
            continue
        p = parse_period(cell("period")) if cell("period") not in (None, "") else period
        if not p:
            raise ValueError(f"Row {n}: period missing – add a Period column or specify the period")
        v = Gstr3bValues(*(_amount(cell(k), f"row {n} {k.upper()}") for k in ("igst", "cgst", "sgst", "cess")))
        table = preview.entries.setdefault(p, {})
        if code in table:
            preview.warnings.append(f"Row {n}: {p} table {code} appears more than once – values added")
            v = table[code] + v
        table[code] = v


def preview_gstr3b(path: str | Path, period: str | None = None) -> Gstr3bPreview:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    period = parse_period(period) if period else None
    suffix = path.suffix.lower()
    if suffix == ".json":
        preview = Gstr3bPreview(path, "GSTR-3B JSON")
        _from_json(read_json(path), period, preview)
    elif suffix == ".csv":
        preview = Gstr3bPreview(path, "GSTR-3B template (CSV)")
        _from_table(read_csv(path, path.name).rows, period, preview)
    elif suffix in (".xlsx", ".xlsm"):
        preview = Gstr3bPreview(path, "GSTR-3B template (Excel)")
        _from_table(read_excel(path)[0].rows, period, preview)
    else:
        raise UnsupportedFileError("GSTR-3B: use the portal JSON or the CSV/Excel template")
    if not preview.entries:
        raise ValueError("No GSTR-3B Table 4 values found in the file")
    for p, table in preview.entries.items():
        if "4C" not in table:  # derive net ITC when the file does not state it
            a = sum((table.get(c, Gstr3bValues()) for c in ("4A1", "4A2", "4A3", "4A4", "4A5")), Gstr3bValues())
            b = sum((table.get(c, Gstr3bValues()) for c in ("4B1", "4B2")), Gstr3bValues())
            table["4C"] = a - b
            preview.warnings.append(f"{p}: 4(C) not in file – derived as 4(A) − 4(B)")
        else:
            a = sum((table.get(c, Gstr3bValues()) for c in ("4A1", "4A2", "4A3", "4A4", "4A5")), Gstr3bValues())
            b = sum((table.get(c, Gstr3bValues()) for c in ("4B1", "4B2")), Gstr3bValues())
            if abs((a - b).total - table["4C"].total) > Decimal("1"):
                preview.warnings.append(f"{p}: 4(C) {table['4C'].total} differs from 4(A) − 4(B) = {(a - b).total}")
    return preview
