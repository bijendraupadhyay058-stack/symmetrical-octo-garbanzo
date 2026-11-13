"""GSTR-3B Table 4 (eligible ITC) import.

Accepted inputs:

* GST portal / offline-tool JSON (``ret_period`` + ``itc_elg`` with ``itc_avl``,
  ``itc_rev``, ``itc_net`` and ``itc_inelg``).
* The filed GSTR-3B downloaded from the portal as PDF (Tables 3.1 and 4 are read from the text of the form;
  the preview shows what was read, to be checked against the return before saving).
* A standard template (CSV or Excel) with the columns
  ``Period, Table, IGST, CGST, SGST, Cess`` (an optional ``Description`` column is
  ignored). One file may hold several periods.

Table codes follow the GSTR-3B form as amended by Notification 14/2022-CT (see ``TABLE4``).
"""
from __future__ import annotations

import re
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
TABLE31 = {
    "31A": "3.1(a) Outward taxable supplies (other than zero rated, nil rated and exempted)",
    "31B": "3.1(b) Outward taxable supplies (zero rated)",
    "31C": "3.1(c) Other outward supplies (nil rated, exempted)",
    "31D": "3.1(d) Inward supplies (liable to reverse charge)",
    "31E": "3.1(e) Non-GST outward supplies",
}
TABLE61 = {
    "61CASH": "6.1 Tax paid in cash",
    "61ITC": "6.1 Tax paid through ITC",
    "61INT": "6.1 Interest paid in cash",
    "61FEE": "6.1 Late fee paid in cash",
}
ALL_TABLES = {**TABLE31, **TABLE4, **TABLE61}
_JSON_31 = {"osup_det": "31A", "osup_zero": "31B", "osup_nil_exmp": "31C", "isup_rev": "31D", "osup_nongst": "31E"}
_JSON_AVL = {"IMPG": "4A1", "IMPS": "4A2", "ISRC": "4A3", "ISD": "4A4", "OTH": "4A5"}
_JSON_REV = {"RUL": "4B1", "OTH": "4B2"}
_JSON_INELG = {"RUL": "4D1", "OTH": "4D2"}
_HEADERS = {"period": ["period", "tax period", "return period", "month"],
            "taxable": ["taxable value", "taxable", "total taxable value"],
            "table": ["table", "table code", "row", "gstr 3b table"],
            "igst": ["igst", "integrated tax"], "cgst": ["cgst", "central tax"],
            "sgst": ["sgst", "state ut tax", "state tax", "sgst utgst"], "cess": ["cess"]}


@dataclass
class Gstr3bValues:
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO
    taxable: Decimal = ZERO  # used by Table 3.1 rows only

    @property
    def total(self) -> Decimal:
        """Total tax (taxable value excluded)."""
        return self.igst + self.cgst + self.sgst + self.cess

    def __add__(self, other: "Gstr3bValues") -> "Gstr3bValues":
        return Gstr3bValues(self.igst + other.igst, self.cgst + other.cgst, self.sgst + other.sgst,
                            self.cess + other.cess, self.taxable + other.taxable)

    def __sub__(self, other: "Gstr3bValues") -> "Gstr3bValues":
        return Gstr3bValues(self.igst - other.igst, self.cgst - other.cgst, self.sgst - other.sgst,
                            self.cess - other.cess, self.taxable - other.taxable)


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
    return code if code in ALL_TABLES else None


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
    sup = data.get("sup_details")
    pmt = data.get("tx_pmt")
    if not isinstance(elg, dict) and not isinstance(sup, dict) and not isinstance(pmt, dict):
        raise UnsupportedFileError("JSON has neither 'sup_details' (Table 3.1), 'itc_elg' (Table 4) nor 'tx_pmt' "
                                   "(Table 6.1)")
    elg = elg if isinstance(elg, dict) else {}
    table: dict[str, Gstr3bValues] = {}

    def vals(d, where):
        return Gstr3bValues(_amount(d.get("iamt"), where), _amount(d.get("camt"), where),
                            _amount(d.get("samt"), where), _amount(d.get("csamt"), where),
                            _amount(d.get("txval"), where))

    for key, code in _JSON_31.items():
        if isinstance(sup, dict) and isinstance(sup.get(key), dict):
            table[code] = vals(sup[key], key)

    for key, mapping in (("itc_avl", _JSON_AVL), ("itc_rev", _JSON_REV), ("itc_inelg", _JSON_INELG)):
        for item in elg.get(key, []) or []:
            code = mapping.get(str(item.get("ty", "")).upper())
            if code is None:
                preview.warnings.append(f"Unknown {key} type '{item.get('ty')}' ignored")
                continue
            table[code] = table.get(code, Gstr3bValues()) + vals(item, f"{key}/{item.get('ty')}")
    if isinstance(elg.get("itc_net"), dict):
        table["4C"] = vals(elg["itc_net"], "itc_net")
    if isinstance(pmt, dict):
        _payments_from_json(pmt, table, preview)
    preview.entries[p] = table


