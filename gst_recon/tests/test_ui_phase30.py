"""Desktop UI: propose claims, firm template in the mapping master, annual return pack."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_propose_claims_firm_template_and_annual_pack(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from PySide6.QtCore import Qt

    from fintax_gst.services.reconciliation import ReconciliationService

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    ReconciliationService(db).run(st.client.id, "2025-04")
    win.go("itcclass")
    page = win.pages["itcclass"]
    page.build()
    assert page.propose_claims(confirm=False) == 0
    n = page.propose_claims(confirm=True)
    assert n > 5
    page.view_cb.setCurrentIndex(page.view_cb.findData("all"))
    assert any(r[13].startswith("Claimed in GSTR-3B 2025-04") for r in page.model.rows)
    # firm template view
    win.go("mapmaster")
    mp = win.pages["mapmaster"]
    mp.scope.setCurrentIndex(mp.scope.findData("firm"))
    assert not mp.apply_btn.isEnabled() and "firm template" in mp.info.text()
    assert mp.add(("Audit Fees", "Legal & audit fees", "services", "regular", "14N", "eligible", "common"))
    assert mp.model.rowCount() == 1
    mp.scope.setCurrentIndex(mp.scope.findData("client"))
    assert mp.model.rowCount() == 0
    assert mp.add(("Freight Inward", "Freight & transportation", "services", "regular", "14B", "eligible", ""))
    mp.select_ledger("freight inward")
    assert mp.to_firm() == 1
    mp.scope.setCurrentIndex(mp.scope.findData("firm"))
    assert mp.model.rowCount() == 2
    # annual return pack
    win.go("annualpack")
    ap = win.pages["annualpack"]
    assert ap.clients.count() == 1
    assert ap.start() is None and any("Tick the clients" in m for m in messages)
    ap.check_all(True)
    assert ap.chosen() == [st.client.id]
    ap.folder.setText(str(tmp_path / "packs"))
    ap.pdf.setChecked(False)
    rows = ap.start()
    assert rows and rows[0].txns > 10 and ap.model.rowCount() == 1 and ap.open_btn.isEnabled()
    assert (tmp_path / "packs").exists() and any((tmp_path / "packs").glob("Annual_pack_2025-26_*.xlsx"))
    _ = Qt
