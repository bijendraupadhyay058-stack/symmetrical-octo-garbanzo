"""Desktop UI: Ledger classification & bifurcation page and the split dialog."""
import os
from decimal import Decimal as D

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _window, messages  # noqa: E402,F401


def test_ledger_classification_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.core.models import Source

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    st.set_client(st.clients.create(**CLIENT))
    st.set_fy("2025-26")
    win.go("ledgers")
    page = win.pages["ledgers"]
    assert page.model.rowCount() == 0 and "Not ready" in page.ready.text()
    assert page.import_path(sample_files["trial_balance"]) and any("16 ledger(s) read" in m for m in messages)
    assert page.model.rowCount() == 7  # purchases, expenses, fixed assets
    page.filter.setCurrentIndex(page.filter.findData("all"))
    assert page.model.rowCount() == 16
    page.filter.setCurrentIndex(page.filter.findData("scope"))
    assert page.suggest() == 7 and all(r[14].startswith("Suggested") for r in page.model.rows)
    page.select_ledgers(["Salary", "Electricity Charges", "Professional Fees"])
    assert page.approve() == 3
    page.filter.setCurrentIndex(page.filter.findData("approved"))
    assert page.model.rowCount() == 3
    page.filter.setCurrentIndex(page.filter.findData("scope"))
    # bulk classification of two ledgers
    page.select_ledgers(["Freight Inward"])
    assert page.bulk(("Freight & transportation", "services", "rcm_reg", "14B", "eligible")) == 1
    # split the purchase ledger in the dialog: percentages, invoices and an approved apportionment
    from fintax_gst.services.imports import ImportService

    ImportService(db).import_file(st.client.id, sample_files["books_april"], Source.BOOKS)
    page.select_ledgers(["Purchase Account"])
    dlg = page.split(run=False)
    assert dlg.table.rowCount() == 1
    dlg.by_percent([D(80), D(20)])
    parts = dlg.parts()
    assert [p.amount for p in parts] == [D(2400000), D(600000)]
    dlg._set(0, 0, "Trading goods")
    dlg._set(1, 0, "Raw materials")
    dlg._set(1, 1, "inputs")
    assert dlg.apportion({"igst": D(0), "cgst": D(270000), "sgst": D(270000), "cess": D(0)}, approved=True)
    parts = dlg.parts()
    assert parts[0].cgst == D(216000) and parts[1].sgst == D(54000) and parts[0].gst_basis == "apportioned"
    assert "approved by" in parts[0].basis_note
    for r in range(2):
        dlg._set(r, 4, "eligible")
    assert dlg.save()
    v = page.svc.view(dlg.view.ledger.id)
    assert v.state == "Approved" and len(v.splits) == 2
    # a part from purchase-register invoices on another ledger
    page.select_ledgers(["Repairs & Maintenance"])
    dlg = page.split(run=False)
    inv = page.svc.invoices(st.client.id, "2025-26")
    r = dlg.from_invoices([inv[0]["id"]], "Stores & spares", "inputs")
    assert r == 1 and dlg.parts()[1].gst_basis == "invoices"
    dlg._set(0, 0, "Repairs & maintenance")
    dlg.fill_last()  # the remaining amount goes to the last part
    assert sum(p.amount for p in dlg.parts()) == D(300000)
    page.reload()
    # drill-down from the summary
    gst_row = next(i for i, p in enumerate(page.s_model.payload) if p == ("gst", "inputs"))
    page.drill(gst_row)
    assert {r[0] for r in page.model.rows} == {"Purchase Account"}
    # amount to classify for the fixed asset, reverse, exports
    page.filter.setCurrentIndex(page.filter.findData("asset"))
    page.select_ledgers(["Plant & Machinery"])
    assert page.set_base("450000", "Additions per fixed asset register")
    page.select_ledgers(["Plant & Machinery"])
    assert page.clear() == 1
    page.filter.setCurrentIndex(page.filter.findData("scope"))
    assert page.export("xlsx", str(tmp_path / "b.xlsx"), open_file=False).exists()
    assert page.export("pdf", str(tmp_path / "b.pdf"), open_file=False).exists()
    assert page.push_table14() == 0 and any("Not sent" in m for m in messages)