def _payments_from_json(pmt: dict, table: dict, preview: "Gstr3bPreview") -> None:
    """Table 6.1 from the ``tx_pmt`` block: tax paid in cash (``pdcash``) and through ITC (``pditc``,
    where ``x_pdy`` is credit of tax x used for liability y), interest and late fee paid in cash."""
    def a(d, key):
        return _amount(d.get(key), f"tx_pmt/{key}")

    def rows(x):
        return x if isinstance(x, list) else [x] if isinstance(x, dict) else []

    cash, interest, fee, itc = Gstr3bValues(), Gstr3bValues(), Gstr3bValues(), Gstr3bValues()
    for d in rows(pmt.get("pdcash")):
        cash = cash + Gstr3bValues(a(d, "ipd"), a(d, "cpd"), a(d, "spd"), a(d, "cspd"))
        interest = interest + Gstr3bValues(a(d, "i_intrpd"), a(d, "c_intrpd"), a(d, "s_intrpd"), a(d, "cs_intrpd"))
        fee = fee + Gstr3bValues(ZERO, a(d, "c_lfeepd"), a(d, "s_lfeepd"), ZERO)
    for d in rows(pmt.get("pditc")):
        itc = itc + Gstr3bValues(a(d, "i_pdi") + a(d, "c_pdi") + a(d, "s_pdi"), a(d, "i_pdc") + a(d, "c_pdc"),
                                 a(d, "i_pds") + a(d, "s_pds"), a(d, "cs_pdcs"))
    for code, v in (("61CASH", cash), ("61ITC", itc), ("61INT", interest), ("61FEE", fee)):
        if v.total:
            table[code] = v
    if any(c in table for c in TABLE61):
        preview.warnings.append("Table 6.1 (payment of tax) read from 'tx_pmt' – check the totals against the "
                                "return as filed")


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
            preview.warnings.append(f"Row {n}: table '{cell('table')}' is not a GSTR-3B table code (3.1, 4 or 6.1) – skipped")
            continue
        p = parse_period(cell("period")) if cell("period") not in (None, "") else period
        if not p:
            raise ValueError(f"Row {n}: period missing – add a Period column or specify the period")
        v = Gstr3bValues(*(_amount(cell(k), f"row {n} {k.upper()}") for k in ("igst", "cgst", "sgst", "cess",
                                                                              "taxable")))
        table = preview.entries.setdefault(p, {})
        if code in table:
            preview.warnings.append(f"Row {n}: {p} table {code} appears more than once – values added")
            v = table[code] + v
        table[code] = v


# ---------------------------------------------------------------- filed GSTR-3B (PDF)
_NUM = r"-?\(?[0-9][0-9,]*\.[0-9]{1,2}\)?"
#: row code -> (label pattern, number of amount columns); searched in this order through the text of the form
_PDF_ROWS = [
    ("31A", r"Outward\s+taxable\s+supplies\s*\(\s*other\s+than\s+zero", 5),
    ("31B", r"Outward\s+taxable\s+supplies\s*\(\s*zero\s+rated", 5),
    ("31C", r"Other\s+outward\s+supplies\s*\(\s*nil", 5),
    ("31D", r"Inward\s+supplies\s*\(\s*liable\s+to\s+reverse\s+charge", 5),
    ("31E", r"Non[-\s]*GST\s+outward\s+supplies", 5),
    ("4A1", r"Import\s+of\s+goods", 4),
    ("4A2", r"Import\s+of\s+services", 4),
    ("4A3", r"Inward\s+supplies\s+liable\s+to\s+reverse\s+charge\s*\(\s*other", 4),
    ("4A4", r"Inward\s+supplies\s+from\s+ISD", 4),
    ("4A5", r"All\s+other\s+ITC", 4),
    ("4B1", r"As\s+per\s+rules?\s*38", 4),
    ("4B2", r"\(\s*2\s*\)\s*Others", 4),
    ("4C", r"Net\s+ITC\s+[Aa]vailable", 4),
    ("4D1", r"ITC\s+reclaimed", 4),
    ("4D2", r"Ineligible\s+ITC\s+under\s+section\s+16", 4),
]
#: text that ends the last row of a table (the next table of the form begins)
_PDF_STOP = r"3\.1\.1|3\.2\b|Details\s+of\s+inter[-\s]*state|4\.?\s*\bEligible\s+ITC|\bEligible\s+ITC|5\.?\s*Values|Values\s+of\s+exempt|Payment\s+of\s+tax"
_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"), 1)}


def _pdf_num(text: str) -> Decimal:
    neg = text.startswith("-") or text.startswith("(")
    v = Decimal(text.strip("-()").replace(",", ""))
    return -v if neg else v


