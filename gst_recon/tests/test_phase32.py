"""Duplicate invoice detection and credit / debit note checks: findings, review marks, export; nothing deleted."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.core.invoice_no import normalize_invoice_no
from fintax_gst.db.models import Invoice, SourceFile
from fintax_gst.samples import CLIENT
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.doc_checks import DocCheckService, section34_limit

FY = "2025-26"
SUP = "27AAACR5055K1Z7"
SUP2 = "29AABCT1332L1ZU"
CUST = "24AAACC1206D1ZM"


def add_docs(db, client_id, rows):
    """rows: (source, gstin, doc_type, number, date, period, taxable, tax, original_no)."""
    with db.session() as s:
        files = {}
        for n, (src, gstin, dt, no, d, period, taxable, tax, orig) in enumerate(rows):
            if src not in files:
                sf = SourceFile(client_id=client_id, source_type=src, file_name=f"{src}.xlsx", file_path="",
                                sha256=f"{src}{n}", layout="test")
                s.add(sf)
                s.flush()
                files[src] = sf.id
            s.add(Invoice(client_id=client_id, source_file_id=files[src], source_type=src, supplier_gstin=gstin,
                          supplier_name=f"Party {gstin[:2]}", doc_type=dt, invoice_no=no,
                          invoice_no_norm=normalize_invoice_no(no), invoice_date=d, period=period, taxable=D(taxable),
                          igst=D(0), cgst=D(tax) / 2, sgst=D(tax) / 2, cess=D(0), original_invoice_no=orig,
                          identity_hash=f"h{n}"))
        s.commit()


@pytest.fixture
def client(db):
    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [
        # duplicates
        ("BOOKS", SUP, "INV", "INV-101", date(2025, 5, 2), "2025-05", 10000, 1800, ""),
        ("BOOKS", SUP, "INV", "INV-101", date(2025, 5, 2), "2025-05", 10000, 1800, ""),  # same month
        ("BOOKS", SUP, "INV", "INV-200", date(2025, 6, 5), "2025-06", 5000, 900, ""),
        ("BOOKS", SUP, "INV", "INV-200", date(2025, 6, 5), "2025-08", 5000, 900, ""),  # two months
        ("BOOKS", SUP2, "INV", "TS/12", date(2025, 7, 1), "2025-07", 2000, 360, ""),
        ("BOOKS", SUP2, "INV", "TS-012", date(2025, 7, 1), "2025-07", 2000, 360, ""),  # written differently
        ("BOOKS", SUP2, "INV", "A-55", date(2025, 9, 9), "2025-09", 7000, 1260, ""),
        ("BOOKS", SUP2, "INV", "A-56", date(2025, 9, 9), "2025-09", 7000, 1260, ""),  # near
        ("BOOKS", SUP2, "INV", "A-57", date(2025, 9, 10), "2025-09", 7000, 1260, ""),  # not a duplicate
        # notes – earlier year invoice for the late credit note
        ("SALES", CUST, "INV", "S-1", date(2024, 4, 10), "2024-04", 50000, 9000, ""),
        ("SALES", CUST, "CRN", "CN-1", date(2025, 12, 15), "2025-12", 5000, 900, "S-1"),  # past 30-11-2025
        ("SALES", CUST, "INV", "S-9", date(2025, 6, 1), "2025-06", 1000, 180, ""),
        ("SALES", CUST, "CRN", "CN-2", date(2025, 6, 20), "2025-06", 800, 144, "S-9"),
        ("SALES", CUST, "CRN", "CN-3", date(2025, 7, 20), "2025-07", 500, 90, "S-9"),  # exceeds S-9
        ("SALES", CUST, "CRN", "CN-4", date(2025, 5, 20), "2025-05", 100, 18, ""),  # no original
        ("SALES", CUST, "CRN", "CN-5", date(2025, 5, 21), "2025-05", 200, 36, "S-404"),  # original not found
        ("BOOKS", SUP, "CRN", "SCN-1", date(2025, 8, 1), "2025-08", 1000, 180, "INV-200"),
        ("BOOKS", SUP, "DBN", "DN-1", date(2024, 6, 1), "2025-12", 2000, 360, ""),  # DN of FY 24-25 booked Dec-25
        ("GSTR2B", SUP, "CRN", "SCN-1", date(2025, 8, 1), "2025-08", 1000, 180, ""),  # booked
        ("GSTR2B", SUP2, "CRN", "TCN-9", date(2025, 10, 3), "2025-10", 3000, 540, ""),  # not booked
    ])
    return c


def test_section34_limit():
    assert section34_limit(date(2024, 4, 10)) == date(2025, 11, 30)
    assert section34_limit(date(2025, 3, 31)) == date(2025, 11, 30)
    assert section34_limit(date(2025, 4, 1)) == date(2026, 11, 30)


def test_duplicates(db, client):
    rep = DocCheckService(db).check(client.id, FY, date(2026, 1, 15))
    kinds = {f.kind: f for f in rep.duplicates}
    assert set(kinds) == {"same_number", "two_months", "written_differently", "near"}
    assert kinds["same_number"].tax == D(1800) and kinds["same_number"].severity == "red"
    assert [d.period for d in kinds["two_months"].docs] == ["2025-06", "2025-08"]
    assert kinds["written_differently"].confidence == "medium"
    assert {d.number for d in kinds["near"].docs} == {"A-55", "A-56"} and kinds["near"].confidence == "low"
    assert len(rep.duplicates) == 4


def test_note_checks(db, client):
    rep = DocCheckService(db).check(client.id, FY, date(2026, 1, 15))
    got = {(f.kind, f.docs[-1].number if f.kind != "exceeds" else f.docs[0].number) for f in rep.notes}
    assert ("late_credit", "CN-1") in got
    assert ("exceeds", "S-9") in got
    assert ("no_original", "CN-4") in got and ("original_missing", "CN-5") in got
    assert ("late_debit", "DN-1") in got
    assert ("not_booked", "TCN-9") in got
    assert not any(f.kind == "not_booked" and f.docs[0].number == "SCN-1" for f in rep.notes)
    late = next(f for f in rep.notes if f.kind == "late_credit")
    assert late.severity == "red" and "30-11-2025" in late.detail
    aug = next(r for r in rep.reverse if r["month"] == "2025-08")
    assert aug["books"] == D(180) and aug["count"] == 1
    octo = next(r for r in rep.reverse if r["month"] == "2025-10")
    assert octo["not_booked"] == D(540) and octo["total"] == D(540)


def test_review_marks_keep_data(db, client, tmp_path):
    svc = DocCheckService(db)
    rep = svc.check(client.id, FY, date(2026, 1, 15))
    near = next(f for f in rep.duplicates if f.kind == "near")
    with pytest.raises(ServiceError, match="reason"):
        svc.mark(client.id, near, "not_issue", "")
    svc.mark(client.id, near, "not_issue", "two genuine bills – copies seen", "partner")
    dup = next(f for f in rep.duplicates if f.kind == "same_number")
    svc.mark(client.id, dup, "confirmed", "remove in Tally", "partner")
    rep = svc.check(client.id, FY, date(2026, 1, 15))
    near = next(f for f in rep.duplicates if f.kind == "near")
    assert near.decision == "not_issue" and near.marked_by == "partner"
    assert len(rep.open("duplicate")) == 2
    with db.session() as s:
        assert s.query(Invoice).count() == 20  # nothing deleted
    out = svc.export_xlsx(client.id, FY, tmp_path / "checks.xlsx", date(2026, 1, 15))
    from openpyxl import load_workbook

    wb = load_workbook(out)
    assert wb.sheetnames == ["Duplicates", "Credit-debit notes", "ITC to reverse"]
    assert any(r[7] == "Not an issue" for r in wb["Duplicates"].iter_rows(min_row=3, values_only=True))
