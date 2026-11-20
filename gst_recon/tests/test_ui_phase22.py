"""Desktop UI for Phase 22."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_tax_audit_tab(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.state.set_fy("2025-26")
    win.go("returns")
    tab = win.pages["returns"].tax_audit_tab
    tab.total.setText("50,00,000")
    tab.save_total()
    assert tab.c44 is not None and tab.model.rowCount() > 0 and "50,00,000" in tab.summary.text()
    assert tab.b_model.rowCount() == 1
    tab.table.selectRow(0)
    assert tab.mark(True) == 1 and tab.c44.composition > 0
    assert tab.export(str(tmp_path / "c44.xlsx")).exists()


def test_litigation_page(qtbot, db, tmp_path, messages):  # noqa: F811
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.set_client(st.clients.get(c.id))
    win.go("litigation")
    page = win.pages["litigation"]
    case = page.new_case({"title": "ITC mismatch FY 2021-22", "stage": "ORDER", "form": "DRC-07",
                          "order_date": date.today(), "tax": "1000000", "interest": "0", "penalty": "100000"})
    assert case is not None and page.model.rowCount() == 1 and "pre-deposit" in page.alerts_lbl.text()
    page.table.selectRow(0)
    assert "pre-deposit" in page.info.text()
    assert page.add_event((date.today(), "note", "Client briefed")) is not None
    assert page.e_model.rowCount() == 2
    page.table.selectRow(0)
    assert page.change({"stage": "APPEAL", "appeal_filed_on": date.today(), "pre_deposit_paid": "100000"},
                       event="APL-01 filed").stage == "APPEAL"
    assert page.make_tasks() >= 0
    assert page.export(str(tmp_path / "cases.xlsx")).exists()
    page.table.selectRow(0)
    assert page.delete() and page.model.rowCount() == 0
