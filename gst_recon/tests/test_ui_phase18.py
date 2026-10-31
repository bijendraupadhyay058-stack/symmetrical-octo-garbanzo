"""Desktop UI for Phase 18."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_phase18 import FakeSMTP, smtp  # noqa: E402,F401
from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_outbox_email_flow(qtbot, db, tmp_path, sample_files, messages, smtp):  # noqa: F811
    from fintax_gst.services.mailer import MailAccount, MailService
    from fintax_gst.ui.dialogs.mail_account import MailAccountDialog

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    win.go("outbox")
    out = win.pages["outbox"]
    assert "No e-mail account" in out.account_lbl.text() and not out.send_btn.isEnabled()
    dlg = MailAccountDialog(win, st)
    qtbot.addWidget(dlg)
    dlg.preset.setCurrentIndex(dlg.preset.findData("Gmail / Google Workspace"))
    assert dlg.host.text() == "smtp.gmail.com" and dlg.port.value() == 587
    dlg.sender.setText("firm@gmail.com")
    dlg.password.setText("app-pass")
    assert dlg.test() and "Connected" in messages[-1]
    assert MailService(db).account() == MailAccount("smtp.gmail.com", 587, "starttls", "firm@gmail.com",
                                                    "firm@gmail.com", "", True)
    win.go("letters")
    drafts = win.pages["letters"].email_letters()
    assert drafts and win.stack.currentWidget() is out
    out.reload()
    assert out.model.rowCount() == len(drafts) and "0 ready" in out.info.text()
    out.table.selectRow(0)
    out.to.setText("accounts@supplier.in")
    assert out.save_mail()
    out.table.selectRow(0)
    assert out.to.text() == "accounts@supplier.in"
    sent, problems = out.send_selected()
    assert sent == 1 and not problems and smtp.sent[0]["To"] == "accounts@supplier.in"
    out.status_cb.setCurrentIndex(out.status_cb.findData("sent"))
    assert out.model.rowCount() == 1
    out.status_cb.setCurrentIndex(out.status_cb.findData("draft"))
    out.table.selectAll()
    assert out.cancel_selected() == len(drafts) - 1 and out.model.rowCount() == 0
    win.go("firm")
    firm = win.pages["firm"]
    firm.reload()
    assert firm.email_reports(all_clients=True)


def test_invoices_from_pdf_on_reconcile_page(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    from fintax_gst.samples import CLIENT
    from fintax_gst.ui.dialogs.pdf_invoices import PdfInvoicesDialog

    from .test_phase18 import _invoice_pdfs

    checked = []

    def fix_and_accept(self):
        checked.append(self)
        bad_row = next(r for r, i in enumerate(self.invoices) if i.file.name == "mismatch.pdf")
        self.grid.item(bad_row, 10).setText("1180")  # correct the total
        self.accept()
        return 1

    monkeypatch.setattr(PdfInvoicesDialog, "exec", fix_and_accept)
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.set_client(st.clients.get(c.id))
    win.go("workflow")
    wf = win.pages["workflow"]
    wf.set_period("2025-04")
    _s1, _s2, files = _invoice_pdfs(tmp_path, c.gstin)
    sf = wf.import_pdfs([str(f) for f in files])
    assert sf is not None and sf.documents_imported == 3
    dlg = checked[0]
    assert "2 " not in dlg.summary.text() and dlg.summary.text().startswith("3 of 4")
    bad = next(i for i in dlg.invoices if i.file.name == "mismatch.pdf")
    assert not bad.problems()


def test_charts_and_mis_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("mis")
    page = win.pages["mis"]
    page.reload()
    assert page.mis is not None and len(page.charts) >= 3 and "Sales" in page.kpi.text()
    assert page.export("pdf", str(tmp_path / "m.pdf"), open_file=False).exists()
    assert page.export("xlsx", str(tmp_path / "m.xlsx"), open_file=False).exists()
    m = page.email()
    assert m.kind == "client_report" and m.subject.startswith("GST MIS 2025-26")
    assert win.stack.currentWidget() is win.pages["outbox"]
    win.go("mis")
    win.grab().save(str(tmp_path / "mis.png"))
    import shutil

    shutil.copy(tmp_path / "mis.png", "/tmp/claude-0/mis/app.png") if os.path.isdir("/tmp/claude-0/mis") else None
