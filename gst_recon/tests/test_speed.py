"""Large-data speed: the read cache, its emptying on writes, and pages prepared in the background."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal as D  # noqa: E402


from fintax_gst.core.models import Source  # noqa: E402
from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.clients import ClientService  # noqa: E402
from fintax_gst.services.imports import ImportService  # noqa: E402
from fintax_gst.services.reconciliation import ReconciliationService  # noqa: E402


def test_cache_is_emptied_by_writes(db, sample_files):
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    assert db.cached("k", compute) == 1 and db.cached("k", compute) == 1 and len(calls) == 1
    c = ClientService(db).create(**CLIENT)  # a write: everything cached is dropped
    assert db.cached("k", compute) == 2
    with db.session() as s:  # a read-only session keeps the cache
        s.execute(__import__("sqlalchemy").select(1))
    assert db.cached("k", compute) == 2
    svc = ImportService(db)
    svc.import_file(c.id, sample_files["books_april"], Source.BOOKS)
    svc.import_file(c.id, sample_files["gstr2b_april_json"], Source.GSTR2B)
    rec = ReconciliationService(db)
    run = rec.run(c.id, "2025-04")
    first = rec.load(run)
    assert rec.load(run) is first  # loaded once
    line = next(ln for ln in first.result.lines if ln.books and ln.gstr2b)
    rec.update_line(run, line.line_no, "manager", remarks="checked with supplier")
    assert rec.load(run) is not first  # a change reloads it


def test_cache_entries_are_bounded(db):
    for i in range(db.CACHE_ENTRIES + 5):
        db.cached(("n", i), lambda i=i: i)
    assert len(db._cache) == db.CACHE_ENTRIES and ("n", 0) not in db._cache


def test_prior_period_books_still_carried(db, sample_files):
    """Earlier months' unpaired bills are still offered to a later month (now filtered in the database)."""
    c = ClientService(db).create(**CLIENT)
    svc = ImportService(db)
    for key, src in (("books_march", Source.BOOKS), ("books_april", Source.BOOKS),
                     ("gstr2b_april_json", Source.GSTR2B)):
        svc.import_file(c.id, sample_files[key], src)
    rec = ReconciliationService(db)
    lines = rec.load(rec.run(c.id, "2025-04")).result.lines
    assert any(ln.books and ln.books.is_prior_period for ln in lines)
    assert D(0) is not None
