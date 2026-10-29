"""Turn one canonical source row into a validated InvoiceRecord.

Every problem is reported: errors reject the row (it is kept in the rejection
list with its raw values), warnings accept it with a note. Values are never
altered silently – derived or reinterpreted values always carry a warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..core.gstin import normalize_gstin, validate_gstin
from ..core.invoice_no import clean_raw_invoice_no
from ..core.models import LEFT_SOURCES, DocType, InvoiceRecord, Source, period_of
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

    outward = ctx.source in (Source.SALES, Source.GSTR1)
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
    elif ctx.source == Source.GSTR8A:
        period = period_of(invoice_date)  # an annual statement: each document belongs to its own month
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
        supply_type=parse_text(row.get("supply_type"))[:40],
    )
    return RowOutcome(record, errors, warnings)
