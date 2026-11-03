from datetime import date
from decimal import Decimal

import pytest

from fintax_gst.core.gstin import check_digit, is_valid_gstin, normalize_gstin, pan_of, validate_gstin
from fintax_gst.core.invoice_no import clean_raw_invoice_no, loose_invoice_no, normalize_invoice_no
from fintax_gst.core.money import AmountParseError, fmt_inr, parse_amount
from fintax_gst.importers.parsing import (
    DateParseError, parse_date, parse_doc_type, parse_period, tally_voucher_doc_type,
)
from fintax_gst.core.models import DocType, fy_of


@pytest.mark.parametrize("raw", ["INV/001/26", "INV-001-26", "inv 001 26", " INV.001.26 ", "INV00126"])
def test_invoice_number_variants_normalise_equal(raw):
    assert normalize_invoice_no(raw) == "INV00126"


def test_loose_number_ignores_leading_zeros_only():
    assert loose_invoice_no("PP-0007") == loose_invoice_no("PP-7") == "PP7"
    assert loose_invoice_no("INV-001") != loose_invoice_no("INV-002")
    assert normalize_invoice_no("A-10") != normalize_invoice_no("A-100")


def test_excel_float_invoice_number():
    assert clean_raw_invoice_no(12345.0) == "12345"


def test_gstin_checksum_and_format():
    assert is_valid_gstin("27AAPFU0939F1ZV")
    assert check_digit("27AAPFU0939F1Z") == "V"
    ok, problem = validate_gstin("27AAPFU0939F1ZA")
    assert ok and "check digit" in problem
    assert validate_gstin("27AAPFU0939F1")[0] is False
    assert validate_gstin("00AAPFU0939F1ZV")[0] is False  # unknown state code
    assert normalize_gstin(" 27aapfu0939f1zv ") == "27AAPFU0939F1ZV"
    assert pan_of("27AAPFU0939F1ZV") == "AAPFU0939F"


@pytest.mark.parametrize("raw,expected", [
    ("1,23,456.50", Decimal("123456.50")), ("₹ 1,000", Decimal("1000")), ("(1,234.00)", Decimal("-1234.00")),
    ("500-", Decimal("-500")), ("-12.5", Decimal("-12.5")), (1234.56, Decimal("1234.56")), (7, Decimal(7)),
    ("1000 Dr", Decimal("1000")), ("", None), (None, None), ("-", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_amount_rejects_text():
    with pytest.raises(AmountParseError):
        parse_amount("abc")


def test_float_never_leaks_binary_error():
    total = sum(parse_amount(x) for x in (0.1, 0.2))
    assert total == Decimal("0.3")


@pytest.mark.parametrize("raw", ["05-04-2025", "05/04/2025", "2025-04-05", "05-Apr-2025", "5 April 2025", 45752,
                                 date(2025, 4, 5)])
def test_parse_date_day_first(raw):
    assert parse_date(raw) == date(2025, 4, 5)


def test_parse_date_invalid():
    with pytest.raises(DateParseError):
        parse_date("31-04-2025")


@pytest.mark.parametrize("raw,expected", [("042025", "2025-04"), ("2025-04", "2025-04"), ("April 2025", "2025-04"),
                                          ("Apr'25", "2025-04"), ("04-2025", "2025-04"), ("xyz", None)])
def test_parse_period(raw, expected):
    assert parse_period(raw) == expected


def test_doc_types_and_tally_convention():
    assert parse_doc_type("Credit Note") == DocType.CREDIT_NOTE
    assert parse_doc_type("D") == DocType.DEBIT_NOTE
    assert parse_doc_type("Regular") == DocType.INVOICE
    # Buyer's debit note voucher (purchase return) is the supplier's credit note.
    assert tally_voucher_doc_type("Debit Note") == DocType.CREDIT_NOTE
    assert tally_voucher_doc_type("Purchase") == DocType.INVOICE


def test_fy_and_inr_format():
    assert fy_of(date(2025, 3, 31)) == "2024-25"
    assert fy_of(date(2025, 4, 1)) == "2025-26"
    assert fmt_inr(Decimal("1234567.891")) == "12,34,567.89"
    assert fmt_inr(Decimal("-999")) == "-999.00"
