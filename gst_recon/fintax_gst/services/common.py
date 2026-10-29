from __future__ import annotations

import getpass
import json
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..core.models import DocType, InvoiceRecord, Source
from ..db.models import AuditLog, Invoice


class ServiceError(ValueError):
    """A user-facing error (bad input, blocked action)."""


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover
        return "local-user"


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(type(value))


def dumps(value) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=False, sort_keys=True)


def audit(session: Session, action: str, entity: str, entity_id="", details: dict | None = None,
          user: str | None = None, client_id: int | None = None) -> None:
    session.add(AuditLog(user=user or current_user(), client_id=client_id, action=action, entity=entity,
                         entity_id=str(entity_id), details_json=dumps(details or {})))


def invoice_to_record(row: Invoice, file_name: str = "", prior: bool = False) -> InvoiceRecord:
    return InvoiceRecord(
        uid=f"I{row.id}", source=Source(row.source_type), supplier_gstin=row.supplier_gstin,
        doc_type=DocType(row.doc_type), invoice_no=row.invoice_no, invoice_date=row.invoice_date,
        taxable=row.taxable, igst=row.igst, cgst=row.cgst, sgst=row.sgst, cess=row.cess, period=row.period,
        supplier_name=row.supplier_name, invoice_value=row.invoice_value, place_of_supply=row.place_of_supply,
        reverse_charge=row.reverse_charge, itc_availability=row.itc_availability, itc_reason=row.itc_reason,
        is_amendment=row.is_amendment, original_invoice_no=row.original_invoice_no,
        original_invoice_date=row.original_invoice_date, supplier_period=row.supplier_period,
        source_file=file_name, source_rows=row.source_rows, db_id=row.id, is_prior_period=prior,
    )
