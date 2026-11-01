"""Desktop UI for Phase 21."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _window, messages  # noqa: E402,F401


def test_exports_and_scheme_tabs(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.set_client(st.clients.get(c.id))
    st.imports.import_file(c.id, sample_files["sales_april"], Source.SALES)
    st.set_fy("2025-26")
    win.go("returns")
    page = win.pages["returns"]
    ex = page.exports_tab
    ex.p_from.setText("2025-04")
    ex.p_to.setText("2025-04")
    ex.refresh()
    assert ex.model.rowCount() >= 1 and "export / SEZ invoice" in ex.info.text()
    assert ex.fill_refund() is not None and ex.fields["adjusted_total_turnover"].text()
    ex.fields["net_itc"].setText("10000")
    r = ex.work_out()
    assert r is not None and "Rule 89(4)" in ex.result_lbl.text()
    assert ex.export(str(tmp_path / "e.xlsx")).exists()
    sc = page.scheme_tab
    sc.period.setText("2025-04")
    assert sc.show_cmp08() is None and "composition dealer" in sc.c_info.text()
    sc.cat.setCurrentIndex(sc.cat.findData("trader"))
    sc.save_category()
    q = sc.show_cmp08()
    assert q is not None and sc.c_model.rowCount() == 3
    assert sc.show_gstr4() is not None and sc.c_model.rowCount() == 6
    assert sc.show_pmt06() is not None and "IFF" in sc.p_info.text()
