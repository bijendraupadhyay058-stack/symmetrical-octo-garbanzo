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
