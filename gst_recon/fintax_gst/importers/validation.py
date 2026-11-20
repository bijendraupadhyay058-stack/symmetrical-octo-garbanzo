"""Turn one canonical source row into a validated InvoiceRecord.

Every problem is reported: errors reject the row (it is kept in the rejection
list with its raw values), warnings accept it with a note. Values are never
altered silently – derived or reinterpreted values always carry a warning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..core.gstin import normalize_gstin, validate_gstin
from ..core.invoice_no import clean_raw_invoice_no
from ..core.models import LEFT_SOURCES, OUTWARD_SOURCES, REFERENCE_SOURCES, DocType, InvoiceRecord, Source, period_of
from ..core.money import ZERO, AmountParseError, parse_amount
from .parsing import (
    DateParseError, parse_bool, parse_date, parse_doc_type, parse_ims_action, parse_period, parse_text,
    tally_voucher_doc_type,
)


@dataclass
class RowContext:
    source: Source
    layout: str  # "tally", "gstn" or "generic"
    file_name: str
    period: str | None = None  # file-level period (GSTR-2B return period / books override)


@dataclass
class RowOutcome:
    record: InvoiceRecord | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ignored: str = ""  # reason the row is deliberately not imported (kept in the import log)


#: e-way bill document types that are not a supply by the client to the other party.
EWB_NOT_SUPPLY = ("challan", "billofentry", "others", "other")


def _ref_status(value) -> str:
    text = parse_text(value).upper()
    if not text:
        return "ACTIVE"
    if "CANCEL" in text or text in ("CNL", "CAN", "C"):
        return "CANCELLED"
    if text in ("ACT", "ACTIVE", "GENERATED", "GEN", "A", "VALID"):
        return "ACTIVE"
    return text[:20]


def _reference_skip(row: dict, source: Source) -> str:
    """Why an e-way bill row is not one of the client's own outward supplies ('' if it is)."""
    if source != Source.EWB:
        return ""
    direction = parse_text(row.get("supply_type")).lower()
    if direction.startswith("inward"):
        return "Inward e-way bill (goods received) – not compared with the sales register"
    doc = re.sub(r"[^a-z]", "", parse_text(row.get("doc_type")).lower())
    if any(doc.startswith(x) or x in doc for x in EWB_NOT_SUPPLY):
        return (f"e-way bill for a '{parse_text(row.get('doc_type'))}' – not a supply invoice, not compared "
                "with the sales register")
    return ""


def _journal_skip(row: dict, source: Source) -> str:
    """Why a journal voucher of a register is not a supplier's bill ('' if it is one).

    Journal registers also hold depreciation, provisions, TDS and ITC reversal entries; those are listed as
    not imported with the reason, never rejected as errors."""
    if source != Source.BOOKS or "journal" not in parse_text(row.get("voucher_type")).lower():
        return ""
    raw = []
    for k in ("igst", "cgst", "sgst", "cess"):
        v = row.get(k)
        raw += v if isinstance(v, list) else [v]
    amounts = []
    for v in raw:
        try:
            amounts.append((v, parse_amount(v)))
        except AmountParseError:
            return ""  # let the normal validation report the bad amount
    taxed = [(v, a) for v, a in amounts if a]
    if not taxed:
        return "Journal without GST – not a supplier's bill (e.g. depreciation, provision, TDS)"
    if any(a < 0 or str(v).strip().lower().endswith("cr") for v, a in taxed):
        return "Journal credits a GST ledger (ITC reversal or adjustment) – not a supplier's bill"
    if not normalize_gstin(parse_text(row.get("supplier_gstin"))):
        return ("Journal without supplier GSTIN (e.g. reverse charge from an unregistered supplier) – not compared "
                "with GSTR-2B")
    return ""


def _amount(row: dict, name: str, errors: list) -> Decimal | None:
    value = row.get(name)
    values = value if isinstance(value, list) else [value]
    total, seen = ZERO, False
    for v in values:
        try:
            parsed = parse_amount(v)
        except AmountParseError as exc:
            errors.append(f"{name.replace('_', ' ')}: {exc}")
            return None
        if parsed is not None:
            total += parsed
            seen = True
    return total if seen else None


