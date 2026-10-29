"""Intelligent column mapping from source headings to canonical fields.

A mapping is ``{field: [column label, ...]}``. Amount fields may map to several
columns that are summed (TallyPrime exports one column per tax ledger such as
"Input CGST 9%" and "Input CGST 6%"). Every automatic decision is reported in
``MappingResult.notes`` so the user can verify it in the import preview, and a
mapping can be overridden manually and saved as a template.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

AMOUNT_FIELDS = ("invoice_value", "taxable_value", "igst", "cgst", "sgst", "cess")

# Synonyms are written in normalised form (see normalize_header) and listed
# in priority order: earlier entries win when several columns qualify.
SYNONYMS: dict[str, list[str]] = {
    "supplier_gstin": [
        "gstin of supplier", "supplier gstin", "gstin of the supplier", "gstin uin of supplier", "party gstin",
        "vendor gstin", "supplier gstin uin", "gstin uin", "gstin", "gst number", "gst no", "gstin no",
        "supplier gst no", "ctin", "revised details gstin of supplier",
    ],
    "supplier_name": [
        "trade legal name", "trade legal name of the supplier", "supplier name", "name of supplier", "party name",
        "vendor name", "legal name", "trade name", "particulars", "party", "ledger name", "supplier", "trdnm",
    ],
    "original_invoice_no": [
        "original details invoice number", "original invoice number", "original invoice no",
        "original details note number", "original note number", "original note no",
        "original document number", "oinum", "ontnum",
    ],
    "original_invoice_date": [
        "original details invoice date", "original invoice date", "original details note date",
        "original note date", "original document date", "oidt", "ontdt",
    ],
    "invoice_no": [
        "supplier invoice no", "supplier invoice number", "supplier inv no", "party invoice no", "vendor invoice no",
        "voucher ref no", "invoice number", "invoice no", "inv no", "bill no", "bill number", "note number",
        "note no", "credit debit note no", "document number", "document no", "doc no", "reference no", "ref no",
        "inum", "ntnum", "voucher no", "voucher number", "vch no",
    ],
    "invoice_date": [
        "supplier invoice date", "supplier inv date", "party invoice date", "voucher ref date", "invoice date",
        "inv date", "bill date", "note date", "credit debit note date", "document date", "doc date",
        "reference date", "ref date", "idt", "dt",
    ],
    "voucher_date": ["date", "voucher date", "posting date", "entry date", "booking date", "accounting date"],
    "voucher_type": ["voucher type", "vch type", "voucher type name"],
    "doc_type": ["document type", "doc type", "type of document", "note type", "document category", "ntty"],
    "supply_type": ["invoice type", "note supply type", "supply type", "inv typ"],
    "invoice_value": [
        "invoice value", "total invoice value", "note value", "gross total", "bill amount", "invoice amount",
        "total amount", "document value", "val", "value",
    ],
    "taxable_value": [
        "taxable value", "taxable amount", "taxable", "assessable value", "taxable value of supply", "txval",
        "net amount", "purchase value", "amount before tax",
    ],
    "igst": ["integrated tax", "igst", "igst amount", "integrated tax amount", "iamt", "input igst"],
    "cgst": ["central tax", "cgst", "cgst amount", "central tax amount", "camt", "input cgst"],
    "sgst": [
        "state ut tax", "state tax", "sgst", "sgst utgst", "utgst", "sgst amount", "state ut tax amount", "samt",
        "input sgst",
    ],
    "cess": ["cess", "cess amount", "compensation cess", "csamt", "input cess"],
    "rate": ["rate", "tax rate", "gst rate", "rate pct", "rt", "gst rate pct"],
    "place_of_supply": ["place of supply", "pos", "place of supply name"],
    "reverse_charge": ["supply attract reverse charge", "reverse charge", "rcm", "rev", "rchrg", "reverse charge applicable"],
    "supplier_period": [
        "gstr 1 iff gstr 5 period", "gstr 1 iff gstr 1a 5 period", "gstr 1 iff gstr 1a gstr 5 period",
        "gstr1 period", "supplier filing period", "supprd",
    ],
    "itc_availability": ["itc availability", "itc available", "itcavl", "eligibility for itc"],
    "itc_reason": ["reason", "rsn", "itc unavailability reason"],
}

#: Pattern used to sum ledger-wise tax columns (TallyPrime) when no exact column exists.
LEDGER_PATTERNS = {
    "igst": re.compile(r"\b(igst|integrated tax)\b"),
    "cgst": re.compile(r"\b(cgst|central tax)\b"),
    "sgst": re.compile(r"\b(sgst|utgst|state tax|state ut tax)\b"),
    "cess": re.compile(r"\bcess\b"),
    "taxable_value": re.compile(r"^(purchase|purchases)\b"),
}

REQUIRED_FIELDS = ("supplier_gstin", "invoice_no", "invoice_date")

FIELD_LABELS = {
    "supplier_gstin": "Supplier GSTIN", "supplier_name": "Supplier name", "invoice_no": "Invoice number",
    "invoice_date": "Invoice date", "voucher_date": "Voucher / booking date", "voucher_type": "Voucher type",
    "doc_type": "Document type", "supply_type": "Supply type", "invoice_value": "Invoice value",
    "taxable_value": "Taxable value", "igst": "IGST", "cgst": "CGST", "sgst": "SGST/UTGST", "cess": "Cess",
    "rate": "Tax rate", "place_of_supply": "Place of supply", "reverse_charge": "Reverse charge",
    "supplier_period": "Supplier filing period", "itc_availability": "ITC availability",
    "itc_reason": "ITC reason", "original_invoice_no": "Original invoice number",
    "original_invoice_date": "Original invoice date",
}


def normalize_header(value) -> str:
    text = str(value or "").lower()
    text = text.replace("₹", " ").replace("%", " pct ")
    text = re.sub(r"\((rs|inr)\.?\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(rs|inr)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Column:
    index: int
    label: str  # display label, e.g. "Invoice details / Invoice number"
    candidates: list[str]  # normalised labels to try, most specific first


@dataclass
class MappingResult:
    fields: dict[str, list[str]] = field(default_factory=dict)  # field -> column labels
    indices: dict[str, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    confidence: dict[str, int] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.missing_required and bool(self.indices.get("taxable_value") or self.indices.get("invoice_value"))

    def to_template(self) -> dict:
        return {"fields": self.fields}


def build_columns(parent_row: list | None, child_row: list) -> list[Column]:
    """Combine a group-header row with its sub-header row.

    Group headers (merged cells) carry text only in their first column; the
    label is carried to the right while the sub-header row has text there.
    """
    columns = []
    carried = ""
    width = max(len(child_row), len(parent_row or []))
    for i in range(width):
        child = child_row[i] if i < len(child_row) else None
        child_text = str(child).strip() if child not in (None, "") and str(child) != "nan" else ""
        parent_text = ""
        if parent_row is not None and i < len(parent_row):
            p = parent_row[i]
            parent_text = str(p).strip() if p not in (None, "") and str(p) != "nan" else ""
        if parent_text:
            carried = parent_text if child_text else ""
        elif child_text and carried:
            parent_text = carried
        else:
            carried = ""
        if child_text and parent_text:
            label = f"{parent_text} / {child_text}"
            cands = [normalize_header(f"{parent_text} {child_text}"), normalize_header(child_text)]
        elif child_text or parent_text:
            label = child_text or parent_text
            cands = [normalize_header(label)]
        else:
            continue
        columns.append(Column(i, label, [c for c in cands if c]))
    return columns


def score_columns(columns: list[Column], fuzzy: bool = True) -> list[tuple[int, int, str, Column]]:
    """All plausible (score, priority, field, column) assignments."""
    scored = []
    for col in columns:
        for depth, cand in enumerate(col.candidates):
            for fname, syns in SYNONYMS.items():
                for prio, syn in enumerate(syns):
                    if cand == syn:
                        scored.append((100 - depth * 2, prio, fname, col))
                    elif fuzzy and len(cand) > 4 and len(syn) > 4 and fuzz.ratio(cand, syn) >= 92:
                        scored.append((88 - depth * 2, prio, fname, col))
    return scored


def auto_map(columns: list[Column]) -> MappingResult:
    result = MappingResult()
    used_cols: set[int] = set()
    scored = score_columns(columns)
    scored.sort(key=lambda t: (-t[0], t[1], t[3].index))
    for score, _prio, fname, col in scored:
        if fname in result.indices or col.index in used_cols:
            continue
        result.indices[fname] = [col.index]
        result.fields[fname] = [col.label]
        result.confidence[fname] = score
        used_cols.add(col.index)
        if score < 100:
            result.notes.append(f"'{col.label}' mapped to {FIELD_LABELS[fname]} by approximate heading match")
    # Ledger-wise columns (e.g. TallyPrime "Input CGST 9%") are summed when no exact column exists.
    for fname, pattern in LEDGER_PATTERNS.items():
        if fname in result.indices:
            continue
        hits = [c for c in columns if c.index not in used_cols and any(pattern.search(x) for x in c.candidates)
                and "rate" not in c.candidates[-1].split()]
        if hits:
            result.indices[fname] = [c.index for c in hits]
            result.fields[fname] = [c.label for c in hits]
            result.confidence[fname] = 80
            used_cols.update(c.index for c in hits)
            result.notes.append(f"{FIELD_LABELS[fname]} = sum of columns: " + ", ".join(f"'{c.label}'" for c in hits))
    result.missing_required = [f for f in REQUIRED_FIELDS if f not in result.indices]
    if "taxable_value" not in result.indices and "invoice_value" not in result.indices:
        result.missing_required.append("taxable_value")
    return result


def apply_template(columns: list[Column], template: dict) -> MappingResult:
    """Resolve a saved or user-provided mapping ``{"fields": {field: [labels]}}``."""
    by_label: dict[str, Column] = {}
    for c in columns:
        by_label.setdefault(normalize_header(c.label), c)
        for cand in c.candidates:
            by_label.setdefault(cand, c)
    result = MappingResult()
    for fname, labels in template.get("fields", {}).items():
        if fname not in FIELD_LABELS:
            raise ValueError(f"Unknown field in mapping: {fname}")
        if isinstance(labels, str):
            labels = [labels]
        cols = []
        for label in labels:
            col = by_label.get(normalize_header(label))
            if col is None:
                result.notes.append(f"Mapped column '{label}' for {FIELD_LABELS[fname]} not found in file")
                continue
            cols.append(col)
        if cols:
            result.indices[fname] = [c.index for c in cols]
            result.fields[fname] = [c.label for c in cols]
            result.confidence[fname] = 100
    result.missing_required = [f for f in REQUIRED_FIELDS if f not in result.indices]
    if "taxable_value" not in result.indices and "invoice_value" not in result.indices:
        result.missing_required.append("taxable_value")
    return result


def header_score(columns: list[Column]) -> int:
    return len({f for _s, _p, f, _c in score_columns(columns, fuzzy=False)})
