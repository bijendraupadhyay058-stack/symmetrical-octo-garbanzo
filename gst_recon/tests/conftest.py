from __future__ import annotations

import itertools
import os
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


TEST_DB_URL = os.environ.get("FINTAX_TEST_DB_URL")  # e.g. postgresql+psycopg://user@localhost/fintax_test


def _reset_server_schema(url: str) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()


@pytest.fixture
def db(tmp_path):
    """SQLite by default; the whole suite runs on PostgreSQL when FINTAX_TEST_DB_URL is set."""
    if TEST_DB_URL:
        _reset_server_schema(TEST_DB_URL)
        database = open_database(TEST_DB_URL, data_dir=tmp_path)
    else:
        database = open_database(tmp_path / "test.db")
    yield database
    database.dispose()


@pytest.fixture(scope="session")
def sample_files(tmp_path_factory):
    return write_all(tmp_path_factory.mktemp("samples"))
