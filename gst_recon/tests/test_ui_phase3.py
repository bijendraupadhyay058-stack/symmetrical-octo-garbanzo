"""Desktop UI for Phase 3: login, roles, ITC review, GSTR-3B & annual, IMS and security pages."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QDialog, QMessageBox  # noqa: E402

from fintax_gst.core.models import Source  # noqa: E402
from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.auth import AuthService, Session  # noqa: E402
from fintax_gst.ui.app import MainWindow, create_app  # noqa: E402
from fintax_gst.ui.dialogs.import_preview import ImportPreviewDialog  # noqa: E402
from fintax_gst.ui.dialogs.login import LoginDialog  # noqa: E402
from fintax_gst.ui.state import AppState  # noqa: E402

AS_OF = (2025, 5, 15)


@pytest.fixture
def messages(monkeypatch):
    seen = []
    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(ImportPreviewDialog, "exec", lambda self: QDialog.Accepted)
    return seen


def _window(qtbot, db, tmp_path, session):
    create_app(["test"])
    state = AppState(db, session, QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat))
    win = MainWindow(state)
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    return win


def _load(win, files):
    st = win.state
    st.set_client(st.clients.create(**CLIENT))
    win.go("workflow")
    wf = win.pages["workflow"]
    wf.set_period("2025-04")
    for key, src in (("books_march", Source.BOOKS), ("books_april", Source.BOOKS),
                     ("gstr2b_april_json", Source.GSTR2B)):
        assert wf.import_path(files[key], src) is not None
    win.go("ims")
    assert win.pages["ims"].import_path(files["ims_april_json"]) is not None
    win.go("returns")
    assert win.pages["returns"].import_path(files["gstr3b_april_json"])
    win.go("workflow")
    wf.start()
    assert st.run_id is not None


def test_login_dialog_setup_then_login(qtbot, db):
    create_app(["test"])
    auth = AuthService(db)
    dlg = LoginDialog(None, auth)
    qtbot.addWidget(dlg)
    assert dlg.setup
    dlg.username.setText("admin")
    dlg.password.setText("Admin12345")
    dlg.confirm.setText("Mismatch99")
    dlg.submit()
    assert dlg.session is None and "match" in dlg.error.text()
    assert dlg.password.text() == ""  # cleared after a failed attempt
    dlg.password.setText("Admin12345")
    dlg.confirm.setText("Admin12345")
    dlg.submit()
    assert dlg.session.role == "admin"
    dlg2 = LoginDialog(None, auth)
    qtbot.addWidget(dlg2)
    assert not dlg2.setup
    dlg2.username.setText("admin")
    dlg2.password.setText("wrong-pass1")
    dlg2.submit()
    assert dlg2.session is None and "Invalid" in dlg2.error.text()
    dlg2.password.setText("Admin12345")
    dlg2.submit()
    assert dlg2.session.username == "admin"


def test_itc_returns_ims_pages(qtbot, db, tmp_path, sample_files, messages, monkeypatch):
    from PySide6.QtCore import QDate

    win = _window(qtbot, db, tmp_path, Session("ca", "admin", "CA Partner"))
    _load(win, sample_files)
    st = win.state

    win.go("itc")
    itc = win.pages["itc"]
    itc.as_of.setDate(QDate(*AS_OF))
    codes = {itc.flag_model.rows[i][3] for i in range(itc.flag_model.rowCount())}
    assert {"S17_5_B_I_FOOD", "RCM", "S16_2_AA", "IMS_REJECTED"} <= codes
    assert itc.cards["blocked_17_5"].value.text() == "₹ 1,440.00"
    # dismiss the food flag with a reason
    row = next(i for i in range(itc.flag_proxy.rowCount())
               if itc.flag_proxy.index(i, 3).data() == "S17_5_B_I_FOOD")
    itc.flags.selectRow(row)
    monkeypatch.setattr(itc, "ask", lambda *a, **k: "Supplies are raw material")
    itc.decide("DISMISSED")
    itc.open_only.setChecked(False)
    assert any(r[3] == "S17_5_B_I_FOOD" and r[5] == "DISMISSED" for r in itc.flag_model.rows)
    # claim everything eligible
    monkeypatch.setattr(itc, "ask", lambda *a, **k: "2025-04")
    itc.claim_all()
    assert itc.claim_model.rowCount() > 0 and any("Claimed" in m for m in messages)
    assert Decimal(itc.cards["claimed_register"].value.text().replace("₹ ", "").replace(",", "")) > 0
    # rules tab: disable a rule for this client
    itc.rules_table.selectRow(next(i for i, r in enumerate(itc.rules) if r.code == "RCM"))
    itc.r_enabled.setChecked(False)
    itc.save_rule()
    assert not next(r for r in st.itc.rules(st.client.id) if r.code == "RCM").enabled

    win.go("returns")
    ret = win.pages["returns"]
    ret.show_table4()
    assert any(r[1] == "4A5" and r[6] == 2000 for r in ret.t4_model.rows)
    assert any(r[1] == "Statutory" for r in ret.find_model.rows)
    assert ret.t8_cards["a"].value.text().startswith("₹")
    path = ret.export_annual(str(tmp_path / "annual"))
    assert path is not None and path.exists()

    win.go("ims")
    ims = win.pages["ims"]
    assert any(r[2] == "GCH-2201" and r[4] == "Rejected" for r in ims.model.rows)
    ims.attention.setChecked(True)
    assert all(r[8] in ("HIGH", "MEDIUM") for r in ims.model.rows)


def test_viewer_cannot_change_anything(qtbot, db, tmp_path, sample_files, messages):
    admin_win = _window(qtbot, db, tmp_path, Session("ca", "admin"))
    _load(admin_win, sample_files)
    win = _window(qtbot, db, tmp_path, Session("v", "viewer", "Viewer"))
    st = win.state
    st.set_client(st.clients.list()[0])
    win.go("workflow")
    wf = win.pages["workflow"]
    assert not wf.start_btn.isEnabled() and not wf.books_btn.isEnabled() and wf.export_btn.isEnabled()
    win.go("exceptions")
    ex = win.pages["exceptions"]
    ex.select_line(1)
    assert not ex.save_btn.isEnabled() and not ex.unmatch_btn.isEnabled()
    win.go("itc")
    assert not win.pages["itc"].claim_all_btn.isEnabled()
    win.go("security")
    sec = win.pages["security"]
    assert not sec.add_btn.isEnabled() and not sec.purge_btn.isEnabled() and not sec.restore_btn.isEnabled()


def test_security_page(qtbot, db, tmp_path, sample_files, messages, monkeypatch):
    auth = AuthService(db)
    auth.create_user("admin", "Admin12345", "admin")
    win = _window(qtbot, db, tmp_path, auth.login("admin", "Admin12345"))
    st = win.state
    st.set_client(st.clients.create(**CLIENT))
    win.go("security")
    sec = win.pages["security"]
    answers = iter(["asha", "Asha K", "Secret123"])
    monkeypatch.setattr(sec, "ask", lambda *a, **k: next(answers))
    monkeypatch.setattr(sec, "choose", lambda *a, **k: "accountant – Accountant")
    sec.add_user()
    assert any(r[0] == "asha" and r[2] == "Accountant" for r in sec.users_model.rows)
    out = sec.encrypted_backup(str(tmp_path / "b.ftpbk"), "Backup#2025")
    assert out.read_bytes().startswith(b"FTPBK1")
    sec.keep.setValue(5)
    sec.save_auto()
    assert st.security.setting("backup_keep") == 5
    assert sec.audit_model.rowCount() > 0
    monkeypatch.setattr(sec, "ask", lambda *a, **k: CLIENT["gstin"])
    sec.purge()
    assert st.client is None and st.clients.list() == []
