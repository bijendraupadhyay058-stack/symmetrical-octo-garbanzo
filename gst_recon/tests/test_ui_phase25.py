"""Desktop UI: Return comparison."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_phase25 import write_gstr2a_json, write_gstr3b_pdf  # noqa: E402
from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_return_compare_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("returncompare")
    page = win.pages["returncompare"]
    tab = page.tabs_by_kind["3B_2B"]
    assert tab.m_model.rowCount() == 12 and tab.m_model.rows[0][1] == "Difference"
    assert tab.m_model.headers[2] == "GSTR-3B" and "₹2,000" in tab.kpi.text()
    assert tab.d_model.rowCount() >= 5 and tab.f_model.rowCount() >= 1
    assert page.a_model.rows[0][2].startswith("✔") and page.a_model.rows[0][3] == "–"  # 3B yes, 2A not yet
    write_gstr2a_json(tmp_path / "GSTR2A_042025.json")
    write_gstr3b_pdf(tmp_path / "GSTR3B_may.pdf")
    res = page.import_paths([tmp_path / "GSTR2A_042025.json"])
    assert res[0][1] and any("1 of 1 file(s) saved" in m for m in messages)
    assert page.a_model.rows[0][3].startswith("✔")
    docs = page.tabs_by_kind["2A_2B"]
    assert docs.doc_model.rowCount() >= 2 and all(r[0] != "Matched" for r in docs.doc_model.rows)
    docs.doc_filter.setCurrentIndex(docs.doc_filter.findData("all"))
    assert any(r[0] == "Matched" for r in docs.doc_model.rows)
    tab.show_month(1)
    assert tab.d_title.text() == "Breakdown of May-2025"
    out = page.export(str(tmp_path / "cmp.xlsx"), open_file=False)
    assert out.exists()
    # the GSTR-3B PDF of April (already imported as JSON for April) – a new file, so saved and superseding
    picked = page.pick_up(tmp_path)
    assert picked and all(ok for _n, ok, _m in picked)
    assert page.pick_up(tmp_path) == []
