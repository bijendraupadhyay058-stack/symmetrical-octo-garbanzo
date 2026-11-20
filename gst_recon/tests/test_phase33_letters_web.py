"""Supplier letters from credit / debit note findings (Outbox drafts) and the Duplicates & notes web page."""
import re
from datetime import date

import pytest

from fintax_gst.samples import CLIENT
from fintax_gst.services.auth import SETUP_SESSION, AuthService, Session
from fintax_gst.services.clients import ClientService
from fintax_gst.services.common import ServiceError
from fintax_gst.services.doc_checks import DocCheckService
from fintax_gst.services.mailer import MailService

from .test_phase32 import CUST, SUP, SUP2, add_docs

FY = "2025-26"
ADMIN = Session("admin", "admin")


@pytest.fixture
def client(db):
    c = ClientService(db).create(**CLIENT)
    add_docs(db, c.id, [
        ("BOOKS", SUP, "INV", "INV-1", date(2025, 5, 2), "2025-05", 10000, 1800, ""),
        ("BOOKS", SUP, "INV", "INV-1", date(2025, 5, 2), "2025-05", 10000, 1800, ""),
        ("BOOKS", SUP, "CRN", "SCN-1", date(2025, 8, 1), "2025-08", 1000, 180, ""),  # no original
        ("BOOKS", SUP, "CRN", "SCN-2", date(2025, 8, 3), "2025-08", 500, 90, "ZZ-9"),  # original missing
        ("GSTR2B", SUP2, "CRN", "TCN-9", date(2025, 10, 3), "2025-10", 3000, 540, ""),  # not booked
        ("SALES", CUST, "CRN", "CN-4", date(2025, 5, 20), "2025-05", 100, 18, ""),  # customer side: no letter
    ])
    from fintax_gst.services.followup import VendorService

    VendorService(db).upsert(c.id, SUP, name="Supplier One", email="one@example.com")
    return c


def test_note_letters(db, client):
    svc = DocCheckService(db)
    items = svc.letter_items(client.id, FY)
    assert set(items) == {SUP, SUP2} and len(items[SUP]) == 2
    made, skipped, no_mail = svc.note_letters(client.id, FY, "asha", "R. Kulkarni")
    assert (made, skipped) == (2, 0) and len(no_mail) == 1
    drafts = {m.ref: m for m in MailService(db).drafts("draft", client.id)}
    one = drafts[f"notes {FY} {SUP}"]
    assert one.to_addr == "one@example.com" and one.status == "draft" and "SCN-1" in one.body and "ZZ-9" in one.body
    assert "original invoice number" in one.body and "R. Kulkarni" in one.body
    assert "send a copy" in drafts[f"notes {FY} {SUP2}"].body
    assert svc.note_letters(client.id, FY, "asha")[:2] == (0, 2)  # not duplicated
    # findings marked 'not an issue' get no letter
    f = next(x for x in svc.check(client.id, FY).notes if x.gstin == SUP2)
    svc.mark(client.id, f, "not_issue", "received by post", "asha")
    assert set(svc.letter_items(client.id, FY)) == {SUP}


def test_checks_web_page(db, client):
    from fastapi.testclient import TestClient

    from fintax_gst.web.app import create_app

    AuthService(db).create_user("admin", "Very#Strong123", "admin", by=SETUP_SESSION)
    AuthService(db).create_user("viewer1", "Very#Strong123", "viewer", by=ADMIN)
    tc = TestClient(create_app(db, secret=b"s" * 32))
    tc.post("/login", data={"username": "admin", "password": "Very#Strong123"})
    assert "Duplicates &amp; notes" in tc.get(f"/client/{client.id}?fy={FY}").text
    page = tc.get(f"/client/{client.id}/checks?fy={FY}").text
    assert "Same number twice in a month" in page and "Letters to 2 supplier(s)" in page
    csrf = re.search(r'name="csrf"\s+value="([0-9a-f]+)"', page).group(1)
    key = re.search(r'name="key"\s*value="([^"]+)"', page).group(1).replace("&amp;", "&").replace("&#34;", '"')
    assert tc.post(f"/client/{client.id}/checks/action", data={"csrf": "bad", "fy": FY, "action": "confirmed",
                                                               "area": "duplicate", "key": key}).status_code == 400
    r = tc.post(f"/client/{client.id}/checks/action", data={"csrf": csrf, "fy": FY, "action": "not_issue",
                                                           "area": "duplicate", "key": key, "note": ""})
    assert "Not saved" in r.text  # a reason is needed
    r = tc.post(f"/client/{client.id}/checks/action", data={"csrf": csrf, "fy": FY, "action": "confirmed",
                                                           "area": "duplicate", "key": key, "note": "remove"})
    assert "Confirmed:" in r.text
    assert DocCheckService(db).check(client.id, FY).duplicates[0].decision == "confirmed"
    r = tc.post(f"/client/{client.id}/checks/action", data={"csrf": csrf, "fy": FY, "action": "letters"})
    assert "2 letter(s) added to the Outbox" in r.text
    assert tc.post(f"/client/{client.id}/checks/action", data={"csrf": csrf, "fy": FY, "action": "confirmed",
                                                              "area": "duplicate", "key": "nope"}).status_code == 404
    tc.get("/logout")
    tc.cookies.clear()
    tc.post("/login", data={"username": "viewer1", "password": "Very#Strong123"})
    v = tc.get(f"/client/{client.id}/checks?fy={FY}&show=all").text
    assert "Not an issue</button>" not in v and "Letters to" not in v
    assert tc.post(f"/client/{client.id}/checks/action", data={"csrf": csrf, "fy": FY,
                                                              "action": "letters"}).status_code == 403
    with pytest.raises(ServiceError):
        DocCheckService(db).note_letters(client.id, "2019-20", "a")
