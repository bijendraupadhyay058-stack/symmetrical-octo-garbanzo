import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from fintax_gst.core.models import Category, ExceptionStatus, Source
from fintax_gst.db.models import AuditLog, ImportIssue, Invoice
from fintax_gst.engine import CancelToken, OperationCancelled
from fintax_gst.engine.summary import dashboard
from fintax_gst.samples import CLIENT, SCENARIOS, SUPPLIERS, gstin
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.imports import ImportService
from fintax_gst.services.reconciliation import ReconciliationService

from .conftest import GSTIN_A


def _client(db, **over):
    return ClientService(db).create(**{**CLIENT, **over})


def _load_demo(db, files):
    c = _client(db)
    svc = ImportService(db)
    for key, src in (("books_march", Source.BOOKS), ("books_april", Source.BOOKS), ("gstr2b_april", Source.GSTR2B)):
        svc.import_file(c.id, files[key], src, user="tester")
    return c


def test_client_validation_and_multiple_gstins_per_pan(db):
    svc = ClientService(db)
    a = svc.create("27AAPFU0939F1ZV", name="Firm MH", financial_year="2025-26")
    b = svc.create(gstin("29", "AAPFU0939F"), name="Firm KA")
    assert a.pan == b.pan == "AAPFU0939F" and a.state == "Maharashtra" and b.state == "Karnataka"
    assert len(svc.list(pan="AAPFU0939F")) == 2
    with pytest.raises(ServiceError):
        svc.create("27AAPFU0939F1ZV", name="dup")
    with pytest.raises(ServiceError):
        svc.create("27AAPFU0939F1ZA", name="bad checksum")
    with pytest.raises(ServiceError):
        svc.create(gstin("24", "AAPFU0939F"), name="x", financial_year="2025-27")
    svc.update(a.id, contact_person="New Person")
    assert svc.get(a.id).contact_person == "New Person"


def test_repeated_file_import_blocked_and_repeated_documents_skipped(db, sample_files, tmp_path):
    c = _client(db)
    svc = ImportService(db)
    sf, _ = svc.import_file(c.id, sample_files["books_april"], Source.BOOKS)
    again = svc.preview(c.id, sample_files["books_april"], Source.BOOKS)
    assert again.already_imported_file_id == sf.id
    with pytest.raises(ServiceError):
        svc.commit(c.id, again)
    # Same documents in a different file (custom CSV export) are recognised and skipped – and logged.
    csv_preview = svc.preview(c.id, sample_files["books_april_csv"], Source.BOOKS)
    assert csv_preview.new_records == []
    sf2 = svc.commit(c.id, csv_preview)
    assert sf2.documents_imported == 0 and sf2.documents_skipped_existing == len(csv_preview.records)
    with db.session() as s:
        n = len(s.scalars(select(ImportIssue).where(ImportIssue.source_file_id == sf2.id,
                                                    ImportIssue.severity == "existing")).all())
        assert n == len(csv_preview.records)
        assert s.query(Invoice).filter(Invoice.client_id == c.id).count() == sf.documents_imported


def test_client_data_isolation(db, sample_files):
    a = _client(db)
    b = _client(db, gstin=gstin("29", "AAPFU0939F"), name="Other client")
    ImportService(db).import_file(a.id, sample_files["books_april"], Source.BOOKS)
    # The same file is a fresh import for another client.
    sf, _ = ImportService(db).import_file(b.id, sample_files["books_april"], Source.BOOKS)
    assert sf.documents_imported > 0
    ImportService(db).import_file(a.id, sample_files["gstr2b_april"], Source.GSTR2B)
    with pytest.raises(ServiceError):
        ReconciliationService(db).run(b.id, "2025-05")
    run_b = ReconciliationService(db).run(b.id, "2025-04")
    lines = ReconciliationService(db).load(run_b).result.lines
    assert all(ln.gstr2b is None for ln in lines)  # client A's GSTR-2B never leaks into client B


