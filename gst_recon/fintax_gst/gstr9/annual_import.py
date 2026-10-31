"""Read a GSTR-9 or GSTR-9C as prepared elsewhere (GST offline tool, portal download, or a firm's template), so it
can be compared with this program's working.

* **GSTR-9 JSON** (portal download / offline tool): Tables 4–8 and 10–13 by their JSON keys.
* **GSTR-9 / GSTR-9C Excel or CSV**: any sheet whose rows carry a table code – either written out ("4A",
  "Pt. II 5A", "12 E") or as the row letter "(A)" under a table heading ("4. Details of advances…") or in a
  sheet named after the table ("4 Outward", "Pt. II 5,6"). Amount columns are found by their headings
  (taxable value, central tax, state tax, integrated tax, cess, amount); a sheet without such headings gives the
  first amount of the row.

Rows that cannot be read are listed, never dropped silently. Nothing read here changes the client's data
unless the user chooses to use the GSTR-9C figures as the audited amounts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..core.money import ZERO, parse_amount
from ..importers.column_mapping import normalize_header
from ..importers.gstr3b import Gstr3bValues as V
from ..importers.readers import RawTable, UnsupportedFileError, read_csv, read_excel, read_json

#: GSTR-9 JSON key -> table code
JSON_KEYS = {
    "table4": {"b2c": "4A", "b2b": "4B", "exp": "4C", "sez": "4D", "deemed": "4E", "at": "4F", "rchrg": "4G",
               "sub_totalAG": "4H", "cr_nt": "4I", "dr_nt": "4J", "amd_pos": "4K", "amd_neg": "4L",
               "sub_totalIL": "4M", "sup_adv": "4N"},
    "table5": {"zero_rtd": "5A", "sez": "5B", "rchrg": "5C", "exmt": "5D", "nil": "5E", "non_gst": "5F",
               "sub_totalAF": "5G", "cr_nt": "5H", "dr_nt": "5I", "amd_pos": "5J", "amd_neg": "5K",
               "sub_totalHK": "5L", "tover_tax_np": "5M", "total_tover": "5N"},
    "table6": {"itc_3b": "6A", "supp_non_rchrg": "6B", "supp_rchrg_unreg": "6C", "supp_rchrg_reg": "6D",
               "iog": "6E", "ios": "6F", "isd": "6G", "itc_clmd": "6H", "sub_totalBH": "6I", "dif6": "6J",
               "tran1": "6K", "tran2": "6L", "other": "6M", "sub_totalKM": "6N", "total_itc_availed": "6O"},
    "table7": {"rule37": "7A", "rule39": "7B", "rule42": "7C", "rule43": "7D", "sec17": "7E", "revsl_tran1": "7F",
               "revsl_tran2": "7G", "other": "7H", "tot_itc_revd": "7I", "net_itc_aval": "7J"},
    "table8": {"itc_2a": "8A", "itc_tot": "8B", "itc_inwd_supp": "8C", "dif_ABC": "8D", "itc_nt_availd": "8E",
               "itc_nt_eleg": "8F", "iog_taxpaid": "8G", "iog_itc_availd": "8H", "iog_itc_ntavaild": "8I",
               "differenceABC": "8J", "tot_itc_lapsed": "8K"},
    "table10": {"dbn_amd": "10", "cdn_amd": "11", "itc_rvsl": "12", "itc_availd": "13", "total_turnover": "14"},
}
_HEADS = {"taxable": ("taxable value", "taxable", "value", "turnover"), "cgst": ("central tax", "cgst"),
          "sgst": ("state tax", "state tax ut tax", "state ut tax", "sgst", "utgst", "sgst utgst"),
          "igst": ("integrated tax", "igst"), "cess": ("cess",), "amount": ("amount", "amount in rs", "value rs")}
_CODE = re.compile(r"(?:pt\.?\s*[ivx]+\s*)?\b(\d{1,2})\s*\(?\s*([A-Z])\b\)?", re.IGNORECASE)
_LETTER = re.compile(r"^\s*\(?([A-Z])[\).]\s|^\s*\(?([A-Z])\)?\s*$")
_HEADING = re.compile(r"^\s*(?:pt\.?\s*[ivx]+\s*[-–:]?\s*)?(\d{1,2})[\.\s]")


@dataclass
class AnnualFile:
    kind: str  # GSTR9 / GSTR9C
    values: dict[str, V] = field(default_factory=dict)  # GSTR-9: table code -> values
    amounts: dict[str, Decimal] = field(default_factory=dict)  # GSTR-9C: table code -> amount
    gstin: str = ""
    fy: str = ""
    skipped: list[str] = field(default_factory=list)


def _v(d) -> V:
    """Values of a JSON entry: a dict with txval/iamt/camt/samt/csamt, or a list of them (added up)."""
    if isinstance(d, list):
        total = V()
        for x in d:
            x = _v(x)
            total = V(total.igst + x.igst, total.cgst + x.cgst, total.sgst + x.sgst, total.cess + x.cess,
                      total.taxable + x.taxable)
        return total
    if not isinstance(d, dict):
        return V()

    def a(*keys):
        for k in keys:
            if d.get(k) not in (None, ""):
                return parse_amount(d.get(k)) or ZERO
        return ZERO

    return V(a("iamt"), a("camt"), a("samt"), a("csamt"), a("txval"))


def _fy_of(fp: str) -> str:
    m = re.fullmatch(r"(\d{2})(\d{4})", fp or "")
    if not m:
        return ""
    y, mo = int(m.group(2)), int(m.group(1))
    start = y - 1 if mo <= 3 else y
    return f"{start}-{str(start + 1)[2:]}"


def read_gstr9_json(js: dict) -> AnnualFile:
    data = js.get("data", js) if isinstance(js, dict) else {}
    out = AnnualFile("GSTR9", gstin=str(data.get("gstin") or ""), fy=_fy_of(str(data.get("fp") or "")))
    found = False
    for table, keys in JSON_KEYS.items():
        sec = data.get(table)
        if not isinstance(sec, dict):
            continue
        found = True
        for key, val in sec.items():
            code = keys.get(key)
            if code is None:
                if isinstance(val, (dict, list)):
                    out.skipped.append(f"{table}.{key}: not compared")
                continue
            out.values[code] = _v(val)
    if not found:
        raise UnsupportedFileError("Not a GSTR-9 JSON: no table4 … table10 found")
    return out


def _columns(names: list[str]) -> dict[str, int]:
    found = {}
    for head, opts in _HEADS.items():
        for i, n in enumerate(names):
            if n in opts or any(n.startswith(o + " ") for o in opts):
                found.setdefault(head, i)
    return found


def _table_no(sheet: str) -> str | None:
    m = re.match(r"\s*(?:pt\.?\s*[ivx]+\s*)?(\d{1,2})\b", sheet, re.IGNORECASE)
    return m.group(1) if m else None


def read_coded_rows(tables: list[RawTable]) -> tuple[dict[str, dict[str, Decimal]], list[str]]:
    """code -> {taxable/igst/cgst/sgst/cess/amount: value} from template sheets, and rows not read."""
    out: dict[str, dict[str, Decimal]] = {}
    skipped: list[str] = []
    for t in tables:
        table_no = _table_no(t.name)
        cols: dict[str, int] = {}
        for n, vals in t.rows:
            names = [normalize_header(v) for v in vals]
            got = _columns(names)
            if len(got) >= 2 or ("amount" in got and not any(parse_amount_safe(v) for v in vals)):
                cols = got
                continue
            texts = [str(v).strip() for v in vals[:3] if isinstance(v, str) and v.strip()]
            if texts and (h := _HEADING.match(texts[0])) and not _CODE.match(texts[0].strip()):
                table_no = h.group(1)
            code = None
            for txt in texts[:2]:
                m = _CODE.match(txt)
                if m and (len(txt) <= 12 or txt[m.end():m.end() + 1] in (" ", ")", ".", "")):
                    code = f"{int(m.group(1))}{m.group(2).upper()}"
                    break
                lm = _LETTER.match(txt)
                if lm and table_no:
                    code = f"{int(table_no)}{(lm.group(1) or lm.group(2)).upper()}"
                    break
            if code is None:
                continue
            nums = [(i, x) for i, x in ((i, parse_amount_safe(v)) for i, v in enumerate(vals))
                    if x is not None and (not isinstance(vals[i], str) or re.fullmatch(r"[\s\d,.\-()₹]+", vals[i]))]
            if not nums:
                continue
            row: dict[str, Decimal] = {}
            if cols:
                for head, i in cols.items():
                    v = parse_amount_safe(vals[i]) if i < len(vals) else None
                    if v is not None:
                        row[head] = v
            if not row:
                row["amount"] = nums[0][1]
            if code in out:
                skipped.append(f"{t.name}!{n}: {code} appears again – the first one is used")
                continue
            out[code] = row
    return out, skipped


def parse_amount_safe(v) -> Decimal | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return parse_amount(v)
    except (ValueError, ArithmeticError):
        return None


def read_annual(path: str | Path, kind: str) -> AnnualFile:
    """GSTR-9 (kind 'GSTR9') or GSTR-9C (kind 'GSTR9C') from JSON / Excel / CSV."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        if kind != "GSTR9":
            raise UnsupportedFileError("GSTR-9C: use the offline tool's Excel template (or CSV)")
        return read_gstr9_json(read_json(path))
    if suffix == ".csv":
        tables = [read_csv(path, path.name)]
    elif suffix in (".xlsx", ".xlsm", ".xls"):
        tables = read_excel(path)
    else:
        raise UnsupportedFileError(f"{path.name}: use a JSON, Excel or CSV file")
    rows, skipped = read_coded_rows(tables)
    out = AnnualFile(kind, skipped=skipped)
    if kind == "GSTR9":
        for code, r in rows.items():
            if int(re.match(r"\d+", code).group()) in (4, 5, 6, 7, 8, 10, 11, 12, 13):
                out.values[code] = V(r.get("igst", ZERO), r.get("cgst", ZERO), r.get("sgst", ZERO),
                                     r.get("cess", ZERO), r.get("taxable", r.get("amount", ZERO)))
    else:
        for code, r in rows.items():
            if int(re.match(r"\d+", code).group()) in (5, 7, 12, 14):
                out.amounts[code] = r.get("amount", r.get("taxable", sum(
                    (r.get(h, ZERO) for h in ("igst", "cgst", "sgst", "cess")), ZERO)))
    if not out.values and not out.amounts:
        raise UnsupportedFileError(f"{path.name}: no {'GSTR-9' if kind == 'GSTR9' else 'GSTR-9C'} table rows found "
                                   "(rows need a table code such as 4A, 6B or 5A and an amount)")
    return out
