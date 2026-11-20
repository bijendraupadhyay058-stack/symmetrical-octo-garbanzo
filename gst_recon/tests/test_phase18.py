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


# ------------------------------------------------------------------ charts and MIS (18C)
def test_mis_figures_and_pack(db, sample_files, tmp_path):
    from openpyxl import load_workbook
    from pypdf import PdfReader

    from fintax_gst.services.mis import MisService

    c, _inward, _outward = _full(db, sample_files)
    svc = MisService(db)
    mis = svc.build(c.id, "2025-26", date(2025, 5, 25))
    assert len(mis.months) == 12 and [m.period for m in mis.active] == ["2025-04"]
    april = mis.months[0]
    assert april.sales and april.sales > 0 and april.output_basis == "GSTR-3B"
    assert april.itc_books and april.itc_2b and april.itc_claimed is not None and april.cash_paid is not None
    assert mis.months[5].sales is None  # no data: blank, not zero
    assert mis.suppliers and all(a > 0 for _n, _g, a, _d in mis.suppliers)
    assert mis.suppliers == sorted(mis.suppliers, key=lambda x: x[2], reverse=True)
    pdf = svc.export_pdf(mis, tmp_path / "mis.pdf", "Sharma & Co")
    text = "".join(p.extract_text() for p in PdfReader(str(pdf)).pages)
    assert "GST MIS – 2025-26" in text and "ITC by month" in text and "Suppliers with the most ITC at risk" in text
    xl = svc.export_xlsx(mis, tmp_path / "mis.xlsx")
    wb = load_workbook(xl)
    ws = wb["Monthly"]
    assert ws["A3"].value == "Apr-25" and ws["A4"].value == "Total" and len(ws._charts) == 3
    assert wb["Supplier risk"].max_row == len(mis.suppliers) + 1


# ------------------------------------------------------------------ firm billing and staff tasks (18D)
def test_fee_invoices_receipts_and_outstanding(db, tmp_path):
    from pypdf import PdfReader

    from fintax_gst.samples import CLIENT, gstin
    from fintax_gst.services.billing import BillingService, FirmProfile
    from fintax_gst.services.clients import ClientService

    cs = ClientService(db)
    mh = cs.create(**CLIENT)  # Maharashtra
    ka = cs.create(**{**CLIENT, "gstin": gstin("29", "AACCV5566C"), "name": "Venkatesh Traders",
                      "state_code": "29"})
    svc = BillingService(db)
    with pytest.raises(ServiceError, match="firm profile"):
        svc.create_invoice(mh.id, [("GST returns", "5000")], ADMIN)
    with pytest.raises(ServiceError):
        svc.save_profile(FirmProfile(name="Sharma & Co", gstin="27AAAAA0000A1Z0"), ADMIN)  # bad check digit
    svc.save_profile(FirmProfile(name="Sharma & Co", address="Pune", gstin=gstin("27", "AAKFS1234P"),
                                 bank="HDFC Bank A/c 123 IFSC HDFC0000001"), ADMIN)
    assert svc.profile().state_code == "27" and svc.profile().pan == "AAKFS1234P"
    a = svc.create_invoice(mh.id, [("GST returns – April 2025", "5,000"), ("GSTR-2B reconciliation", "2500.50")],
                           ADMIN, date(2025, 5, 2))
    assert a.number == "FTP/2025-26/0001" and a.taxable == D("7500.50")
    assert (a.cgst, a.sgst, a.igst, a.total) == (D("675.05"), D("675.05"), D(0), D("8850.60"))
    b = svc.create_invoice(ka.id, [("GST returns", "10000")], ADMIN, date(2025, 5, 3))
    assert b.number == "FTP/2025-26/0002" and b.igst == D(1800) and b.total == D(11800)
    c = svc.create_invoice(mh.id, [("Annual return", "1000")], ADMIN, date(2026, 4, 2))
    assert c.number == "FTP/2026-27/0001"  # numbering restarts with the year
    with pytest.raises(ServiceError):
        svc.create_invoice(mh.id, [("", "100")], ADMIN)
    with pytest.raises(ServiceError):
        svc.create_invoice(mh.id, [("Fees", "100")], VIEWER)
    # receipts with TDS; outstanding by client, oldest unpaid first
    svc.record_receipt(mh.id, "7965.55", date(2025, 5, 20), ADMIN, "UPI", "UTR1", tds="885.05", invoice_id=a.id)
    svc.record_receipt(ka.id, "5000", date(2025, 5, 25), ADMIN, "Bank transfer", invoice_id=b.id)
    with pytest.raises(ServiceError, match="not this client's"):
        svc.record_receipt(mh.id, "1", date(2025, 5, 25), ADMIN, invoice_id=b.id)
    out = {o.name: o for o in svc.outstanding()}
    assert out[CLIENT["name"]].balance == D(1180) and out[CLIENT["name"]].oldest_due == c.due_date
    assert out["Venkatesh Traders"].balance == D(6800) and out["Venkatesh Traders"].overdue_days(date(2025, 6, 1)) == 14
    views = {v.inv.number: v for v in svc.invoices()}
    assert views["FTP/2025-26/0001"].balance == 0 and views["FTP/2025-26/0002"].balance == D(6800)
    with pytest.raises(ServiceError, match="receipts"):
        svc.cancel_invoice(b.id, "wrong client", ADMIN)
    svc.cancel_invoice(c.id, "raised twice", ADMIN)
    assert {o.name: o for o in svc.outstanding()}[CLIENT["name"]].balance == 0
    pdf = svc.invoice_pdf(a.id, tmp_path / "a.pdf")
    text = PdfReader(str(pdf)).pages[0].extract_text()
    assert "TAX INVOICE" in text and "FTP/2025-26/0001" in text and "8,850.60" in text
    assert "Eight Thousand Eight Hundred Fifty and Sixty Paise" in text
    # an unregistered firm issues a bill of supply without GST
    svc.save_profile(FirmProfile(name="Sharma & Co", prefix="SC"), ADMIN)
    d = svc.create_invoice(mh.id, [("Fees", "3000")], ADMIN, date(2025, 6, 1))
    assert d.number == "SC/2025-26/0001" and d.total == D(3000) and d.cgst == 0
    assert "BILL OF SUPPLY" in PdfReader(str(svc.invoice_pdf(d.id, tmp_path / "d.pdf"))).pages[0].extract_text()