def test_run_persist_reload_matches_engine(db, sample_files):
    c = _load_demo(db, sample_files)
    rs = ReconciliationService(db)
    run_id = rs.run(c.id, "2025-04")
    ctx = rs.load(run_id)
    d = dashboard(ctx.result.lines)
    with db.session() as s:
        books = s.scalars(select(Invoice).where(Invoice.source_type == "BOOKS", Invoice.period == "2025-04")).all()
        g2b = s.scalars(select(Invoice).where(Invoice.source_type == "GSTR2B")).all()
    sign = {"CRN": -1}
    assert d["itc_as_per_books"] == sum((i.igst + i.cgst + i.sgst + i.cess) * sign.get(i.doc_type, 1) for i in books)
    assert d["itc_as_per_gstr2b"] == sum((i.igst + i.cgst + i.sgst + i.cess) * sign.get(i.doc_type, 1) for i in g2b)
    assert d["total_purchase_invoices"] == len(books)
    stored = json.loads(rs.list_runs(c.id)[0].summary_json)
    assert Decimal(stored["itc_as_per_books"]) == d["itc_as_per_books"]
    # repeatable: a second run gives identical lines and fingerprint
    run2 = rs.run(c.id, "2025-04")
    ctx2 = rs.load(run2)
    sig = lambda r: [(ln.line_no, ln.category, ln.books and ln.books.db_id, ln.gstr2b and ln.gstr2b.db_id)  # noqa
                     for ln in r.result.lines]
    assert sig(ctx) == sig(ctx2) and ctx.run.fingerprint == ctx2.run.fingerprint


def test_demo_scenarios_through_full_pipeline(db, sample_files):
    c = _load_demo(db, sample_files)
    rs = ReconciliationService(db)
    lines = rs.load(rs.run(c.id, "2025-04")).result.lines
    for name, books, g2b, expected, _note in SCENARIOS:
        if books:
            got = {ln.category for ln in lines if ln.books and ln.books.invoice_no in {d.no for d in books}
                   and ln.books.supplier_gstin in {SUPPLIERS[d.sup][0] for d in books}}
        else:
            got = {ln.category for ln in lines if ln.gstr2b and ln.gstr2b.invoice_no in {d.no for d in g2b}}
        assert got == {expected}, f"{name}: expected {expected.value}, got {[g.value for g in got]}"


def test_exception_update_is_audited_and_carried_forward(db, sample_files):
    c = _load_demo(db, sample_files)
    rs = ReconciliationService(db)
    run1 = rs.run(c.id, "2025-04")
    line = next(ln for ln in rs.load(run1).result.lines if ln.category == Category.MISSING_IN_2B)
    rs.update_line(run1, line.line_no, "ca.user", status="Supplier Follow-up Required", remarks="Mailed supplier",
                   assigned_to="Asha", action_date=date(2025, 5, 20))
    with pytest.raises(ServiceError):
        rs.update_line(run1, line.line_no, status="Not a status")
    with db.session() as s:
        log = s.scalars(select(AuditLog).where(AuditLog.entity == "recon_line")).one()
        assert log.user == "ca.user" and "Mailed supplier" in log.details_json
    run2 = rs.run(c.id, "2025-04")
    again = next(ln for ln in rs.load(run2).result.lines if ln.books and ln.books.db_id == line.books.db_id)
    assert again.status == ExceptionStatus.SUPPLIER_FOLLOWUP and again.remarks == "Mailed supplier"
    assert again.assigned_to == "Asha"


