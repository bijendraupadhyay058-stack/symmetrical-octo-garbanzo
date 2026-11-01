"""Desktop UI: Return preparation."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_return_prep_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("returnprep")
    page = win.pages["returnprep"]
    page.kind.setCurrentIndex(page.kind.findData("GSTR3B"))
    page.period.setText("2025-04")
    page.refresh()
    assert page.prep is not None and page.c_model.rowCount() >= 3 and page.f_model.rowCount() > 5
    assert "no file upload" in page.how.text()
    files = page.make_files(str(tmp_path / "3b"))
    assert files and all(f.exists() for f in files)
    assert page.mark_final() is not None and ": final" in page.status.text()
    assert page.reopen() and page.prep.final is None
    page.kind.setCurrentIndex(page.kind.findData("GSTR9"))
    assert page.period.text() == "2025-26"
    page.refresh()
    assert page.prep.kind == "GSTR9" and "offline tool" in page.how.text()
    page.kind.setCurrentIndex(page.kind.findData("GSTR1"))
    page.period.setText("2025-04")
    page.refresh()
    assert "not ready" in page.status.text()  # _load imports no sales register
