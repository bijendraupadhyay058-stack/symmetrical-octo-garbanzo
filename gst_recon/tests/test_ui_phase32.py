"""Desktop UI: duplicates & credit / debit note checks with review marks."""
import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_phase32 import CUST, SUP, add_docs  # noqa: E402
from .test_ui_phase3 import _window, messages  # noqa: E402,F401


def test_duplicates_and_notes_page(qtbot, db, tmp_path, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    add_docs(db, c.id, [
        ("BOOKS", SUP, "INV", "INV-101", date(2025, 5, 2), "2025-05", 10000, 1800, ""),
        ("BOOKS", SUP, "INV", "INV-101", date(2025, 5, 2), "2025-05", 10000, 1800, ""),
        ("SALES", CUST, "INV", "S-9", date(2025, 6, 1), "2025-06", 1000, 180, ""),
        ("SALES", CUST, "CRN", "CN-2", date(2025, 6, 20), "2025-06", 1500, 270, "S-9"),
    ])
    st.set_client(c)
    st.set_fy("2025-26")
    win.go("docchecks")
    page = win.pages["docchecks"]
    page.reload()
    assert page.models["duplicate"].rowCount() == 1
    assert page.models["note"].rows[0][3].startswith("Credit notes exceed invoice S-9")
    assert "1 to check" in page.summary.text()
    page.select("duplicate", 0)
    assert "INV-101" in page.detail.text()
    assert page.mark("not_issue", "two separate bills – copies checked")
    assert page.models["duplicate"].rows[0][6] == "Not an issue"
    page.hide_done.setChecked(True)
    assert page.models["duplicate"].rowCount() == 0
    page.select("note", 0)
    assert page.mark("confirmed", "")
    assert page.models["note"].rowCount() == 0
    page.hide_done.setChecked(False)
    page.src.setCurrentIndex(page.src.findData("BOOKS"))
    assert page.models["note"].rowCount() == 0 and page.models["duplicate"].rowCount() == 1
    out = page.export(str(tmp_path / "x.xlsx"), open_file=False)
    assert out.exists()
