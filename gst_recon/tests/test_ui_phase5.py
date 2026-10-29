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


def test_gstr9_and_9c_tabs(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.core.models import Source

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    for key, src in (("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1),
                     ("gstr1_may_json", Source.GSTR1)):
        st.imports.import_file(st.client.id, sample_files[key], src)
    win.go("returns")
    rp = win.pages["returns"]
    rp.show_gstr9()
    codes = [r[0] for r in rp.g9_model.rows]
    assert codes[:2] == ["4A", "4B"] and "7J" in codes
    assert [r[0] for r in rp.g9_tax_model.rows] == ["IGST", "CGST", "SGST", "CESS"]
    rp.show_9c()
    five_a = next(r for r in rp.c9_model.rows if r[0] == "5A")
    assert five_a[3].startswith("default")
    rp.c9_item.setCurrentIndex(rp.c9_item.findData("5A"))
    rp.c9_amount.setText("8,00,000")
    rp.c9_note.setText("Audited accounts note 21")
    rp.save_9c_input()
    five_a = next(r for r in rp.c9_model.rows if r[0] == "5A")
    assert five_a[2] == __import__("decimal").Decimal("800000") and five_a[3] == "entered"
    rp.c9_item.setCurrentIndex(rp.c9_item.findData("5A"))
    rp.save_9c_input(clear=True)
    assert next(r for r in rp.c9_model.rows if r[0] == "5A")[3].startswith("default")
