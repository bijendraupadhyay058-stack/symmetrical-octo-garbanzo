"""Purchase invoices saved as PDF by billing software (PDFs with text, not scans), read on this computer.

The reader looks for the usual words of a GST tax invoice: the supplier's GSTIN (any GSTIN other than the
client's own), "Invoice No", "Invoice Date" / "Dated", "Taxable value", CGST / SGST / UTGST / IGST / Cess and the
invoice total. Every figure found is shown on a check screen before anything is saved; when taxable value plus
tax does not add up to the total, or something is missing, the invoice is flagged. A scanned PDF (an image) has no
text: it is reported, not guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..core.gstin import validate_gstin
from ..core.money import ZERO
from .parsing import parse_date

_GSTIN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
_AMOUNT = re.compile(r"(?<![\d.])(?:₹|rs\.?|inr)?\s*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?\)?|\d+(?:\.\d{1,2})?)"
                     r"(?![\d%])", re.IGNORECASE)
_DATE = re.compile(r"\b(\d{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3,9})[-/.]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
_INV_NO = re.compile(r"(?:tax\s+)?(?:invoice|inv|bill)\.?\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-_.]{0,24})",
                     re.IGNORECASE)
_INV_DATE = re.compile(r"(?:invoice|inv|bill)?\.?\s*(?:date|dated|dt)\.?\s*[:\-]?\s*(" + _DATE.pattern[2:-2] + r")",
                       re.IGNORECASE)
LABELS = {
    "taxable": re.compile(r"\b(total\s+)?(taxable\s+(value|amount|amt)|assessable\s+value|sub\s*-?\s*total)\b", re.I),
    "igst": re.compile(r"\b(igst|integrated\s+tax)\b", re.I),
    "cgst": re.compile(r"\b(cgst|central\s+tax)\b", re.I),
    "sgst": re.compile(r"\b(sgst|utgst|state\s+tax|sgst\s*/\s*utgst)\b", re.I),
    "cess": re.compile(r"\bcess\b", re.I),
    "total": re.compile(r"\b(grand\s+total|invoice\s+(value|total|amount)|total\s+(invoice\s+)?amount|amount\s+"
                        r"payable|net\s+amount|total\s+value)\b", re.I),
}
_SKIP_TOTAL = re.compile(r"\b(in\s+words|rupees\s+\w+\s+only|taxable)\b", re.I)


@dataclass
class PdfInvoice:
    file: Path
    supplier_gstin: str = ""
    supplier_name: str = ""
    invoice_no: str = ""
    invoice_date: date | None = None
    taxable: Decimal = ZERO
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO
    total: Decimal | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def problems(self) -> list[str]:
        out = []
        if not self.supplier_gstin:
            out.append("supplier GSTIN not found")
        elif not validate_gstin(self.supplier_gstin)[0]:
            out.append(f"supplier GSTIN {self.supplier_gstin} is not valid")
        if not self.invoice_no:
            out.append("invoice number not found")
        if self.invoice_date is None:
            out.append("invoice date not found")
        if not self.taxable:
            out.append("taxable value not found")
        if self.total is not None and self.taxable and abs(self.taxable + self.tax - self.total) > Decimal("1.00"):
            out.append(f"taxable value + tax ({self.taxable + self.tax:,.2f}) does not equal the total "
                       f"({self.total:,.2f}) – check the amounts")
        return out


def pdf_text(path: str | Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001 - any failure means a password is needed
                raise ValueError("the PDF is protected by a password") from None
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except PdfReadError as exc:
        raise ValueError(f"not a readable PDF ({exc})") from None


def _amounts(line: str) -> list[Decimal]:
    out = []
    for m in _AMOUNT.finditer(line):
        raw = m.group(1)
        neg = raw.startswith("(") and raw.endswith(")")
        raw = raw.strip("()").replace(",", "")
        try:
            v = Decimal(raw)
        except ArithmeticError:
            continue
        out.append(-v if neg else v)
    return out


def _value_after(line: str, label: re.Pattern) -> Decimal | None:
    """The amount on the line after its label (the last one: rate columns and percentages come first)."""
    m = label.search(line)
    if not m:
        return None
    rest = re.sub(r"@?\s*\d+(\.\d+)?\s*%", " ", line[m.end():])  # drop rates such as '@ 9%'
    nums = [v for v in _amounts(rest)]
    return nums[-1] if nums else None


def parse_invoice(text: str, own_gstin: str, file: str | Path = "") -> PdfInvoice:
    inv = PdfInvoice(Path(file))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    gstins = []
    for g in _GSTIN.findall(text.upper()):
        if g not in gstins:
            gstins.append(g)
    others = [g for g in gstins if g != own_gstin]
    if own_gstin and own_gstin not in gstins:
        inv.notes.append("your client's GSTIN is not on the invoice – check it is addressed to the client")
    if others:
        inv.supplier_gstin = others[0]
        if len(others) > 1:
            inv.notes.append("more than one other GSTIN on the invoice – the first one is taken as the supplier: "
                             + ", ".join(others))
    for ln in lines[:8]:  # the seller's name is normally at the top
        if not re.search(r"tax\s+invoice|original|duplicate|triplicate|gstin|invoice|page\s+\d", ln, re.I) and \
                re.search(r"[A-Za-z]{3}", ln) and len(ln) <= 80:
            inv.supplier_name = ln
            break
    m = _INV_NO.search(text)
    if m:
        inv.invoice_no = m.group(1).rstrip(".-/")
    m = _INV_DATE.search(text)
    candidates = [m.group(1)] if m else []
    candidates += _DATE.findall(text)
    for c in candidates:
        try:
            d = parse_date(c)
        except ValueError:
            d = None
        if d:
            inv.invoice_date = d
            break
    found: dict[str, list[Decimal]] = {k: [] for k in LABELS}
    totals: dict[str, Decimal] = {}
    for ln in lines:
        for head, pat in LABELS.items():
            if head == "total" and _SKIP_TOTAL.search(ln):
                continue
            v = _value_after(ln, pat)
            if v is None:
                continue
            if re.match(r"^\s*total\b", ln, re.I) and head in ("igst", "cgst", "sgst", "cess"):
                totals[head] = v  # 'Total CGST 1,800.00'
            else:
                found[head].append(v)
    for head in ("igst", "cgst", "sgst", "cess"):
        vals = found[head]
        if head in totals:
            setattr(inv, head, totals[head])
        elif vals:
            # tax summary lines by rate are added up; a figure repeated (item table and summary) is counted once
            distinct = []
            for v in vals:
                if v not in distinct:
                    distinct.append(v)
            setattr(inv, head, sum(distinct, ZERO))
            if len(distinct) > 1:
                inv.notes.append(f"{head.upper()}: {len(distinct)} amounts found and added up – check")
    if found["taxable"]:
        inv.taxable = max(found["taxable"])
    if found["total"]:
        inv.total = max(found["total"])
    if not inv.taxable and inv.total is not None:
        inv.taxable = inv.total - inv.tax
        inv.notes.append("taxable value worked out as total − tax")
    if inv.cgst != inv.sgst and (inv.cgst or inv.sgst):
        inv.notes.append("CGST and SGST differ – check")
    return inv


def read_pdf_invoice(path: str | Path, own_gstin: str) -> PdfInvoice:
    path = Path(path)
    try:
        text = pdf_text(path)
    except ValueError as exc:
        inv = PdfInvoice(path)
        inv.notes.append(f"{path.name}: {exc}")
        return inv
    if len(re.sub(r"\s", "", text)) < 20:
        inv = PdfInvoice(path)
        inv.notes.append("no text in the PDF – it is a scanned image; enter this invoice by hand")
        return inv
    return parse_invoice(text, own_gstin, path)
