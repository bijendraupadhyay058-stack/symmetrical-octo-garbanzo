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


# ------------------------------------------------------------------ invoices from PDF (18B)
def _pdf(path, lines):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for ln in lines:
        c.drawString(40, y, ln)
        y -= 16
    if not lines:
        c.rect(40, 400, 200, 200, fill=1)  # an "image" only, like a scan
    c.save()
    return path


def _invoice_pdfs(tmp_path, own):
    from fintax_gst.samples import gstin

    sup1, sup2 = gstin("27", "AABCM1234K"), gstin("29", "AAFFV5678Q")
    a = _pdf(tmp_path / "mahalaxmi_inv_0012.pdf", [
        "Mahalaxmi Steel Pvt Ltd", "TAX INVOICE  (Original for recipient)", f"GSTIN: {sup1}",
        "Invoice No: MSL/25-26/0012", "Invoice Date: 14-04-2025", f"Buyer GSTIN: {own}",
        "1  Steel sheets  7208  10 MT  9,000.00  90,000.00", "Taxable Value 90,000.00",
        "CGST @ 9% 8,100.00", "SGST @ 9% 8,100.00", "Grand Total 1,06,200.00",
        "Rupees One Lakh Six Thousand Two Hundred only"])
    b = _pdf(tmp_path / "venkatesh_b77.pdf", [
        "Venkatesh Traders", f"GSTIN {sup2}", "Bill No. B-77   Dated 02/04/2025", f"Bill to: GSTIN {own}",
        "Sub Total 25,000.00", "IGST 18% 4,500.00", "Invoice Value 29,500.00"])
    bad = _pdf(tmp_path / "mismatch.pdf", [
        "Some Supplier", f"GSTIN {sup2}", "Invoice No: X-1", "Invoice Date: 05-04-2025", f"GSTIN {own}",
        "Taxable Value 1,000.00", "IGST 18% 180.00", "Grand Total 1,500.00"])
    scan = _pdf(tmp_path / "scanned.pdf", [])
    return sup1, sup2, [a, b, bad, scan]


def test_pdf_invoices_into_purchase_register(db, tmp_path):
    from fintax_gst.samples import CLIENT
    from fintax_gst.services.clients import ClientService
    from fintax_gst.services.imports import ImportService
    from fintax_gst.services.pdf_invoices import PdfInvoiceService

    c = ClientService(db).create(**CLIENT)
    sup1, sup2, files = _invoice_pdfs(tmp_path, c.gstin)
    svc = PdfInvoiceService(db)
    a, b, bad, scan = svc.read(c.id, files)
    assert (a.supplier_gstin, a.invoice_no, a.invoice_date) == (sup1, "MSL/25-26/0012", date(2025, 4, 14))
    assert (a.taxable, a.cgst, a.sgst, a.igst, a.total) == (D(90000), D(8100), D(8100), D(0), D(106200))
    assert a.supplier_name == "Mahalaxmi Steel Pvt Ltd" and not a.problems()
    assert (b.supplier_gstin, b.invoice_no, b.invoice_date, b.taxable, b.igst) == (
        sup2, "B-77", date(2025, 4, 2), D(25000), D(4500))
    assert not b.problems()
    assert any("does not equal the total" in p for p in bad.problems())
    assert "scanned image" in scan.notes[0] and scan.problems()
    pv = svc.preview(c.id, [a, b, bad, scan], "2025-04")
    assert len(pv.records) == 3  # the scan is left out and listed
    assert any(i.severity == "ignored" and i.row == "scanned.pdf" for i in pv.issues)
    sf = ImportService(db).commit(c.id, pv, "accountant")
    assert sf.documents_imported == 3 and sf.file_name.startswith("PDF invoices (3)")
    assert svc.preview(c.id, [a, b, bad], "2025-04").already_imported_file_id == sf.id
