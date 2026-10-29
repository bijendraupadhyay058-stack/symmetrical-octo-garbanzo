from datetime import date

import pytest
from sqlalchemy import select

from fintax_gst.core.models import Category, ExceptionStatus, Flag, Source
from fintax_gst.db.models import AuditLog
from fintax_gst.engine import reconcile
from fintax_gst.engine.summary import dashboard
from fintax_gst.samples import CLIENT, SUPPLIERS
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.followup import AttachmentService, VendorService
from fintax_gst.services.imports import ImportService
from fintax_gst.services.reconciliation import ReconciliationService
from fintax_gst.services.tracking import TrackingService

from .conftest import rec


def _demo(db, files):
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    for key, src in (("books_march", Source.BOOKS), ("books_april", Source.BOOKS), ("gstr2b_april", Source.GSTR2B)):
        svc.import_file(c.id, files[key], src)
    rs = ReconciliationService(db)
    return c, rs, rs.run(c.id, "2025-04")


def _find(lines, books_no=None, g_no=None):
    return next(ln for ln in lines if (books_no is None or (ln.books and ln.books.invoice_no == books_no))
                and (g_no is None or (ln.gstr2b and ln.gstr2b.invoice_no == g_no)))


def _docs(lines):
    return sorted(r.db_id for ln in lines for r in (ln.books, ln.gstr2b) if r is not None)


# ------------------------------------------------------------------ engine
def test_engine_manual_pairs_and_rejections():
    b, g = rec("B", "AAA-1", uid="b"), rec("G", "ZZZ-9", uid="g")
    ln = reconcile([b], [g], manual_pairs=[("b", "g", "by CA")]).lines
    assert len(ln) == 1 and ln[0].category == Category.MANUALLY_MATCHED and ln[0].reasons[0] == "by CA"
    b2, g2 = rec("B", "X-1", uid="b2"), rec("G", "X-1", uid="g2")
    lines = reconcile([b2], [g2], rejected_pairs=[("b2", "g2")]).lines
    assert {x.category for x in lines} == {Category.MISSING_IN_2B, Category.MISSING_IN_BOOKS}
    # fuzzy pass also respects rejection
    b3, g3 = rec("B", "DOS-1189", uid="b3"), rec("G", "DOS-1198", uid="g3")
    assert all(x.gstr2b is None or x.books is None
               for x in reconcile([b3], [g3], rejected_pairs=[("b3", "g3")]).lines)


def test_manual_match_of_one_duplicate_leaves_other_as_duplicate():
    b1, b2, g = rec("B", "D-1", uid="b1"), rec("B", "D-1", uid="b2"), rec("G", "D-1", uid="g")
    lines = reconcile([b1, b2], [g], manual_pairs=[("b1", "g", "")]).lines
    cats = sorted(x.category.value for x in lines)
    assert cats == sorted([Category.MANUALLY_MATCHED.value, Category.DUPLICATE_IN_BOOKS.value])