def test_staff_tasks_from_due_dates(db):
    from fintax_gst.samples import CLIENT
    from fintax_gst.services.clients import ClientService
    from fintax_gst.services.tasks import TaskService

    cs = ClientService(db)
    c = cs.create(**CLIENT)
    cs.update(c.id, "admin", staff="priya")
    svc = TaskService(db)
    created, closed = svc.return_tasks("2025-04", "admin")
    assert created == 2 and closed == 0
    assert svc.return_tasks("2025-04", "admin") == (0, 0)  # never twice
    tasks = svc.tasks("priya")
    assert [t.task.title for t in tasks] == ["File GSTR-1 – April 2025", "File GSTR-3B – April 2025"]
    assert tasks[0].task.due_date == date(2025, 5, 11) and tasks[0].state(date(2025, 5, 12)) == "Overdue"
    manual = svc.add("Reply to ASMT-10", "admin", "rahul", date(2025, 5, 30), c.id)
    assert "rahul" in svc.assignees() and "priya" in svc.assignees()
    from fintax_gst.db.models import ReturnFiling

    with db.session() as s:
        s.add(ReturnFiling(client_id=c.id, return_type="GSTR-1", period="2025-04", filed_on=date(2025, 5, 10)))
    open_titles = [t.task.title for t in svc.tasks()]
    assert "File GSTR-1 – April 2025" not in open_titles and "Reply to ASMT-10" in open_titles
    done = [t for t in svc.tasks(include_done=True) if t.task.status == "done"]
    assert done[0].task.done_by == "filing recorded"
    assert svc.set_status([manual.id], True, "rahul") == 1 and svc.set_status([manual.id], True, "rahul") == 0
    assert svc.reassign([manual.id], "priya", "admin") == 1
    assert svc.delete([manual.id], "admin") == 1
