"""Desktop UI for Phase 23."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_gstin_status_tab_and_health_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("suppliers")
    tab = win.pages["suppliers"].status_tab
    tab.refresh()
    assert tab.model.rowCount() > 0 and "not checked recently" in tab.info.text()
    first = tab.model.payload[0]
    assert tab.set_status({"gstin": first.gstin, "status": "Suspended"}) is not None
    assert "ITC at stake" in tab.info.text()
    out = tab.verify_list(str(tmp_path / "v.csv"))
    assert out.exists()
    win.go("health")
    page = win.pages["health"]
    page.reload()
    assert page.report is not None and "health score" in page.score.text()
    red = next(r for r, i in enumerate(page.model.payload) if i.area == "Suppliers" and i.severity == "red")
    page.table.selectRow(red)
    assert "Suspended" in page.examples.text() or "suspended" in page.examples.text()
    assert page.go_fix() == "suppliers" and win.stack.currentWidget() is win.pages["suppliers"]
    win.go("health")
    rows = page.check_all()
    assert rows and rows[0][0] == st.client.name
