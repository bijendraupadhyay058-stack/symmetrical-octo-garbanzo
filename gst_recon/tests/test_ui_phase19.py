"""Desktop UI for Phase 19."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from PySide6.QtCore import QDate  # noqa: E402

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_claim_plan_tab(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.itc.claim_plan import CLAIM, HOLD, WRITTEN_OFF

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.go("itc")
    page = win.pages["itc"]
    page.as_of.setDate(QDate(2025, 5, 15))
    tab = page.plan_tab
    tab.period.setText("2025-04")
    tab.refresh()
    assert tab.plan.bucket(CLAIM) and "Claim now" in tab.summary.text()
    n = len(tab.plan.bucket(CLAIM))
    res = tab.claim_all()
    assert len(res.claimed) == n and not tab.plan.bucket(CLAIM)
    hold_row = next(r for r, ln in enumerate(tab.model.payload) if ln.bucket == HOLD)
    tab.table.selectRow(tab.table.model().mapFromSource(tab.model.index(hold_row, 0)).row())
    assert tab.write_off("supplier closed") == 1 and tab.plan.bucket(WRITTEN_OFF)
    tab.only_open.setChecked(False)
    off_row = next(r for r, ln in enumerate(tab.model.payload) if ln.bucket == WRITTEN_OFF)
    tab.table.selectRow(tab.table.model().mapFromSource(tab.model.index(off_row, 0)).row())
    assert tab.undo() == 1
    assert tab.export(str(tmp_path / "p.xlsx")).exists()


def test_year_end_pack_button(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.state.set_fy("2025-26")
    win.go("returns")
    pdf, xlsx = win.pages["returns"].year_end_pack(str(tmp_path / "pack"), open_file=False)
    assert pdf.exists() and xlsx.exists() and "FY2025-26" in pdf.name
