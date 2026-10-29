"""Desktop UI for Phase 4: Sales & GSTR-1, compliance, letters & working papers, sync & web."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import zipfile  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QFileDialog, QInputDialog  # noqa: E402

from fintax_gst.core.models import Source  # noqa: E402
from fintax_gst.services.auth import SETUP_SESSION, Session  # noqa: E402
from fintax_gst.services.sync import SyncService  # noqa: E402
from fintax_gst.ui import import_flow  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_outward_page_reconciles_and_shows_liability(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.go("outward")
    page = win.pages["outward"]
    page.from_cb.setCurrentText("2025-04")
    page.to_cb.setCurrentText("2025-04")
    for key, src in (("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1)):
        assert import_flow.import_interactive(page, win.state, sample_files[key], src) is not None
    page.reload()
    assert "sales register document(s)" in page.status_lbl.text()
    page.reconcile()
    run = win.state.run_context().run
    assert run.comparison == "SALES_VS_GSTR1"
    page.reload()
    assert page.rows_model.rowCount() == 4
    assert any("short payment" in r[3] for r in page.find_model.rows)
    assert page.cards["gap"].value.text() != "–"
    page.open_exceptions()
    assert win.stack.currentWidget() is win.pages["exceptions"]


def test_compliance_letters_papers_and_sync_pages(qtbot, db, tmp_path, sample_files, messages,  # noqa: F811
                                                  monkeypatch):
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.go("compliance")
    comp = win.pages["compliance"]
    assert comp.c_model.rowCount() == 1 and comp.m_model.rowCount() == 12
    assert comp.m_model.rows[0][1] in ("Action required", "Attention")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "d.xlsx"), "")))
    comp.export_excel()
    assert (out / "d.xlsx").exists()

    win.go("letters")
    lp = win.pages["letters"]
    assert lp.l_model.rowCount() > 0 and lp.gen_btn.isEnabled()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    lp.fmt_eml.setChecked(False)
    lp.generate()
    assert list(out.rglob("*.docx")) and not list(out.rglob("*.eml"))
    lp.prepare()
    assert lp.w_model.rowCount() == 1
    wp = lp.w_model.payload[0]
    assert zipfile.is_zipfile(wp.package_path)
    lp.w_tbl.selectRow(0)
    lp.verify()
    assert "matches" in messages[-1]
    win.state.session = Session("reviewer", "manager", "R")  # a different person signs off
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("Checked", True)))
    lp.reload()
    lp.w_tbl.selectRow(0)
    lp.review()
    assert lp.w_model.rows[0][5] == "reviewer"

    win.state.session = SETUP_SESSION
    win.go("sync")
    sp = win.pages["sync"]
    sp.granted_by.setText("Proprietor")
    sp.evidence.setText("Consent 9")
    sp.authorise()
    assert sp.a_model.rows[0][1] == "Active"
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("a-long-password", True)))
    sp.export()
    assert list(out.glob("*.ftpsync"))
    assert SyncService(db).active_authorisation(win.state.client.id).expires_on > date.today() + timedelta(days=300)