# ---------------------------------------------------------------- services
def test_confirm_probable_match_persists_into_rerun(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    lines = rs.load(run1).result.lines
    probable = _find(lines, "DOS-1189", "DOS-1198")
    assert probable.category == Category.PROBABLE
    before_docs = _docs(lines)
    rs.confirm_match(run1, probable.line_no, "ca", "Supplier confirmed typo")
    after = rs.load(run1).result.lines
    confirmed = _find(after, "DOS-1189")
    assert confirmed.category == Category.MANUALLY_MATCHED and confirmed.status == ExceptionStatus.RESOLVED
    assert _docs(after) == before_docs
    run2 = rs.run(c.id, "2025-04")
    assert _find(rs.load(run2).result.lines, "DOS-1189").category == Category.MANUALLY_MATCHED


def test_manual_match_two_single_sided_lines(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    lines = rs.load(run1).result.lines
    books_only = _find(lines, "MSL/260/25-26")  # missing in GSTR-2B
    g_only = _find(lines, g_no="OSL/377")  # missing in books (different supplier!)
    n_before = len(lines)
    kept = rs.manual_match(run1, books_only.line_no, g_only.line_no, "ca", "Same purchase")
    after = rs.load(run1).result.lines
    assert len(after) == n_before - 1
    merged = next(ln for ln in after if ln.line_no == kept)
    assert merged.category == Category.MANUALLY_MATCHED
    assert Flag.GSTIN_MISMATCH.value in merged.flags
    assert _docs(after) == _docs(lines)
    d = dashboard(after)
    assert d["itc_as_per_books"] == dashboard(lines)["itc_as_per_books"]  # totals unchanged
    with pytest.raises(ServiceError):
        rs.manual_match(run1, kept, _find(after, g_no="BEL-1950").line_no)  # kept line already paired


def test_cannot_pair_credit_note_with_invoice(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    lines = rs.load(run1).result.lines
    rs.unmatch(run1, _find(lines, "GCH-CN-12").line_no)
    lines = rs.load(run1).result.lines
    cn_books = next(ln for ln in lines if ln.books and ln.books.invoice_no == "GCH-CN-12")
    inv_g = _find(lines, g_no="OSL/377")
    with pytest.raises(ServiceError):
        rs.manual_match(run1, cn_books.line_no, inv_g.line_no)


def test_unmatch_splits_line_and_blocks_automatic_rematch(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    lines = rs.load(run1).result.lines
    pair = _find(lines, "BEL-2101")
    new_no = rs.unmatch(run1, pair.line_no, "ca", "Different consignment")
    after = rs.load(run1).result.lines
    assert len(after) == len(lines) + 1
    assert next(ln for ln in after if ln.line_no == pair.line_no).category == Category.MISSING_IN_2B
    assert next(ln for ln in after if ln.line_no == new_no).category == Category.MISSING_IN_BOOKS
    assert _docs(after) == _docs(lines)
    rerun = rs.load(rs.run(c.id, "2025-04")).result.lines
    assert not any(ln.books and ln.gstr2b and ln.books.invoice_no == "BEL-2101" for ln in rerun)
    # Re-confirming the pair supersedes the rejection.
    rs.manual_match(run1, pair.line_no, new_no, "ca")
    assert _find(rs.load(rs.run(c.id, "2025-04")).result.lines, "BEL-2101").category == Category.MANUALLY_MATCHED
    with db.session() as s:
        actions = [a.action for a in s.scalars(select(AuditLog).where(AuditLog.entity == "recon_line"))]
    assert "UNMATCH" in actions and "MANUAL_MATCH" in actions


def test_unmatching_prior_period_pair_does_not_add_prior_document_to_period(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    lines = rs.load(run1).result.lines
    prior = _find(lines, "DOS-1001")
    assert prior.category == Category.PREVIOUS_PERIOD
    rs.unmatch(run1, prior.line_no)
    after = rs.load(run1).result.lines
    assert dashboard(after)["itc_as_per_books"] == dashboard(lines)["itc_as_per_books"]
    assert not any(ln.books and ln.books.invoice_no == "DOS-1001" for ln in after)


def test_pending_clarification_category_survives_rerun(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    line = _find(rs.load(run1).result.lines, "MSL/233/25-26")
    rs.mark_pending_clarification(run1, line.line_no, "ca", "Asked client for invoice copy")
    assert _find(rs.load(run1).result.lines, "MSL/233/25-26").category == Category.PENDING_CLARIFICATION
    again = _find(rs.load(rs.run(c.id, "2025-04")).result.lines, "MSL/233/25-26")
    assert again.category == Category.PENDING_CLARIFICATION
    assert again.status == ExceptionStatus.CLIENT_CLARIFICATION


def test_remarks_follow_document_into_later_period(db, sample_files, tmp_path):
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    sup = SUPPLIERS["BEL"][0]
    b = tmp_path / "b.csv"
    b.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,IGST\n{sup},L-1,20-04-2025,1000,180\n")
    g = tmp_path / "g.csv"
    g.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,IGST\n{sup},L-1,20-04-2025,1000,180\n")
    svc.import_file(c.id, b, Source.BOOKS)
    rs = ReconciliationService(db)
    april = rs.run(c.id, "2025-04")
    rs.update_line(april, 1, "ca", status="Supplier Follow-up Required", remarks="Called supplier 5-May",
                   assigned_to="Asha")
    svc.import_file(c.id, g, Source.GSTR2B, period="2025-05")
    may = rs.load(rs.run(c.id, "2025-05")).result.lines
    assert may[0].category == Category.PREVIOUS_PERIOD
    assert "Called supplier 5-May" in may[0].remarks and may[0].assigned_to == "Asha"
    # Open-items register: closed now, listed once.
    assert TrackingService(db).open_items(c.id) == []
    hist = TrackingService(db).document_history(may[0].books.db_id)
    assert [h["category"] for h in hist] == [Category.MISSING_IN_2B.value, Category.PREVIOUS_PERIOD.value]


def test_open_items_and_fy_overview(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    items = TrackingService(db).open_items(c.id)
    ids = [i.invoice_id for i in items]
    assert len(ids) == len(set(ids))
    cats = {i.last_category for i in items}
    assert Category.MISSING_IN_2B.value in cats and "Not reconciled yet" in cats  # March MSL/090 never reconciled
    assert not any(i.invoice_no == "DOS-1001" for i in items)  # resolved as previous-period
    ov = TrackingService(db).fy_overview(c.id, "2025-26")
    assert len(ov) == 12 and ov[0]["run_id"] == run1 and ov[1]["run_id"] is None


def test_vendor_register(db, sample_files):
    c, rs, run1 = _demo(db, sample_files)
    vs = VendorService(db)
    gst = SUPPLIERS["MSL"][0]
    vs.upsert(c.id, gst, "ca", name="Mahalaxmi Steel", email="acc@msl.example", followup_status="Mail sent",
              next_followup="2025-05-10", remarks="Asked to upload MSL/260")
    vs.upsert(c.id, gst, "ca", followup_status="Reminder sent")
    v = vs.get(c.id, gst)
    assert v.email == "acc@msl.example" and v.followup_status == "Reminder sent"
    assert [x.gstin for x in vs.due(c.id, date(2025, 5, 31))] == [gst]
    with pytest.raises(ServiceError):
        vs.upsert(c.id, gst, followup_status="Maybe")


def test_attachments_follow_documents_across_runs(db, sample_files, tmp_path):
    c, rs, run1 = _demo(db, sample_files)
    line = _find(rs.load(run1).result.lines, "MSL/260/25-26")
    ev = tmp_path / "supplier_mail.pdf"
    ev.write_bytes(b"%PDF-1.4 evidence")
    att = AttachmentService(db).add(run1, line.line_no, ev, "ca", "Supplier's reply")
    assert AttachmentService.verify(att)
    run2 = rs.run(c.id, "2025-04")
    line2 = _find(rs.load(run2).result.lines, "MSL/260/25-26")
    found = AttachmentService(db).for_line(run2, line2.line_no)
    assert [a.file_name for a in found] == ["supplier_mail.pdf"]
    assert AttachmentService(db).counts(run2) == {line2.line_no: 1}


def test_migration_from_v1_database(tmp_path):
    """An existing Phase 1 database is upgraded in place, with a backup first."""
    from fintax_gst.db.database import MIGRATIONS, Database

    path = tmp_path / "old.db"
    old = Database(path)
    first = MIGRATIONS[:1]
    import fintax_gst.db.database as dbm

    saved = dbm.MIGRATIONS
    dbm.MIGRATIONS = first
    try:
        old.migrate()
    finally:
        dbm.MIGRATIONS = saved
    assert old.current_version() == 1
    old.dispose()
    db = Database(path)
    assert db.migrate() == [2]
    assert db.current_version() == 2
    assert list((tmp_path / "backups").glob("*pre-migration-v2.db"))
    db.dispose()
