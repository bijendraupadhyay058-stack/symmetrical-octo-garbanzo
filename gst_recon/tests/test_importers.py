import csv
import json
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook

from fintax_gst.core.models import DocType, Source
from fintax_gst.importers.pipeline import MappingRequired, preview_file
from fintax_gst.importers.readers import UnsupportedFileError
from fintax_gst.samples import REJECTED_BOOK_ROWS, books_docs, g2b_docs

from .conftest import GSTIN_A, GSTIN_B


def _key(r):
    return (r.supplier_gstin, r.doc_type, r.invoice_no, r.invoice_date, r.taxable, r.igst, r.cgst, r.sgst, r.cess)


def test_tally_register_detected_and_mapped(sample_files):
    p = preview_file(sample_files["books_april"], Source.BOOKS)
    assert p.layout == "tally"
    m = p.mappings["Purchase Register"].fields
    assert m["invoice_no"] == ["Supplier Invoice No."]  # not Tally's internal voucher number
    assert m["cgst"] == ["Input CGST 9%", "Input CGST 6%"]  # ledger columns summed
    assert len(p.records) == len(books_docs())
    assert p.rejected_rows == len(REJECTED_BOOK_ROWS)
    assert p.count("ignored") == 1  # Grand Total row
    assert p.duplicate_rows == 1
    assert {r.period for r in p.records} == {"2025-04"}


def test_tally_debit_note_voucher_becomes_supplier_credit_note(sample_files):
    p = preview_file(sample_files["books_april"], Source.BOOKS)
    cn = [r for r in p.records if r.invoice_no == "GCH-CN-12"][0]
    assert cn.doc_type == DocType.CREDIT_NOTE
    assert cn.taxable == Decimal("5000") and cn.signed("itc") == Decimal("-900")


def test_rejected_rows_keep_reason_and_raw_values(sample_files):
    p = preview_file(sample_files["books_april"], Source.BOOKS)
    errors = [i for i in p.issues if i.severity == "error"]
    assert any("GSTIN missing" in i.message for i in errors)
    assert any("31-04-2025" in i.message for i in errors)
    assert all(i.raw for i in errors)


def test_custom_csv_gives_same_documents_as_tally(sample_files):
    tally = preview_file(sample_files["books_april"], Source.BOOKS)
    custom = preview_file(sample_files["books_april_csv"], Source.BOOKS)
    assert custom.layout == "generic"
    assert sorted(map(_key, custom.records)) == sorted(map(_key, tally.records))
    assert custom.rejected_rows == tally.rejected_rows


def test_gstr2b_excel_portal_layout(sample_files):
    p = preview_file(sample_files["gstr2b_april"], Source.GSTR2B)
    assert p.layout == "gstr2b_excel" and p.period == "2025-04"
    assert len(p.records) == len(g2b_docs())
    amended = [r for r in p.records if r.is_amendment]
    assert len(amended) == 1 and amended[0].original_invoice_no == "OSL/45"
    notes = [r for r in p.records if r.doc_type == DocType.CREDIT_NOTE]
    assert len(notes) == 2
    na = [r for r in p.records if r.invoice_no == "KTX-2301"][0]
    assert na.itc_availability == "N"


def test_gstr2b_json_equals_excel(sample_files):
    xl = preview_file(sample_files["gstr2b_april"], Source.GSTR2B)
    js = preview_file(sample_files["gstr2b_april_json"], Source.GSTR2B)
    assert js.layout == "gstr2b_json" and js.period == "2025-04"
    assert sorted(map(_key, js.records)) == sorted(map(_key, xl.records))


def test_zip_export(tmp_path, sample_files):
    z = tmp_path / "2b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(sample_files["gstr2b_april_json"], "nested/returns_042025_R2B.json")
    p = preview_file(z, Source.GSTR2B)
    assert len(p.records) == len(g2b_docs())


def test_wrong_source_is_refused(sample_files):
    with pytest.raises(UnsupportedFileError):
        preview_file(sample_files["gstr2b_april"], Source.BOOKS)
    with pytest.raises(UnsupportedFileError):
        preview_file(sample_files["books_april"], Source.GSTR2B, period="2025-04")


def test_gstr2b_without_detectable_period_requires_one(tmp_path, sample_files):
    js = json.loads(sample_files["gstr2b_april_json"].read_text())
    del js["data"]["rtnprd"]
    f = tmp_path / "x.json"
    f.write_text(json.dumps(js))
    with pytest.raises(ValueError):
        preview_file(f, Source.GSTR2B)
    assert preview_file(f, Source.GSTR2B, period="2025-04").period == "2025-04"


