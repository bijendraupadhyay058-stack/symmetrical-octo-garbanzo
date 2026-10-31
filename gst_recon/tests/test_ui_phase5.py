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


def test_reminders_page(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication

    from fintax_gst.samples import CLIENT

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    win.state.clients.create(**{**CLIENT, "mobile": "9820012345"})
    win.go("reminders")
    page = win.pages["reminders"]
    page.period.setText("2025-04")
    page.signature.setText("CA Office")
    page.reload()
    assert page.model.rowCount() == 1 and "Purchase register for April 2025" in page.text.toPlainText()
    page.show_message()
    assert page.text.toPlainText().endswith("CA Office")
    page.text.setPlainText(page.text.toPlainText() + "\nPS: edited")
    assert page.send("copy").endswith("PS: edited") and QApplication.clipboard().text().endswith("PS: edited")
    assert page.send("whatsapp").startswith("https://wa.me/919820012345") and opened
    assert page.model.rows[0][3] == 2


def test_firm_page_client_reports(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    from PySide6.QtGui import QDesktopServices

    from fintax_gst.samples import CLIENT, gstin

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    win.state.clients.create(**CLIENT)
    win.state.clients.create(gstin("29", "AACCB5678L"), None, name="Bangalore Electronics LLP")
    win.go("firm")
    page = win.pages["firm"]
    page.period.setText("2025-04")
    page.reload()
    paths = page.client_reports(str(tmp_path / "all"))
    assert len(paths) == 2 and not opened
    page.table.selectRow(0)
    one = page.client_reports(str(tmp_path / "one"))
    assert len(one) == 1 and len(opened) == 1


def test_security_cloud_copy(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    win.go("security")
    sec = win.pages["security"]
    sec.reload()
    assert sec.cloud_lbl.text() == "Off." and not sec.cloud_now_btn.isEnabled()
    folder = tmp_path / "GoogleDrive"
    folder.mkdir()
    assert sec.cloud_on(str(folder), "my backup pw 1")
    assert "First copy saved" in messages[-1] and len(list(folder.glob("*.ftpbk"))) == 1
    assert "On" in sec.cloud_lbl.text() and "OK" in sec.cloud_lbl.text() and sec.cloud_now_btn.isEnabled()
    assert sec.cloud_off() and sec.cloud_lbl.text() == "Off."


def test_workflow_tax_checks(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT, gstin
    from fintax_gst.ui.dialogs.tax_checks import TaxCheckDialog

    shown = []
    monkeypatch.setattr(TaxCheckDialog, "exec", lambda self: shown.append(self) or 0)
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    c = win.state.clients.create(**CLIENT)
    reg = tmp_path / "p.csv"
    reg.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,IGST\n{gstin('27', 'AABCM1234K')},IG-1,03-04-2025,"
                   "1000,180\n")
    win.state.imports.import_file(c.id, reg, Source.BOOKS)
    win.state.set_client(win.state.clients.get(c.id))
    win.go("workflow")
    wf = win.pages["workflow"]
    wf.set_period("2025-04")
    issues = wf.tax_checks()
    assert len(issues) == 1 and shown and shown[0].model.rowCount() == 1
    assert shown[0].export(str(tmp_path / "tc.xlsx")).exists()


def test_rule37_page(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from datetime import date as _date
    from decimal import Decimal

    from PySide6.QtCore import QDate

    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.imports.import_file(c.id, sample_files["books_april"], Source.BOOKS)
    st.set_client(st.clients.get(c.id))
    win.go("workflow")
    assert win.pages["workflow"].import_payments(str(sample_files["payments"])) is not None
    assert "4 payment(s) imported" in messages[-1] and "Contra" in messages[-1]
    win.go("rule37")
    page = win.pages["rule37"]
    page.as_of.setDate(QDate(2025, 11, 15))
    page.reload()
    assert "ITC to reverse: Rs." in page.summary.text() and page.model.rowCount() > 20
    page.filter.setCurrentText("Paid late – re-claim")
    assert page.model.rowCount() == 1
    page.filter.setCurrentText("Reverse ITC")
    page.table.selectRow(0)
    first = page.model.rows[0][3]
    assert page.mark_paid((_date(2025, 11, 14), Decimal("1"), "test"))  # part payment: still to reverse
    done, skipped = page.record_reversals()
    assert done == 0 and skipped  # nothing is recorded as claimed in the claim register
    assert page.export(str(tmp_path / "r37.xlsx")).exists()
    assert first


def test_pan_view_page(qtbot, db, tmp_path, messages):  # noqa: F811
    from fintax_gst.samples import CLIENT, gstin

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    st.clients.create(**CLIENT)
    st.clients.create(gstin("29", "AAPFU0939F"), None, name="Shree Ganesh Traders (Karnataka)")
    st.fy = "2025-26"
    win.go("pan")
    page = win.pages["pan"]
    page.reload()
    assert page.pan_cb.count() == 1 and page.model.rowCount() == 2 and "2 registration(s)" in page.summary.text()
    assert page.export(str(tmp_path / "pan.xlsx")).exists()
    page.table.selectRow(1)
    page.open_registration()
    assert st.client is not None and win.stack.currentWidget() is win.pages["dashboard"]


def test_tally_journal_dialog(qtbot, db, tmp_path, messages):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT, gstin

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    reg = tmp_path / "b.csv"
    reg.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n{gstin('27', 'AABCM1234K')},Z-1,"
                   "02-04-2025,1000,90,90\n")
    st.imports.import_file(c.id, reg, Source.BOOKS)
    st.set_client(st.clients.get(c.id))
    win.go("rule37")
    dlg = win.pages["rule37"].tally_journals(show=False)
    dlg.period.setText("2025-10")
    dlg.refresh()
    assert len(dlg.entries) == 1 and dlg.save_btn.isEnabled()
    dlg.ledger_edits["reversed"].setText("GST ITC Disallowed")
    dlg.save_ledgers()
    assert dlg.entries[0].lines[0][0] == "GST ITC Disallowed"
    assert dlg.save(str(tmp_path / "j.xml")).exists()
    win.go("itc")
    claims = win.pages["itc"].tally_journals(show=False)
    claims.period.setText("2025-10")
    claims.refresh()
    assert claims.entries == [] and "No reversal" in claims.info.text()


def test_errors_are_logged_and_shown(qtbot, tmp_path, messages, monkeypatch, caplog):  # noqa: F811
    import logging
    import sys

    from PySide6.QtWidgets import QMessageBox

    from fintax_gst.ui import crash

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    monkeypatch.setattr(crash, "_state", {"file": None, "showing": False, "shown": 0, "home": tmp_path})
    old_hook = sys.excepthook
    try:
        crash.install(tmp_path)
        with caplog.at_level(logging.ERROR):
            try:
                raise RuntimeError("boom in a button")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
        assert "boom in a button" in caplog.text and "Traceback" in caplog.text
        assert shown and "boom in a button" in shown[0] and "fintaxpro.log" in shown[0]
        for _ in range(5):  # a repeating error does not bury the window under messages
            crash.show_error(RuntimeError("again"))
        assert len(shown) == crash.MAX_DIALOGS
    finally:
        sys.excepthook = old_hook
        import faulthandler

        faulthandler.disable()
        if crash._state["file"]:
            crash._state["file"].close()
    (tmp_path / "crash.log").write_text("Fatal Python error: Segmentation fault")
    kept = crash.previous_crash(tmp_path)
    assert kept and kept.name.startswith("crash-") and not (tmp_path / "crash.log").exists()
    assert crash.previous_crash(tmp_path) is None  # reported once


def test_gstr1_json_dialog(qtbot, db, tmp_path, sample_files, messages):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.imports.import_file(c.id, sample_files["sales_april"], Source.SALES)
    st.fy = "2025-26"
    st.set_client(st.clients.get(c.id))
    win.go("outward")
    page = win.pages["outward"]
    page.from_cb.setCurrentText("2025-04")
    dlg = page.prepare_gstr1(show=False)
    assert dlg.sec_model.rowCount() >= 4 and dlg.save_btn.isEnabled() and "placed in GSTR-1" in dlg.info.text()
    assert dlg.save(str(tmp_path / "g1.json")).exists()


def test_gstr3b_draft_dialog(qtbot, db, tmp_path, sample_files, messages, monkeypatch):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.imports.import_file(c.id, sample_files["sales_april"], Source.SALES)
    st.fy = "2025-26"
    st.set_client(st.clients.get(c.id))
    win.go("returns")
    page = win.pages["returns"]
    page.from_cb.setCurrentText("2025-04")
    dlg = page.gstr3b_draft(show=False)
    assert "Cash to pay" in dlg.info.text() and dlg.pay_model.rowCount() == 5 and dlg.model.rowCount() >= 15
    assert dlg.save_pdf(str(tmp_path / "d.pdf"), open_file=False).exists()


def test_invoices_page(qtbot, db, tmp_path, messages):  # noqa: F811
    from datetime import date as _date
    from decimal import Decimal

    from fintax_gst.samples import CLIENT, gstin
    from fintax_gst.ui.pages.invoices import InvoiceDialog

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.set_client(st.clients.get(c.id))
    win.go("invoices")
    page = win.pages["invoices"]
    values = {"supplier_gstin": gstin("27", "AABCM1234K"), "supplier_name": "Mahalaxmi", "doc_type": "INV",
              "invoice_no": "M-1", "invoice_date": _date(2025, 4, 5), "taxable_value": Decimal("1000"),
              "cgst": Decimal("90"), "sgst": Decimal("90")}
    assert page.new(values) and page.model.rowCount() == 1 and "saved" in messages[-1]
    assert not page.new(values) and "already in the data" in messages[-1]
    page.table.selectRow(0)
    assert page.edit({"cgst": Decimal("95")}) and "not equal" in messages[-1]
    dlg = InvoiceDialog(page, page.source, {**values, "period": "2025-04"})  # the form round-trips the values
    v = dlg.values()
    assert v["invoice_no"] == "M-1" and v["taxable_value"] == Decimal("1000") and v["period"] == "2025-04"
    page.table.selectRow(0)
    assert page.delete() and page.model.rowCount() == 0


def test_earlier_years(qtbot, db, tmp_path, messages):  # noqa: F811
    import json as _json

    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT, gstin

    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    a = st.clients.create(**CLIENT)
    b = st.clients.create(gstin("29", "AACCB5678L"), None, name="Other", financial_year="2025-26")
    st.set_client(st.clients.get(a.id))
    years = [win.fy_cb.itemText(i) for i in range(win.fy_cb.count())]
    assert years[0] == "2017-18" and "2019-20" in years  # every year since GST began
    win.fy_cb.setCurrentText("2019-20")
    assert st.fy == "2019-20"
    st.set_client(st.clients.get(b.id))
    assert st.fy == "2019-20"  # the chosen year stays when another client is selected
    st.set_client(st.clients.get(a.id))
    g = gstin("27", "AABCM1234K")
    books = tmp_path / "b.csv"
    books.write_text(f"GSTIN,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n{g},OLD-1,05-06-2019,1000,90,90\n")
    two_b = tmp_path / "2b.json"
    two_b.write_text(_json.dumps({"data": {"gstin": CLIENT["gstin"], "rtnprd": "062019", "docdata": {"b2b": [
        {"ctin": g, "trdnm": "M", "inv": [{"inum": "OLD-1", "dt": "05-06-2019", "val": 1180, "typ": "R", "pos": "27",
                                           "rev": "N", "itcavl": "Y", "rsn": "", "items": [
                                               {"rt": 18, "txval": 1000, "igst": 0, "cgst": 90, "sgst": 90,
                                                "cess": 0}]}]}]}}}))
    st.imports.import_file(a.id, books, Source.BOOKS)
    st.imports.import_file(a.id, two_b, Source.GSTR2B)
    run = st.recon.run(a.id, "2019-06")
    ctx = st.recon.load(run)
    assert ctx.run.financial_year == "2019-20" and ctx.result.lines[0].category.value == "Fully Matched"


def test_replace_import_with_revised_file(qtbot, db, tmp_path, messages, monkeypatch):  # noqa: F811
    from fintax_gst.core.models import Source
    from fintax_gst.samples import CLIENT, gstin
    from fintax_gst.ui.dialogs.revision import RevisionDialog

    shown = []
    monkeypatch.setattr(RevisionDialog, "exec", lambda self: shown.append(self) or 1)
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    c = st.clients.create(**CLIENT)
    st.set_client(st.clients.get(c.id))
    g = gstin("27", "AABCM1234K")
    head = "GSTIN,Invoice No,Invoice Date,Taxable Value,CGST,SGST\n"
    old = tmp_path / "v1.csv"
    old.write_text(head + f"{g},A-1,02-04-2025,1000,90,90\n{g},A-2,03-04-2025,500,45,45\n")
    new = tmp_path / "v2.csv"
    new.write_text(head + f"{g},A-1,02-04-2025,1100,99,99\n{g},A-3,05-04-2025,700,63,63\n")
    st.imports.import_file(c.id, old, Source.BOOKS, period="2025-04")
    win.go("imports")
    page = win.pages["imports"]
    page.reload()
    page.table.selectRow(0)
    sf = page.replace(str(new))
    assert sf is not None and shown
    kinds = sorted(r[0] for r in shown[0].model.rows)
    assert kinds == ["Changed", "New", "No longer in the file"]
    assert "taxable: 1000 → 1100" in next(r[3] for r in shown[0].model.rows if r[0] == "Changed")
    assert [f.file_name for f in st.imports.list_files(c.id)] == ["v2.csv"]


def test_rule42_tab(qtbot, db, tmp_path, messages):  # noqa: F811
    from datetime import date as _date
    from decimal import Decimal

    from fintax_gst.services.batch import BatchService, write_example

    BatchService(db).run(write_example(tmp_path / "b"), create_clients=True)
    win = _window(qtbot, db, tmp_path, SETUP_SESSION)
    st = win.state
    st.fy = "2025-26"
    st.set_client(st.clients.list()[0])
    win.go("returns")
    tab = win.pages["returns"].rule42_tab
    tab.reload()
    tab.month.setCurrentText("2025-04")
    m = tab.show_month()
    assert m is not None and "save the month" in tab.result.rows[-1][1]
    tab.t["t4"].setText("10000")
    assert tab.save() and "save the month" not in tab.result.rows[-1][1]
    assert tab.add_good({"description": "Van", "invoice_no": "V1", "invoice_date": _date(2025, 4, 2),
                         "igst": Decimal(0), "cgst": Decimal("600"), "sgst": Decimal("600"), "cess": Decimal(0)})
    assert tab.goods.rowCount() == 1
    assert "FY 2025-26" in (tab.show_year() and tab.year_lbl.text())
    dlg = tab.journals(show=False)
    assert dlg.entries and dlg.source.currentData() == "rule42"
