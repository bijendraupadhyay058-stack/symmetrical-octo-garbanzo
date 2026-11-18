"""Desktop UI: ITC claim recorded apart from the classification; Mapping master page."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_record_claim_and_mapping_master(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    st.set_fy("2025-26")
    win.go("itcclass")
    page = win.pages["itcclass"]
    page.build()
    v = next(x for x in page.model.payload if x.txn.invoice_id and x.txn.cgst)
    page.select(lambda x: x.txn.id == v.txn.id)
    page.classify({"nature": "capital", "status": "eligible", "scope": "", "reason": "machine"})
    page.find.setText(v.txn.invoice_no)
    row = page.model.rows[0]
    assert row[10] == "Capital goods" and row[12] == "Eligible" and row[13] == "Claim not verified"
    page.select(lambda x: x.txn.id == v.txn.id)
    assert page.record_claim("claimed", "2025-04", "GSTR-3B April") == 1
    row = page.model.rows[0]
    assert row[10] == "Capital goods" and row[13] == "Claimed in GSTR-3B 2025-04"
    page.find.setText("")
    page.view_cb.setCurrentIndex(page.view_cb.findData("unverified"))
    assert all(r[13] == "Claim not verified" for r in page.model.rows)
    page.view_cb.setCurrentIndex(page.view_cb.findData("all"))
    i = next(k for k, p in enumerate(page.o_model.payload) if p == ("claim", "claimed"))
    page.drill(i)
    assert page.model.rowCount() == 1
    assert page.reporting_note("FY 2025-26: Table 14 optional – Notification checked by partner").startswith("FY 2025-26")
    # Mapping master
    win.go("ledgers")
    assert win.pages["ledgers"].import_path(sample_files["trial_balance"])
    win.go("mapmaster")
    mp = win.pages["mapmaster"]
    assert mp.model.rowCount() == 0
    assert mp.add(("Professional Fees", "Professional & consultancy", "services", "regular", "14N", "eligible", ""))
    assert mp.add(("Purchase Account", "Trading goods", "inputs", "regular", "14A", "eligible", "goods for resale"))
    assert mp.model.rowCount() == 2 and mp.model.rows[0][10] == "2025-26"
    res = mp.apply()
    assert res["ledgers"] >= 2
    lv = {x.ledger.name: x for x in win.pages["ledgers"].svc.views(st.client.id, "2025-26")}
    assert lv["Purchase Account"].ledger.confidence == "saved"
    mp.select_ledger("purchase account")
    assert mp.toggle() == 1 and mp.model.payload[[e.m.ledger_key for e in mp.model.payload].index(
        "purchase account")].m.active is False
    out = mp.export(str(tmp_path / "m.xlsx"), open_file=False)
    first_id = st.client.id
    other = st.clients.create(**{**CLIENT, "name": "Group Co", "gstin": "27AAPFU0939F2ZU"})
    st.set_client(other)
    assert mp.import_path(out)[0] == 2
    assert mp.copy_from(first_id) == (0, 1)  # one active entry, already here
