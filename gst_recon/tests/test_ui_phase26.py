"""Desktop UI: follow-up from the Return comparison and the Year on year page."""
import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_comparison_follow_up(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.services.reconciliation import ReconciliationService

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    ReconciliationService(db).run(st.client.id, "2025-04")
    win.go("returncompare")
    page = win.pages["returncompare"]
    page.tabs.setCurrentIndex(0)
    assert not page.reply_btn.isEnabled() and "open the GSTR-3B" in page.act_label.text()
    page.tabs.setCurrentWidget(page.tabs_by_kind["3B_2B"])
    assert page.letters_btn.isEnabled() and page.reply_btn.text() == "Reply draft DRC-01C…"
    files = page.supplier_letters(tmp_path / "letters", open_folder=False)
    assert files and any("letter(s) saved" in m for m in messages)
    path = page.reply_draft(tmp_path, reference="ZD99", open_file=False)
    assert path is not None and path.exists() and "DRC-01C" in path.name
    out = page.drc03(str(tmp_path / "drc03.xlsx"), date(2025, 7, 31), open_file=False)
    assert out is not None and out.exists() and any("Tax and interest" in m for m in messages)
    page.tabs.setCurrentWidget(page.tabs_by_kind["2A_2B"])
    assert not page.letters_btn.isEnabled() and not page.drc03_btn.isEnabled()
    assert page.drc03(str(tmp_path / "x.xlsx")) is None


def test_year_on_year_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("yoy")
    page = win.pages["yoy"]
    assert page.yoy is not None and page.yoy.years == ["2023-24", "2024-25", "2025-26"]
    assert page.s_model.rowCount() == 7 and page.s_model.headers[3] == "2025-26"
    assert page.m_model.rowCount() == 12 and page.m_model.rows[0][0] == "Apr"
    page.metric_cb.setCurrentIndex(page.metric_cb.findData("itc_books"))
    assert "ITC as per books" in page.m_title.text() and page.m_model.rows[11][2] is not None  # March 2025
    page.years.setCurrentIndex(page.years.findData(2))
    assert page.yoy.years == ["2024-25", "2025-26"] and page.sup_model.rowCount() >= 3
    out = page.export(str(tmp_path / "yoy.xlsx"), open_file=False)
    assert out.exists()
