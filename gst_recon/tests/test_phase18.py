"""Phase 18: e-mail outbox, invoices from PDF, charts and MIS, firm billing and staff tasks."""
from datetime import date
from decimal import Decimal as D

import pytest

from fintax_gst.services.auth import Session
from fintax_gst.services.common import ServiceError

from .test_phase4 import _full

ADMIN = Session("admin", "admin", "Admin")
VIEWER = Session("viewer", "viewer", "Viewer")


class FakeSMTP:
    """Stands in for the mail server: records what would be sent."""

    sent: list = []
    logins: list = []
    fail_for: set = set()

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        import smtplib

        if password != "app-pass":
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        FakeSMTP.logins.append(user)

    def send_message(self, msg):
        import smtplib

        if any(a in msg["To"] for a in FakeSMTP.fail_for):
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})
        FakeSMTP.sent.append(msg)

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.fail_for = [], [], set()
    monkeypatch.setattr("fintax_gst.services.mailer.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("fintax_gst.services.mailer.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


# ------------------------------------------------------------------ e-mail (18A)
def test_mail_account_and_outbox(db, sample_files, smtp):
    import json

    from fintax_gst.db.models import AppSetting, ClientReminder
    from fintax_gst.services.followup import VendorService
    from fintax_gst.services.mailer import MailAccount, MailService

    c, inward, _outward = _full(db, sample_files)
    svc = MailService(db)
    acc = MailAccount("smtp.gmail.com", 587, "starttls", "firm@gmail.com", "firm@gmail.com", "Sharma & Co")
    with pytest.raises(ServiceError):
        svc.save_account(acc, "app-pass", VIEWER)
    svc.save_account(acc, "app-pass", ADMIN)
    with db.session() as s:
        stored = s.get(AppSetting, "mail_account").value_json
    assert "app-pass" not in stored and json.loads(stored)["password"]  # kept encrypted
    assert svc.has_saved_password() and "Connected" in svc.test_account()
    # supplier letters -> drafts with the PDF attached; a supplier without e-mail cannot be sent
    letters = svc.letters_to_drafts(inward, "CA Sharma", user="accountant")
    assert letters and all(m.kind == "supplier_letter" and m.attachments_json.endswith('.pdf"]') for m in letters)
    first = letters[0]
    VendorService(db).upsert(c.id, first.ref, "accountant", email="accounts@supplier.in")
    svc.update_draft(first.id, to_addr="accounts@supplier.in")
    nothing_yet = smtp.sent == []
    assert nothing_yet  # drafts are never sent by themselves
    sent, problems = svc.send([m.id for m in letters], ADMIN)
    assert sent == 1 and len(problems) == len(letters) - 1 and all("no recipient" in p for p in problems)
    msg = smtp.sent[0]
    assert msg["To"] == "accounts@supplier.in" and msg["From"] == "Sharma & Co <firm@gmail.com>"
    assert [p.get_filename() for p in msg.iter_attachments()][0].endswith(".pdf")
    assert {m.id for m in svc.drafts("sent")} == {first.id}
    # client report and reminder drafts; a refused address is marked failed and can be retried
    rep = svc.report_drafts("2025-04", [c.id], "Sharma & Co", user="accountant")[0]
    assert rep.subject.startswith("GST summary April 2025")
    svc.update_draft(rep.id, to_addr="owner@client.in, cfo@client.in")
    smtp.fail_for = {"owner@client.in"}
    sent, problems = svc.send([rep.id], ADMIN)
    assert sent == 0 and "no such user" in problems[0] and svc.drafts("failed")[0].id == rep.id
    smtp.fail_for = set()
    assert svc.send([rep.id], ADMIN)[0] == 1
    from fintax_gst.services.reminders import ClientRequest

    req = ClientRequest(c.id, c.name, "Mr Rao", "", "", "", "2025-05", documents=["Purchase register"])
    rem = svc.reminder_drafts([req], "Sharma & Co", "accountant")[0]
    assert "Purchase register" in rem.body
    svc.update_draft(rem.id, to_addr="owner@client.in")
    assert svc.send([rem.id], ADMIN)[0] == 1
    with db.session() as s:
        assert s.query(ClientReminder).filter_by(client_id=c.id, channel="email").count() == 1
    # bad address and cancel
    bad = svc.add_draft("other", "not-an-address", "x", "y", client_id=c.id)
    assert "not an e-mail address" in svc.problems(bad)[0]
    assert svc.cancel([bad.id]) == 1 and not any(m.id == bad.id for m in svc.drafts())
    with pytest.raises(ServiceError, match="Only drafts"):
        svc.update_draft(first.id, subject="changed after sending")
    # wrong password: nothing sent, drafts stay
    svc.save_account(acc, "", ADMIN)
    assert not svc.has_saved_password()
    d = svc.add_draft("other", "a@b.in", "x", "y")
    with pytest.raises(ServiceError, match="password"):
        svc.send([d.id], ADMIN, password="wrong")
    assert svc.send([d.id], ADMIN, password="app-pass")[0] == 1