def build_record(row: dict, ctx: RowContext, uid: str) -> RowOutcome:
    errors: list[str] = []
    warnings: list[str] = []

    outward = ctx.source in OUTWARD_SOURCES
    skip = _reference_skip(row, ctx.source) or _journal_skip(row, ctx.source)
    if skip:
        return RowOutcome(None, ignored=skip)
    gstin = normalize_gstin(parse_text(row.get("supplier_gstin")))
    if outward and gstin in ("URP", "UNREGISTERED", "B2C", "NA", "NIL", "CONSUMER", "CASH"):
        gstin = ""
    if not gstin and outward:
        pass  # unregistered recipient (B2C) or export: compared at summary level, not invoice by invoice
    elif not gstin:
        errors.append("Supplier GSTIN missing (unregistered purchases cannot be reconciled with GSTR-2B)")
    else:
        ok, problem = validate_gstin(gstin)
        if not ok:
            errors.append(f"{problem}: '{gstin}'")
        elif problem:
            warnings.append(f"{problem}: '{gstin}' – please verify")

    invoice_no = clean_raw_invoice_no(row.get("invoice_no")) if row.get("invoice_no") is not None else ""
    if invoice_no.lower() in ("", "nan", "none"):
        errors.append("Invoice number missing")

    invoice_date = None
    try:
        invoice_date = parse_date(row.get("invoice_date"))
        if invoice_date is None:
            errors.append("Invoice date missing")
    except DateParseError as exc:
        errors.append(f"Invoice date: {exc}")

    voucher_date = None
    if row.get("voucher_date") is not None:
        try:
            voucher_date = parse_date(row.get("voucher_date"))
        except DateParseError as exc:
            warnings.append(f"Voucher date ignored: {exc}")

    # Document type, from the supplier's point of view.
    doc_type: DocType | None = None
    if ctx.layout == "tally" and row.get("voucher_type") is not None:
        doc_type = (parse_doc_type(row.get("voucher_type")) if outward  # own sales: no buyer/supplier flip
                    else tally_voucher_doc_type(row.get("voucher_type")))
        if doc_type is None:
            warnings.append(f"Voucher type '{row.get('voucher_type')}' not recognised – treated as invoice")
    if doc_type is None and row.get("doc_type") is not None:
        doc_type = parse_doc_type(row.get("doc_type"))
        if doc_type is None and ctx.source in REFERENCE_SOURCES and "supply" in str(row.get("doc_type")).lower():
            doc_type = DocType.INVOICE  # bill of supply
        if doc_type is None:
            errors.append(f"Document type '{row.get('doc_type')}' not recognised")
    if doc_type is None and row.get("_note_sheet"):
        errors.append("Note type (credit/debit) missing for a credit/debit note row")
    doc_type = doc_type or DocType.INVOICE

    taxable = _amount(row, "taxable_value", errors)
    taxes = {k: _amount(row, k, errors) for k in ("igst", "cgst", "sgst", "cess")}
    invoice_value = _amount(row, "invoice_value", errors)

    if taxable is None:
        if invoice_value is not None and not errors:
            taxable = invoice_value - sum((v or ZERO) for v in taxes.values())
            warnings.append(f"Taxable value not given – derived as invoice value less tax = {taxable}")
        elif not errors:
            errors.append("Taxable value missing")
    if all(v is None for v in taxes.values()) and not errors:
        warnings.append("No tax amounts present – treated as zero tax (verify exempt/nil-rated/RCM)")

    amounts = [v for v in (taxable, *taxes.values()) if v is not None]
    negatives = [v for v in amounts if v < 0]
    positives = [v for v in amounts if v > 0]
    if negatives and positives:
        errors.append("Mixed positive and negative amounts in one document")
    elif negatives:
        if doc_type == DocType.INVOICE:
            doc_type = DocType.CREDIT_NOTE
            warnings.append("Negative amounts – document treated as a credit note")
        elif doc_type == DocType.DEBIT_NOTE:
            warnings.append("Negative amounts on a debit note – magnitudes used")

    if errors:
        return RowOutcome(None, errors, warnings)

    taxable = abs(taxable)
    t = {k: abs(v) if v is not None else ZERO for k, v in taxes.items()}
    if t["igst"] > 0 and (t["cgst"] > 0 or t["sgst"] > 0):
        warnings.append("Both IGST and CGST/SGST charged on one document")
    if abs(t["cgst"] - t["sgst"]) > Decimal("1"):
        warnings.append(f"CGST ({t['cgst']}) and SGST ({t['sgst']}) are not equal")

    if ctx.source in LEFT_SOURCES:
        if voucher_date is not None:
            period = period_of(voucher_date)
        elif ctx.period:
            period = ctx.period
        else:
            period = period_of(invoice_date)
    elif ctx.source == Source.GSTR8A or ctx.source in REFERENCE_SOURCES:
        period = period_of(invoice_date)  # annual statement / portal report: each document in its own month
    else:
        period = ctx.period or ""

    original_date = None
    if row.get("original_invoice_date") is not None:
        try:
            original_date = parse_date(row.get("original_invoice_date"))
        except DateParseError as exc:
            warnings.append(f"Original invoice date ignored: {exc}")
    is_amendment = bool(row.get("_amendment"))
    original_no = parse_text(row.get("original_invoice_no"))
    if is_amendment and not original_no:
        warnings.append("Amendment row without original document number")

    ims_action = ""
    if ctx.source == Source.IMS:
        ims_action = parse_ims_action(row.get("ims_action"))
        if ims_action is None:
            return RowOutcome(None, [f"IMS action '{row.get('ims_action')}' not recognised"], warnings)
        if row.get("ims_action") is None or parse_text(row.get("ims_action")) == "":
            warnings.append("No IMS action recorded – treated as 'No action' (deemed accepted)")
    itc = parse_text(row.get("itc_availability")).upper()[:1]
    rate = None
    try:
        rate = parse_amount(row.get("rate")) if not isinstance(row.get("rate"), list) else None
    except AmountParseError:
        warnings.append(f"Tax rate '{row.get('rate')}' ignored")

    hsn_lines = []
    hsn = parse_text(row.get("hsn")).replace(" ", "").replace(".", "")[:10]
    if hsn:
        try:
            qty = abs(parse_amount(row.get("quantity")) or ZERO)
        except AmountParseError:
            qty = ZERO
            warnings.append(f"Quantity '{row.get('quantity')}' ignored")
        hsn_lines = [{"hsn": hsn, "uqc": parse_text(row.get("uqc")).upper()[:10], "qty": str(qty),
                      "taxable": str(taxable), **{k: str(v) for k, v in t.items()}}]

    irn = ref_no = ref_status = ""
    if ctx.source in REFERENCE_SOURCES:
        irn = parse_text(row.get("irn")).replace(" ", "")[:64]
        ref_no = parse_text(row.get("ref_no")).replace(" ", "")
        if ref_no.endswith(".0") and ref_no[:-2].isdigit():
            ref_no = ref_no[:-2]  # a number read from Excel as a float
        ref_no = ref_no[:30]
        ref_status = _ref_status(row.get("ref_status"))
        what = "IRN" if ctx.source == Source.EINV else "e-way bill"
        if ctx.source == Source.EINV and not irn and not ref_no:
            warnings.append("No IRN or acknowledgement number – verify the e-invoice report")
        if ctx.source == Source.EWB and not ref_no:
            warnings.append("No e-way bill number")
        if ref_status == "CANCELLED":
            warnings.append(f"{what} cancelled – imported, but not counted as reported for this document")
        elif ref_status != "ACTIVE":
            warnings.append(f"{what} status '{ref_status}' not recognised – treated as active")

    record = InvoiceRecord(
        uid=uid, source=ctx.source, supplier_gstin=gstin, doc_type=doc_type, invoice_no=invoice_no,
        invoice_date=invoice_date, taxable=taxable, igst=t["igst"], cgst=t["cgst"], sgst=t["sgst"],
        cess=t["cess"], period=period, supplier_name=parse_text(row.get("supplier_name")),
        invoice_value=abs(invoice_value) if invoice_value is not None else None, rate=rate,
        place_of_supply=parse_text(row.get("place_of_supply")), reverse_charge=parse_bool(row.get("reverse_charge")),
        itc_availability=itc, itc_reason=parse_text(row.get("itc_reason")), is_amendment=is_amendment,
        original_invoice_no=original_no, original_invoice_date=original_date,
        supplier_period=parse_period(row.get("supplier_period")) or parse_text(row.get("supplier_period")),
        source_file=ctx.file_name, source_rows=str(row.get("_row", "")),
        description=parse_text(row.get("description"))[:500], ims_action=ims_action,
        supply_type=parse_text(row.get("supply_type"))[:40], hsn_lines=hsn_lines,
        irn=irn, ref_no=ref_no, ref_status=ref_status,
    )
    return RowOutcome(record, errors, warnings)
