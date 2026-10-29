from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal

import pytest

from fintax_gst.core.models import DocType, InvoiceRecord, Source
from fintax_gst.db.database import open_database
from fintax_gst.samples import SUPPLIERS, write_all

GSTIN_A = SUPPLIERS["MSL"][0]  # 27AABCM1234K1Z?
GSTIN_A2 = SUPPLIERS["MSK"][0]  # same PAN, Karnataka
GSTIN_B = SUPPLIERS["BEL"][0]

_counter = itertools.count(1)


def rec(source: str, no: str, dt: date | str = "2025-04-10", taxable="1000", igst="0", cgst="90", sgst="90",
        cess="0", gstin: str = GSTIN_A, doc: DocType = DocType.INVOICE, period="2025-04", uid: str | None = None,
        **kw) -> InvoiceRecord:
    if isinstance(dt, str):
        dt = date.fromisoformat(dt)
    src = {"B": Source.BOOKS, "G": Source.GSTR2B}[source]
    return InvoiceRecord(
        uid=uid or f"{source}{next(_counter)}", source=src, supplier_gstin=gstin, doc_type=doc, invoice_no=no,
        invoice_date=dt, taxable=Decimal(taxable), igst=Decimal(igst), cgst=Decimal(cgst), sgst=Decimal(sgst),
        cess=Decimal(cess), period=period, **kw,
    )


@pytest.fixture
def db(tmp_path):
    database = open_database(tmp_path / "test.db")
    yield database
    database.dispose()


@pytest.fixture(scope="session")
def sample_files(tmp_path_factory):
    return write_all(tmp_path_factory.mktemp("samples"))
