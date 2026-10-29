"""File import pipeline: detect layout → map columns → validate → preview.

``preview_file`` reads a file and returns an :class:`ImportPreview` without
writing anything. Persisting a preview is done by the import service, which
also checks for repeated imports against the database.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import AMOUNT_FIELDS, LEFT_SOURCES, InvoiceRecord, Source
from ..core.money import ZERO
from .column_mapping import (
    Column, MappingResult, apply_template, auto_map, build_columns, header_score, normalize_header,
)
from .gstn_json import detect_json_kind, flatten_gstr1, flatten_gstr2a, flatten_gstr2b, flatten_gstr8a, flatten_ims
from .parsing import parse_period
from .readers import SUPPORTED_EXTENSIONS, RawTable, UnsupportedFileError, read_csv, read_excel, read_json, zip_members
from .validation import RowContext, build_record

LAYOUT_LABELS = {
    "gstr2b_excel": "GSTR-2B (GST portal Excel)",
    "gstr2b_json": "GSTR-2B (GST portal JSON)",
    "gstr2a_excel": "GSTR-2A (GST portal Excel)",
    "gstr2a_json": "GSTR-2A (GST portal JSON)",
    "ims_json": "IMS download (GST portal JSON)",
    "gstr1_json": "GSTR-1 (GST portal JSON)",
    "gstr8a_excel": "GSTR-9 Table 8A document details (GST portal Excel)",
    "gstr8a_json": "GSTR-9 Table 8A document details (GST portal JSON)",
    "tally": "TallyPrime purchase register",
    "generic": "Custom purchase register",
}
GSTN_INVOICE_SHEETS = {"b2b": False, "b2ba": True}
GSTN_NOTE_SHEETS = {"b2b-cdnr": False, "b2b-cdnra": True, "cdnr": False, "cdnra": True}
GSTN_SUMMARY_SHEETS = {"read me", "readme", "itc available", "itc not available", "itc reversal", "itc rejected",
                       "summary"}
_TOTAL_ROW = re.compile(r"^\s*(grand\s+)?total\b", re.IGNORECASE)


class MappingRequired(ValueError):
    """Raised when required columns cannot be identified automatically."""

    def __init__(self, sheet: str, mapping: MappingResult, columns: list[Column]):
        self.sheet, self.mapping, self.columns = sheet, mapping, columns
        missing = ", ".join(mapping.missing_required)
        super().__init__(f"Sheet '{sheet}': could not identify column(s) for {missing}. "
                         f"Available columns: {', '.join(c.label for c in columns)}")


@dataclass
class RowIssue:
    sheet: str
    row: str
    severity: str  # error | warning | duplicate | ignored | info | existing
    message: str
    raw: dict = field(default_factory=dict)


@dataclass
class ImportPreview:
    file_path: Path
    file_name: str
    sha256: str
    source: Source
    layout: str
    period: str | None
    records: list[InvoiceRecord] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)
    mappings: dict[str, MappingResult] = field(default_factory=dict)
    file_warnings: list[str] = field(default_factory=list)
    columns: dict[str, list[str]] = field(default_factory=dict)  # sheet -> column labels (for re-mapping)
    other_itc: list[dict] = field(default_factory=list)  # GSTR-2B ISD credits and imports (bills of entry)
    outward_summary: list[dict] = field(default_factory=list)  # GSTR-1 section totals
    total_rows: int = 0
    existing_record_hashes: set[str] = field(default_factory=set)
    already_imported_file_id: int | None = None

    @property
    def layout_label(self) -> str:
        return LAYOUT_LABELS.get(self.layout, self.layout)

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)

    @property
    def rejected_rows(self) -> int:
        return self.count("error")

    @property
    def new_records(self) -> list[InvoiceRecord]:
        return [r for r in self.records if r.identity_hash() not in self.existing_record_hashes]

    @property
    def duplicate_rows(self) -> int:
        return self.count("duplicate")

    def summary(self) -> dict:
        return {
            "file": self.file_name, "layout": self.layout_label, "source": self.source.value,
            "period": self.period, "rows_read": self.total_rows, "valid_documents": len(self.records),
            "new_documents": len(self.new_records),
            "already_imported_documents": len(self.records) - len(self.new_records),
            "rejected_rows": self.rejected_rows, "duplicate_rows_in_file": self.duplicate_rows,
            "ignored_rows": self.count("ignored"), "rows_with_warnings": self.count("warning"),
            "taxable_total": sum((r.signed("taxable") for r in self.records), ZERO),
            "itc_total": sum((r.signed("itc") for r in self.records), ZERO),
            "isd_import_records": len(self.other_itc),
        }


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _template_score(cols: list[Column], template: dict) -> int:
    wanted = {normalize_header(label) for labels in template.get("fields", {}).values()
              for label in ([labels] if isinstance(labels, str) else labels)}
    return sum(1 for c in cols if wanted & ({normalize_header(c.label)} | set(c.candidates)))


def locate_header(table: RawTable, max_scan: int = 40, template: dict | None = None) -> tuple[int, list[Column]] | None:
    best = None
    rows = table.rows[:max_scan]
    for i, (_n, values) in enumerate(rows):
        if not values:
            continue
        options = [(build_columns(None, values), 1)]
        if i > 0:
            options.append((build_columns(rows[i - 1][1], values), 0))
        for cols, prefer_single in options:
            score = _template_score(cols, template) if template else header_score(cols)
            key = (score, prefer_single)
            if best is None or key > best[0]:
                best = (key, i, cols)
    if best is None or best[0][0] < 3:
        return None
    return best[1], best[2]


def detect_excel_period(tables: list[RawTable]) -> str | None:
    """Find 'Tax period' / 'Financial year' labels in the title area of portal exports."""
    month = year = None
    for t in tables:
        for _n, values in t.rows[:12]:
            cells = [str(v).strip() for v in values if v not in (None, "")]
            for j, cell in enumerate(cells):
                low = cell.lower()
                nxt = cells[j + 1] if j + 1 < len(cells) else ""
                if "tax period" in low or "return period" in low:
                    candidate = nxt or cell.split(":")[-1]
                    p = parse_period(candidate)
                    if p:
                        return p
                    month = candidate.strip()
                if "financial year" in low:
                    m = re.search(r"(\d{4})\s*-\s*(\d{2,4})", nxt or cell)
                    if m:
                        year = int(m.group(1))
    if month and year:
        p = parse_period(f"{month} {year}")
        if p:
            mo = int(p[5:])
            return f"{year + (1 if mo <= 3 else 0)}-{mo:02d}"
    return None


def _row_values(values: list, mapping: MappingResult) -> dict:
    row = {}
    for fname, idxs in mapping.indices.items():
        vals = [values[i] if i < len(values) else None for i in idxs]
        row[fname] = vals[0] if len(vals) == 1 else vals
    return row


def _raw_dict(values: list, columns: list[Column]) -> dict:
    return {c.label: (str(values[c.index]) if c.index < len(values) and values[c.index] is not None else "")
            for c in columns}


class _Builder:
    def __init__(self, preview: ImportPreview, layout_kind: str):
        self.p = preview
        self.ctx = RowContext(preview.source, layout_kind, preview.file_name, preview.period)

    def add(self, sheet: str, row_ref: str, row: dict, raw: dict) -> None:
        self.p.total_rows += 1
        row.setdefault("_row", f"{sheet}!{row_ref}" if sheet else row_ref)
        outcome = build_record(row, self.ctx, uid=f"{self.p.file_name}:{row['_row']}")
        if outcome.record is None:
            self.p.issues.append(RowIssue(sheet, row_ref, "error", "; ".join(outcome.errors), raw))
            return
        if outcome.warnings:
            self.p.issues.append(RowIssue(sheet, row_ref, "warning", "; ".join(outcome.warnings), raw))
        self.p.records.append(outcome.record)


def _process_table(builder: _Builder, table: RawTable, template: dict | None, extra: dict) -> None:
    located = locate_header(table, template=template)
    if located is None:
        if any(v for _n, v in table.rows):
            builder.p.file_warnings.append(f"Sheet '{table.name}': no recognisable header row – sheet not imported")
        return
    header_idx, columns = located
    mapping = apply_template(columns, template) if template else auto_map(columns)
    if (builder.p.source == Source.SALES and "invoice_date" not in mapping.indices
            and "voucher_date" in mapping.indices):  # in a sales register the voucher is the invoice
        mapping.indices["invoice_date"] = mapping.indices["voucher_date"]
        mapping.fields["invoice_date"] = mapping.fields["voucher_date"]
        mapping.missing_required = [f for f in mapping.missing_required if f != "invoice_date"]
        mapping.notes.append("Invoice date taken from the voucher date column (sales register)")
    if not mapping.complete:
        raise MappingRequired(table.name, mapping, columns)
    builder.p.mappings[table.name] = mapping
    builder.p.columns[table.name] = [c.label for c in columns]
    for n, values in table.rows[header_idx + 1:]:
        if not any(v not in (None, "") for v in values):
            continue
        first_text = next((str(v) for v in values if v not in (None, "")), "")
        row = _row_values(values, mapping)
        if _TOTAL_ROW.match(first_text) and not row.get("supplier_gstin"):
            builder.p.issues.append(RowIssue(table.name, str(n), "ignored", f"Total row ignored: '{first_text}'",
                                             _raw_dict(values, columns)))
            continue
        row.update(extra)
        builder.add(table.name, str(n), row, _raw_dict(values, columns))


def _aggregate_and_flag(preview: ImportPreview) -> None:
    """Merge tax-rate lines of one document; flag genuine repeats as duplicates."""
    groups: dict[tuple, list[InvoiceRecord]] = defaultdict(list)
    for r in preview.records:
        groups[(r.supplier_gstin, r.doc_type, r.invoice_no_norm, r.invoice_date, r.is_amendment)].append(r)
    merged: list[InvoiceRecord] = []
    for members in groups.values():
        if len(members) == 1:
            merged.append(members[0])
            continue
        rates = [m.rate for m in members]
        if all(rt is not None for rt in rates) and len(set(rates)) == len(rates):
            head = members[0]
            for m in members[1:]:
                for f in AMOUNT_FIELDS:
                    setattr(head, f, getattr(head, f) + getattr(m, f))
            head.source_rows = ",".join(m.source_rows for m in members)
            head.rate = None
            preview.issues.append(RowIssue("", head.source_rows, "info",
                                           f"{len(members)} tax-rate lines combined into one document "
                                           f"'{head.invoice_no}'"))
            merged.append(head)
        else:
            refs = ", ".join(m.source_rows for m in members)
            for m in members[1:]:
                preview.issues.append(RowIssue("", m.source_rows, "duplicate",
                                               f"Document '{m.invoice_no}' repeated in file ({refs}); imported and "
                                               "will be reported as a duplicate during reconciliation"))
            merged.extend(members)
    order = {id(r): i for i, r in enumerate(preview.records)}
    preview.records = sorted(merged, key=lambda r: order[id(r)])


def _layout_for_tables(tables: list[RawTable]) -> str:
    names = {t.name.strip().lower() for t in tables}
    for t in tables:
        for _n, values in t.rows[:8]:
            text = " ".join(str(v) for v in values if v).lower()
            if "table 8a" in text or "gstr-9" in text or "gstr 9" in text:
                return "gstr8a_excel"
    if names & {"b2b-cdnr", "b2b-cdnra"} or ("b2b" in names and "read me" in names and "itc available" in names):
        return "gstr2b_excel"
    if "b2b" in names and names & {"cdnr", "b2ba", "cdnra"}:
        return "gstr2a_excel"
    for t in tables:
        for _n, values in t.rows[:12]:
            text = " ".join(str(v) for v in values if v).lower()
            if "gstr-2b" in text or "gstr 2b" in text:
                return "gstr2b_excel"
            if "gstr-2a" in text:
                return "gstr2a_excel"
    for t in tables:
        located = locate_header(t)
        if located:
            labels = {c.candidates[-1] for c in located[1]}
            if "voucher type" in labels or "vch type" in labels or "voucher no" in labels:
                return "tally"
    return "generic"


def _expected_source(layout: str) -> Source | None:
    if layout.startswith("gstr2b"):
        return Source.GSTR2B
    if layout.startswith("gstr2a"):
        return Source.GSTR2A
    if layout.startswith("ims"):
        return Source.IMS
    if layout.startswith("gstr1"):
        return Source.GSTR1
    if layout.startswith("gstr8a"):
        return Source.GSTR8A
    return Source.BOOKS


def preview_file(path: str | Path, source: Source | str, period: str | None = None,
                 template: dict | None = None, sheet: str | None = None) -> ImportPreview:
    path = Path(path)
    source = Source(source)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"Unsupported file type '{suffix}'. Use Excel (.xlsx), CSV, JSON or ZIP.")
    norm_period = parse_period(period) if period else None
    if period and not norm_period:
        raise ValueError(f"Invalid period '{period}' (use YYYY-MM)")
    preview = ImportPreview(path, path.name, sha256_of(path), source, "generic", norm_period)

    members: list[tuple[str, bytes | Path]]
    members = zip_members(path) if suffix == ".zip" else [(path.name, path)]

    for name, data in members:
        msuffix = Path(name).suffix.lower()
        if msuffix == ".json":
            js = read_json(data)
            kind = detect_json_kind(js, source.value)
            if kind is None:
                raise UnsupportedFileError(f"{name}: JSON is not a recognised GSTR-2B/GSTR-2A/IMS layout")
            if kind == "GSTR2B":
                rows, json_period, warnings, other = flatten_gstr2b(js)
                preview.other_itc.extend(other)
            elif kind == "IMS":
                rows, json_period, warnings = flatten_ims(js)
            elif kind == "GSTR1":
                rows, json_period, warnings, preview.outward_summary = flatten_gstr1(js)
            elif kind == "GSTR8A":
                rows, json_period, warnings = flatten_gstr8a(js)
            elif kind == "GSTR3B":
                raise UnsupportedFileError(f"{name} is a GSTR-3B return – import it with the GSTR-3B import")
            else:
                rows, json_period, warnings = flatten_gstr2a(js)
            preview.layout = {"GSTR2B": "gstr2b_json", "IMS": "ims_json", "GSTR1": "gstr1_json",
                              "GSTR8A": "gstr8a_json"}.get(kind, "gstr2a_json")
            _check_source(preview)
            preview.period = preview.period or json_period
            preview.file_warnings += warnings
            _require_period(preview)
            builder = _Builder(preview, "gstn")
            if preview.outward_summary:
                preview.issues.append(RowIssue("", "", "info", f"{len(preview.outward_summary)} GSTR-1 section "
                                               "total(s) read for the GSTR-1 vs GSTR-3B comparison"))
            if preview.other_itc:
                preview.issues.append(RowIssue("", "", "info", f"{len(preview.other_itc)} ISD / import (bill of "
                                               "entry) record(s) read for the GSTR-3B Table 4 working"))
            for row in rows:
                if row.get("doc_type") is None and row["_sheet"] in ("cdnr", "cdnra", "cdn", "cdna"):
                    row["_note_sheet"] = True
                builder.add("", row["_row"], row, {k: str(v) for k, v in row.items() if not k.startswith("_")})
            continue

        tables = [read_csv(data, name)] if msuffix == ".csv" else read_excel(data)
        if sheet:
            tables = [t for t in tables if t.name == sheet]
            if not tables:
                raise ValueError(f"Sheet '{sheet}' not found")
        preview.layout = _layout_for_tables(tables)
        if preview.source == Source.GSTR8A and preview.layout in ("gstr2b_excel", "gstr2a_excel"):
            preview.layout = "gstr8a_excel"  # the Table 8A download uses the same B2B / CDNR sheets
        _check_source(preview)
        if preview.layout in ("gstr2b_excel", "gstr2a_excel", "gstr8a_excel"):
            preview.period = preview.period or detect_excel_period(tables)
            _require_period(preview)
            builder = _Builder(preview, "gstn")
            for t in tables:
                key = t.name.strip().lower()
                if key in GSTN_INVOICE_SHEETS:
                    _process_table(builder, t, template, {"_amendment": GSTN_INVOICE_SHEETS[key], "doc_type": "INV"})
                elif key in GSTN_NOTE_SHEETS:
                    _process_table(builder, t, template, {"_amendment": GSTN_NOTE_SHEETS[key], "_note_sheet": True})
                elif key in GSTN_SUMMARY_SHEETS:
                    continue
                elif _has_data_rows(t):
                    preview.file_warnings.append(f"Sheet '{t.name}' is not reconciled in this version (not imported)")
        else:
            if preview.source not in LEFT_SOURCES:
                _require_period(preview)
            builder = _Builder(preview, preview.layout)
            imported_any = False
            unrecognised = []
            for t in tables:
                if locate_header(t, template=template) is None:
                    if any(v for _n, v in t.rows):
                        unrecognised.append(t)
                    continue
                _process_table(builder, t, template, {})
                imported_any = True
            if not imported_any and unrecognised:
                # Offer the first non-empty row as the heading row for manual mapping.
                t = unrecognised[0]
                first = next(v for _n, v in t.rows if v)
                cols = build_columns(None, first)
                raise MappingRequired(t.name, auto_map(cols), cols)
            for t in unrecognised:
                if _has_data_rows(t):
                    preview.file_warnings.append(f"Sheet '{t.name}': no recognisable header row – not imported")
            if not imported_any:
                raise UnsupportedFileError(f"{name}: no sheet with recognisable purchase-register headings")
    _aggregate_and_flag(preview)
    return preview


def _has_data_rows(t: RawTable) -> bool:
    return sum(1 for _n, v in t.rows if any(x not in (None, "") for x in v)) > 2


def _check_source(preview: ImportPreview) -> None:
    expected = _expected_source(preview.layout)
    own_books = preview.source in LEFT_SOURCES
    if own_books and expected != Source.BOOKS:
        raise UnsupportedFileError(f"{preview.file_name} looks like a {LAYOUT_LABELS[preview.layout]} file, "
                                   "not a purchase/sales register")
    if not own_books and expected == Source.BOOKS and preview.layout == "tally":
        raise UnsupportedFileError(f"{preview.file_name} looks like a TallyPrime register, not GSTR data")
    if not own_books and expected not in (Source.BOOKS, preview.source):
        raise UnsupportedFileError(f"{preview.file_name} is a {LAYOUT_LABELS[preview.layout]} file but was "
                                   f"imported as {preview.source.value}")


def _require_period(preview: ImportPreview) -> None:
    if preview.source == Source.GSTR8A:
        return  # annual statement: each document's month comes from its date
    if not preview.period:
        raise ValueError(f"{preview.file_name}: return period could not be detected – specify it (YYYY-MM)")
