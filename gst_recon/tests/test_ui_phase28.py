"""Desktop UI: ITC classification & manual mapping."""
import os
from decimal import Decimal as D

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_itc_classification_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("itcclass")
    page = win.pages["itcclass"]
    assert page.import_tax_path(sample_files["tax_ledgers"]) and any("line(s) of" in m for m in messages)
    stats = page.build()
    assert stats["matched"] > 10 and stats["adjustments"] == 1
    n = page.model.rowCount()
    assert n > 20 and "Consolidate" in page.steps.text()
    page.view_cb.setCurrentIndex(page.view_cb.findData("adjust"))
    assert page.model.rowCount() == 1
    page.view_cb.setCurrentIndex(page.view_cb.findData("all"))
    # bulk: everything of one supplier as trading / eligible, for the selected only
    gstin = page.model.payload[0].txn.gstin
    k = page.select(lambda v: v.txn.gstin == gstin)
    assert page.classify({"nature": "trading", "status": "eligible", "scope": "", "reason": "bulk"}) == k
    page.find.setText(gstin)
    assert all(r[10] == "Trading purchase" and r[15] == "Manual" for r in page.model.rows)
    page.find.setText("")
    # a supplier rule for another supplier's transactions
    other = next(v for v in page.model.payload if v.txn.gstin and v.txn.gstin != gstin)
    page.select(lambda v: v.txn.id == other.txn.id)
    page.classify({"nature": "services", "status": "eligible", "scope": "gstin", "reason": "supplier gives services"})
    page.find.setText(other.txn.gstin)
    assert all(r[10] == "Input services" for r in page.model.rows) and page.model.rows[0][15] == "Rule"
    page.find.setText("")
    # split one invoice exactly, then undo
    v = next(x for x in page.model.payload if x.txn.taxable and x.txn.cgst and x.txn.taxable > 10000)
    page.select(lambda x: x.txn.id == v.txn.id)
    dlg = page.split(run=False)
    dlg.add_row()
    dlg.set_cell(0, 0, v.txn.taxable - 1000)
    dlg.set_cell(1, 0, D(1000))
    assert dlg.proportional()
    dlg.set_cell(1, 5, "capital")
    assert dlg.save()
    assert len(page.svc.view(v.txn.id).parts) == 2
    page.reload()
    page.select(lambda x: x.txn.id == v.txn.id)
    assert any("ITC_SPLIT" in line for line in page.history(show=False))
    assert page.undo() and len(page.svc.view(v.txn.id).parts) == 1
    # drill-down from the overview, finalise with a reason, exports
    row = next(i for i, p in enumerate(page.o_model.payload) if p == ("nature", "trading"))
    page.drill(row)
    assert page.model.rowCount() >= k
    assert page.finalise(note="reviewed", override="sample data")
    assert page.final_btn.text() == "Reopen"
    assert page.export("xlsx", str(tmp_path / "i.xlsx"), open_file=False).exists()
    assert page.export("pdf", str(tmp_path / "i.pdf"), open_file=False).exists()
    rules = page.rules(delete_id=page.svc.rules(st.client.id)[0].id)
    assert rules == []