def pdf_period(text: str) -> str | None:
    """Return period of a filed GSTR-3B: 'Year 2024-25' and 'Period June' (or 'Tax period June 2024')."""
    year = re.search(r"Year\s*:?\s*(20\d\d)\s*[-–]\s*(\d{2,4})", text)
    month = re.search(r"Period\s*:?\s*([A-Za-z]{3,9})", text)
    if month and month.group(1).lower() in _MONTHS and year:
        mo = _MONTHS[month.group(1).lower()]
        start = int(year.group(1))
        return f"{start if mo >= 4 else start + 1}-{mo:02d}"
    m = re.search(r"(?:Tax\s+)?Period\s*:?\s*([A-Za-z]+[\s\-]+20\d\d)", text)
    return parse_period(m.group(1)) if m else None


def read_gstr3b_pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        return "\n".join(page.extract_text() or "" for page in reader.pages[:6])
    except (PdfReadError, ValueError, OSError) as exc:
        raise UnsupportedFileError(f"{path.name}: the PDF could not be read ({exc})") from exc


def is_gstr3b_text(text: str) -> bool:
    return bool(re.search(r"GSTR[-\s]*3B", text, re.I)) and bool(re.search(r"Eligible\s+ITC|Outward\s+taxable", text,
                                                                         re.I))


def _from_pdf(path: Path, period: str | None, preview: Gstr3bPreview) -> None:
    text = read_gstr3b_pdf_text(path)
    if not is_gstr3b_text(text):
        raise UnsupportedFileError(f"{path.name} is not a GSTR-3B (the form heading was not found in the PDF)")
    if not text.strip():
        raise UnsupportedFileError(f"{path.name}: the PDF has no text (scanned image) – use the JSON or the template")
    flat = re.sub(r"\s+", " ", text)
    p = pdf_period(flat) or period
    if not p:
        raise ValueError("The period was not found in the GSTR-3B PDF – specify the period (YYYY-MM)")
    found: list[tuple[int, int, str, int]] = []  # start, end of label, code, columns
    pos = 0
    for code, pattern, cols in _PDF_ROWS:
        m = re.compile(pattern, re.I).search(flat, pos)
        if m is None:
            continue
        found.append((m.start(), m.end(), code, cols))
        pos = m.end()
    if not found:
        raise ValueError("No GSTR-3B table rows (3.1 / 4) were found in the PDF")
    stop = re.compile(_PDF_STOP, re.I)
    table: dict[str, Gstr3bValues] = {}
    for i, (_start, end, code, cols) in enumerate(found):
        nxt = found[i + 1][0] if i + 1 < len(found) else len(flat)
        seg = flat[end:nxt]
        s = stop.search(seg)
        if s:
            seg = seg[:s.start()]
        nums = [_pdf_num(n) for n in re.findall(_NUM, seg)][:cols]
        if not nums:
            preview.warnings.append(f"{ALL_TABLES[code][:60]}: no amounts read – taken as nil")
            nums = [ZERO] * cols
        if cols == 5:  # taxable value, IGST, CGST, SGST, cess
            taxable, tax = nums[0], (nums[1:] + [ZERO] * 4)[:4]
            if len(nums) not in (1, 5):
                preview.warnings.append(f"{ALL_TABLES[code][:60]}: {len(nums)} amount(s) read, 5 expected – check")
        else:
            taxable, tax = ZERO, (nums + [ZERO] * 4)[:4]
            if len(nums) != 4:
                preview.warnings.append(f"{ALL_TABLES[code][:60]}: {len(nums)} amount(s) read, 4 expected – check")
        table[code] = Gstr3bValues(*tax, taxable)
    preview.entries[p] = table
    preview.warnings.append("Read from the PDF of the filed return – compare the figures shown with the PDF before "
                            "saving")


def preview_gstr3b(path: str | Path, period: str | None = None) -> Gstr3bPreview:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    period = parse_period(period) if period else None
    suffix = path.suffix.lower()
    if suffix == ".json":
        preview = Gstr3bPreview(path, "GSTR-3B JSON")
        _from_json(read_json(path), period, preview)
    elif suffix == ".pdf":
        preview = Gstr3bPreview(path, "GSTR-3B filed return (PDF)")
        _from_pdf(path, period, preview)
    elif suffix == ".csv":
        preview = Gstr3bPreview(path, "GSTR-3B template (CSV)")
        _from_table(read_csv(path, path.name).rows, period, preview)
    elif suffix in (".xlsx", ".xlsm", ".xls"):
        preview = Gstr3bPreview(path, "GSTR-3B template (Excel)")
        _from_table(read_excel(path)[0].rows, period, preview)
    else:
        raise UnsupportedFileError("GSTR-3B: use the portal JSON or PDF, or the CSV/Excel template")
    if not preview.entries:
        raise ValueError("No GSTR-3B Table 4 values found in the file")
    for p, table in preview.entries.items():
        if not set(table) & set(TABLE4):
            continue  # Table 3.1 only
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
