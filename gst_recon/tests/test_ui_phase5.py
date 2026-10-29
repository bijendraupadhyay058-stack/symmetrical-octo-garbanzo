"""Desktop UI for Phase 5: Table 8A on the annual tab, returns calendar, web upload switch."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_table8a_calendar_and_upload_switch(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.go("returns")
    rp = win.pages["returns"]
    assert rp.import_8a_btn.isEnabled()
    assert rp.import_8a_path(sample_files["gstr8a_json"]) is not None
    assert "Table 8A document details" in rp.t8_note.text()
    rp.reconcile_8a()
    assert win.state.run_context().run.comparison == "BOOKS_VS_GSTR8A"
    assert win.stack.currentWidget() is win.pages["exceptions"]

    win.go("compliance")
    cp = win.pages["compliance"]
    cp.x_type.setCurrentText("GSTR-3B")
    cp.x_period.setText(f"{date.today():%Y-%m}")
    cp.x_ref.setText("Notif. 1/2099-CT")
    cp.add_extension()
    assert cp.x_model.rowCount() == 1 and cp.x_model.rows[0][4] == "Notif. 1/2099-CT"
    cp.days.setValue(60)
    assert any(r[6] == "Notif. 1/2099-CT" for r in cp.u_model.rows)
    cp.x_tbl.selectRow(0)
    cp.delete_extension()
    assert cp.x_model.rowCount() == 0

    win.go("sync")
    sp = win.pages["sync"]
    assert not sp.uploads_cb.isChecked()
    sp.uploads_cb.setChecked(True)
    assert win.state.security.setting("web_uploads") is True
