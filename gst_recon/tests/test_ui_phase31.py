"""Desktop UI: voucher-wise ledger split."""
import os
from decimal import Decimal as D

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _window, messages  # noqa: E402,F401


def test_split_ledger_by_vouchers(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    st.set_client(st.clients.create(**CLIENT))
    st.set_fy("2025-26")
    win.go("ledgers")
    page = win.pages["ledgers"]
    assert page.import_path(sample_files["trial_balance"])
    assert page.import_vouchers_path(sample_files["daybook_xml"]) and any("voucher line(s)" in m for m in messages)
    row = next(r for r in page.model.rows if r[0] == "Repairs & Maintenance")
    assert row[16].startswith("4 · ₹3,00,000")
    page.select_ledgers(["Repairs & Maintenance"])
    dlg = page.split(run=False)
    lines = {v.voucher_no: v.id for v in page.svc.voucher_lines(dlg.view.ledger.id)}
    assert dlg.from_vouchers([lines["P-101"], lines["P-188"]], "Repairs & maintenance", "services") == 0
    assert dlg.from_vouchers([lines["P-240"]], "Stores & spares", "inputs") == 1
    assert dlg.from_vouchers([lines["J-77"]], "Repairs & maintenance", "services") == 2
    parts = dlg.parts()
    assert [p.amount for p in parts] == [D(180000), D(100000), D(20000)]
    assert parts[0].gst_basis == "vouchers" and parts[0].cgst == D(16200) and parts[2].cgst is None
    for r in range(3):
        dlg._set(r, 4, "eligible")
    assert dlg.save()
    v = page.svc.view(dlg.view.ledger.id)
    assert v.state == "Approved" and len(v.splits) == 3
    # the vouchers are used: a new part finds none left
    page.reload()
    page.select_ledgers(["Repairs & Maintenance"])
    dlg = page.split(run=False)
    assert dlg.table.rowCount() == 3
    assert dlg.from_vouchers() is None and any("No vouchers of this ledger are free" in m for m in messages)