def test_prior_period_itc_never_counted_twice(db, tmp_path):
    """A March booking matched in April's GSTR-2B must not be matched again in May."""
    c = _client(db)
    svc = ImportService(db)
    sup = SUPPLIERS["DOS"][0]

    def write(name, header, rows):
        f = tmp_path / name
        f.write_text("\n".join([",".join(header)] + [",".join(r) for r in rows]))
        return f

    hdr = ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "IGST"]
    svc.import_file(c.id, write("b3.csv", hdr, [[sup, "P-1", "28-03-2025", "1000", "180"]]), Source.BOOKS, "2025-03")
    svc.import_file(c.id, write("g4.csv", hdr, [[sup, "P-1", "28-03-2025", "1000", "180"]]), Source.GSTR2B, "2025-04")
    svc.import_file(c.id, write("g5.csv", hdr, [[sup, "P/1", "28-03-2025", "1000", "180"]]), Source.GSTR2B, "2025-05")
    rs = ReconciliationService(db)
    april = rs.load(rs.run(c.id, "2025-04")).result.lines
    assert [ln.category for ln in april] == [Category.PREVIOUS_PERIOD]
    may = rs.load(rs.run(c.id, "2025-05")).result.lines
    assert [ln.category for ln in may] == [Category.MISSING_IN_BOOKS]


def test_multi_month_and_financial_year_runs(db, sample_files):
    c = _load_demo(db, sample_files)
    rs = ReconciliationService(db)
    fy = rs.load(rs.run(c.id, "2025-04", "2026-03")).result
    assert fy.period_start == date(2025, 4, 1)
    q = rs.load(rs.run(c.id, "2025-03", "2025-04")).result
    # March books now in scope as current-period documents, not prior-period ones
    assert any(ln.books and ln.books.period == "2025-03" and not ln.books.is_prior_period for ln in q.lines)


def test_cancelled_run_saves_nothing(db, sample_files):
    c = _load_demo(db, sample_files)
    token = CancelToken()
    rs = ReconciliationService(db)

    def progress(pct, msg):
        if pct > 50:
            token.cancel()

    with pytest.raises(OperationCancelled):
        rs.run(c.id, "2025-04", progress=progress, cancel=token)
    assert rs.list_runs(c.id) == []


def test_remove_import_only_when_unused(db, sample_files, tmp_path):
    c = _load_demo(db, sample_files)
    svc = ImportService(db)
    used = [f for f in svc.list_files(c.id) if f.file_name == "gstr2b_2025-04.xlsx"][0]
    extra = tmp_path / "may.csv"
    extra.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n{GSTIN_A},MAY-1,02-05-2025,100,9,9\n")
    unused, _ = svc.import_file(c.id, extra, Source.BOOKS)
    ReconciliationService(db).run(c.id, "2025-04")
    with pytest.raises(ServiceError):
        svc.remove_import(c.id, used.id)
    assert svc.remove_import(c.id, unused.id) == 1
    with db.session() as s:
        assert s.scalars(select(AuditLog).where(AuditLog.action == "DELETE")).one().entity_id == str(unused.id)


def test_mapping_template_saved_and_reused(db, tmp_path):
    c = _client(db)
    f = tmp_path / "odd.csv"
    f.write_text(f"Party Code,Bill Ref,Bill Dt,Basic,Tax A,Tax B\n{GSTIN_A},Z-1,01-04-2025,1000,90,90\n")
    svc = ImportService(db)
    svc.save_template("odd-layout", Source.BOOKS, {"supplier_gstin": ["Party Code"], "invoice_no": ["Bill Ref"],
                                                   "invoice_date": ["Bill Dt"], "taxable_value": ["Basic"],
                                                   "cgst": ["Tax A"], "sgst": ["Tax B"]})
    p = svc.preview(c.id, f, Source.BOOKS, template="odd-layout")
    assert p.records[0].sgst == Decimal("90")


def test_backup_and_restore(db, sample_files, tmp_path):
    c = _client(db)
    backup = db.backup(tmp_path / "b.db")
    ImportService(db).import_file(c.id, sample_files["books_april"], Source.BOOKS)
    assert ImportService(db).list_files(c.id)
    db.restore(backup)
    assert ImportService(db).list_files(c.id) == []
