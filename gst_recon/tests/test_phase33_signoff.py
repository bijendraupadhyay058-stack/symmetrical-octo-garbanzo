"""Preparer – reviewer sign-off: four eyes, fingerprint goes out of date when the data changes."""
from datetime import date

import pytest

from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import PermissionDenied, Session
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.doc_checks import DocCheckService
from fintax_gst.services.signoff import AREAS, SignOffService

from .test_phase32 import SUP, add_docs

FY = "2025-26"
PREP = Session("asha", "accountant")
REV = Session("partner", "manager")


def test_signoff_cycle(db, tmp_path):
    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [("BOOKS", SUP, "INV", "X1", date(2025, 5, 2), "2025-05", 1000, 180, ""),
                        ("BOOKS", SUP, "INV", "X1", date(2025, 5, 2), "2025-05", 1000, 180, "")])
    svc = SignOffService(db)
    st = {x.area: x for x in svc.status(c.id, FY)}
    assert set(st) == set(AREAS) and st["doc_checks"].state == "not_prepared"
    with pytest.raises(ServiceError, match="not been marked as prepared"):
        svc.review(c.id, FY, "doc_checks", REV)
    with pytest.raises(PermissionDenied):
        svc.prepare(c.id, FY, "doc_checks", Session("v", "viewer"))
    svc.prepare(c.id, FY, "doc_checks", PREP, "duplicates checked")
    assert {x.area: x for x in svc.status(c.id, FY)}["doc_checks"].state == "prepared"
    with pytest.raises(ServiceError, match="cannot review their own"):
        svc.review(c.id, FY, "doc_checks", Session("asha", "manager"))
    with pytest.raises(PermissionDenied):
        svc.review(c.id, FY, "doc_checks", Session("other", "accountant"))
    svc.review(c.id, FY, "doc_checks", REV, "ok")
    st = {x.area: x for x in svc.status(c.id, FY)}
    assert st["doc_checks"].state == "reviewed" and st["doc_checks"].row.reviewed_by == "partner"
    assert st["recon"].state == "not_prepared"
    # a review mark changes the data of the duplicates working → out of date
    dc = DocCheckService(db)
    f = dc.check(c.id, FY).duplicates[0]
    dc.mark(c.id, f, "confirmed", "remove", "asha")
    st = {x.area: x for x in svc.status(c.id, FY)}
    assert st["doc_checks"].state == "changed" and "after review" in st["doc_checks"].label
    # an unrelated area's data does not affect it; a new import does
    svc.prepare(c.id, FY, "rule37a", PREP)
    add_docs(db, c.id, [("BOOKS", SUP, "INV", "X2", date(2025, 6, 2), "2025-06", 1000, 180, "")])
    st = {x.area: x for x in svc.status(c.id, FY)}
    assert st["rule37a"].state == "prepared"
    svc.prepare(c.id, FY, "doc_checks", PREP, "again")
    add_docs(db, c.id, [("BOOKS", SUP, "INV", "X3", date(2025, 6, 2), "2025-06", 1000, 180, "")])
    with pytest.raises(ServiceError, match="changed since it was prepared"):
        svc.review(c.id, FY, "doc_checks", REV)
    with pytest.raises(ServiceError, match="reason"):
        svc.reopen(c.id, FY, "doc_checks", PREP, "")
    svc.reopen(c.id, FY, "doc_checks", PREP, "redo")
    assert {x.area: x for x in svc.status(c.id, FY)}["doc_checks"].state == "not_prepared"
    out = svc.export_xlsx(c.id, FY, tmp_path / "s.xlsx")
    from openpyxl import load_workbook

    ws = load_workbook(out).active
    assert ws.cell(3, 1).value == AREAS["recon"] and ws.max_row == 2 + len(AREAS)


def test_every_area_fingerprints(db):
    c = ClientService(db).create(**CLIENT)
    svc = SignOffService(db)
    prints = {a: svc.fingerprint(c.id, FY, a) for a in AREAS}
    assert len(set(prints.values())) == len(AREAS)
    assert prints == {a: svc.fingerprint(c.id, FY, a) for a in AREAS}  # stable
