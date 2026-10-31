"""Desktop UI for Phase 5: Table 8A on the annual tab, returns calendar, web upload switch."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("pytestqt")

from fintax_gst.services.auth import SETUP_SESSION  # noqa: E402

from .test_ui_phase3 import _load, _window, messages  # noqa: E402,F401


def test_table8a_calendar_and_upload_switch(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    win.go("returns")
    rp = win.pages["returns"]
    assert rp.import_8a_btn.isEnabled()
    assert rp.import_8a_path(sample_files["gstr8a_json"]) is not None
    assert "Table 8A document details" in rp.t8_note.text()
    rp.reconcile_8a()
    assert win.state.run_context().run.comparison == "BOOKS_VS_GSTR8A"
    assert win.stack.currentWidget() is win.pages["exceptions"]

    win.go("compliance")
    cp = win.pages["compliance"]
    cp.x_type.setCurrentText("GSTR-3B")
    cp.x_period.setText(f"{date.today():%Y-%m}")
    cp.x_ref.setText("Notif. 1/2099-CT")
    cp.add_extension()
    assert cp.x_model.rowCount() == 1 and cp.x_model.rows[0][4] == "Notif. 1/2099-CT"
    cp.days.setValue(60)
    assert any(r[6] == "Notif. 1/2099-CT" for r in cp.u_model.rows)
    cp.x_tbl.selectRow(0)
    cp.delete_extension()
    assert cp.x_model.rowCount() == 0

    win.go("sync")
    sp = win.pages["sync"]
    assert not sp.uploads_cb.isChecked()
    sp.uploads_cb.setChecked(True)
    assert win.state.security.setting("web_uploads") is True


def test_gstr9_and_9c_tabs(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.core.models import Source

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    _load(win, sample_files)
    st = win.state
    for key, src in (("sales_april", Source.SALES), ("gstr1_april_json", Source.GSTR1),
                     ("gstr1_may_json", Source.GSTR1)):
        st.imports.import_file(st.client.id, sample_files[key], src)
    win.go("returns")
    rp = win.pages["returns"]
    rp.show_gstr9()
    codes = [r[0] for r in rp.g9_model.rows]
    assert codes[:2] == ["4A", "4B"] and "7J" in codes
    assert [r[0] for r in rp.g9_tax_model.rows] == ["IGST", "CGST", "SGST", "CESS"]
    rp.show_9c()
    five_a = next(r for r in rp.c9_model.rows if r[0] == "5A")
    assert five_a[3].startswith("default")
    rp.c9_item.setCurrentIndex(rp.c9_item.findData("5A"))
    rp.c9_amount.setText("8,00,000")
    rp.c9_note.setText("Audited accounts note 21")
    rp.save_9c_input()
    five_a = next(r for r in rp.c9_model.rows if r[0] == "5A")
    assert five_a[2] == __import__("decimal").Decimal("800000") and five_a[3] == "entered"
    rp.c9_item.setCurrentIndex(rp.c9_item.findData("5A"))
    rp.save_9c_input(clear=True)
    assert next(r for r in rp.c9_model.rows if r[0] == "5A")[3].startswith("default")


def test_9c_expense_ledger_import(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    win.state.set_client(win.state.clients.create(**__import__("fintax_gst.samples", fromlist=["CLIENT"]).CLIENT))
    win.go("returns")
    rp = win.pages["returns"]
    assert rp.import_expense_path(sample_files["expense_ledger"])
    codes = {r[0]: r for r in rp.c9_model.rows}
    assert "14A" in codes and codes["14R"][2] > 0


def test_gstr9_entered_tables_via_desktop(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    win.state.set_client(win.state.clients.create(**CLIENT))
    win.go("returns")
    rp = win.pages["returns"]
    idx = rp.c9_item.findData("15E-I")
    assert idx >= 0 and "Total demand of taxes" in rp.c9_item.itemText(idx)
    rp.c9_item.setCurrentIndex(idx)
    rp.c9_amount.setText("25000")
    rp.c9_note.setText("DRC-07")
    rp.save_9c_input()
    rp.show_gstr9()
    assert any(r[0] == "15E" and r[3] == 25000 for r in rp.g9_model.rows)


def test_batch_page(qtbot, db, tmp_path, messages):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    win.go("batch")
    page = win.pages["batch"]
    root = page.make_example(str(tmp_path))
    assert root.is_dir() and page.folder.text() == str(root)
    page.create_clients.setChecked(True)
    page.start(dry_run=True)
    assert "nothing changed" in page.status.text() and "8 item(s)" in page.status.text()
    assert not win.state.clients.list()
    page.start(dry_run=False)
    assert "4 reconciliation(s)" in page.status.text() and page.open_btn.isEnabled()
    results = {page.model.rows[i][3] for i in range(page.model.rowCount())}
    assert {"Client added", "Imported", "Reconciled", "Report saved"} <= results
    assert len(win.state.clients.list()) == 1


def test_firm_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    st.clients.create(**CLIENT)
    win.go("firm")
    page = win.pages["firm"]
    page.period.setText("2025-04")
    page.reload()
    assert page.cards["Awaiting data"].value.text() == "1" and page.model.rowCount() == 1
    page.table.selectRow(0)
    assert page.set_staff("priya")
    assert page.model.rows[0][2] == "priya" and page.staff_cb.findText("priya") >= 0
    page.table.selectRow(0)
    assert page.record_filing(("GSTR-1", date(2025, 5, 10), "AA270525"))
    assert "GSTR-1: filed" in page.model.rows[0][7]
    assert page.export(str(tmp_path / "firm.xlsx")).exists()
    page.table.selectRow(0)
    page.open_client()
    assert st.client is not None and win.stack.currentWidget() is win.pages["workflow"]


def test_update_bar(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    from .test_phase13 import FakeReleasePage

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    page = FakeReleasePage()
    try:
        win = _window(qtbot, db, tmp_path, SETUP_SESSION)
        bar = win.update_bar
        bar.factory = page.service
        q = win.state.qsettings
        assert not bar.isVisible()
        t = bar.check_in_background(q)
        t.join(10)
        qtbot.waitUntil(bar.isVisible, timeout=5000)
        assert "99.0.0" in bar.text.text()
        assert bar.check_in_background(q) is None  # once a day only
        path = bar.download_and_install(tmp_path / "dl", launch=False)
        assert path.exists() and path.stat().st_size == page.size
        win.go("settings")
        settings = win.pages["settings"]
        settings.auto_update.setChecked(False)
        q.setValue("update_last_check", "")
        assert bar.check_in_background(q) is None  # switched off
        page.version = "0.0.1"
        assert settings.check_updates() is None and "latest version" in messages[-1]
    finally:
        page.server.shutdown()