def _csv(tmp_path, header, rows, name="reg.csv"):
    f = tmp_path / name
    with open(f, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return f


def test_negative_values_treated_as_credit_note_with_warning(tmp_path):
    f = _csv(tmp_path, ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "CGST", "SGST"],
             [[GSTIN_A, "R-1", "01-04-2025", "-1000", "-90", "-90"]])
    p = preview_file(f, Source.BOOKS)
    r = p.records[0]
    assert r.doc_type == DocType.CREDIT_NOTE and r.taxable == Decimal("1000")
    assert any("credit note" in i.message for i in p.issues if i.severity == "warning")


def test_mixed_signs_rejected(tmp_path):
    f = _csv(tmp_path, ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "CGST", "SGST"],
             [[GSTIN_A, "R-1", "01-04-2025", "1000", "-90", "90"]])
    p = preview_file(f, Source.BOOKS)
    assert not p.records and p.rejected_rows == 1


def test_missing_tax_components(tmp_path):
    f = _csv(tmp_path, ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "IGST", "CGST", "SGST"],
             [[GSTIN_B, "T-1", "01-04-2025", "1000", "180", "", ""],
              [GSTIN_B, "T-2", "01-04-2025", "1000", "", "", ""],
              [GSTIN_B, "T-3", "01-04-2025", "", "", "", ""]])
    p = preview_file(f, Source.BOOKS)
    by_no = {r.invoice_no: r for r in p.records}
    assert by_no["T-1"].igst == Decimal("180") and by_no["T-1"].cgst == 0
    assert by_no["T-2"].total_tax == 0
    assert any("No tax amounts" in i.message for i in p.issues)
    assert "T-3" not in by_no and p.rejected_rows == 1  # nothing to reconcile on: rejected, not dropped


def test_invalid_gstin_rejected_and_bad_checksum_warned(tmp_path):
    bad_check = GSTIN_A[:14] + ("A" if GSTIN_A[14] != "A" else "B")
    f = _csv(tmp_path, ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "IGST"],
             [["27ABC", "G-1", "01-04-2025", "100", "18"], [bad_check, "G-2", "01-04-2025", "100", "18"]])
    p = preview_file(f, Source.BOOKS)
    assert [r.invoice_no for r in p.records] == ["G-2"]
    assert any("check digit" in i.message for i in p.issues if i.severity == "warning")


def test_rate_lines_of_one_document_are_combined(tmp_path):
    f = _csv(tmp_path, ["GSTIN", "Invoice No", "Invoice Date", "Rate", "Taxable Value", "CGST", "SGST"],
             [[GSTIN_A, "ML-1", "01-04-2025", "18", "1000", "90", "90"],
              [GSTIN_A, "ML-1", "01-04-2025", "12", "500", "30", "30"]])
    p = preview_file(f, Source.BOOKS)
    assert len(p.records) == 1 and p.records[0].taxable == Decimal("1500") and p.records[0].cgst == Decimal("120")


def test_unrecognised_headings_require_mapping_then_template_works(tmp_path):
    f = _csv(tmp_path, ["Party Code", "Bill Ref", "Bill Dt", "Basic", "Tax A", "Tax B"],
             [[GSTIN_A, "Z-1", "01-04-2025", "1000", "90", "90"]])
    with pytest.raises(MappingRequired):
        preview_file(f, Source.BOOKS)
    template = {"fields": {"supplier_gstin": ["Party Code"], "invoice_no": ["Bill Ref"], "invoice_date": ["Bill Dt"],
                           "taxable_value": ["Basic"], "cgst": ["Tax A"], "sgst": ["Tax B"]}}
    p = preview_file(f, Source.BOOKS, template=template)
    assert p.records[0].cgst == Decimal("90") and p.records[0].invoice_no == "Z-1"


def test_header_found_below_title_rows_in_excel(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["My Company"])
    ws.append(["Purchase Book April"])
    ws.append([])
    ws.append(["Supplier GSTIN", "Bill No", "Bill Date", "Taxable Amount", "IGST Amount"])
    ws.append([GSTIN_B, "E-1", "02/04/2025", 1000, 180])
    f = tmp_path / "b.xlsx"
    wb.save(f)
    p = preview_file(f, Source.BOOKS)
    assert len(p.records) == 1 and p.records[0].igst == Decimal("180")


def test_unsupported_extension(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(UnsupportedFileError):
        preview_file(f, Source.BOOKS)
