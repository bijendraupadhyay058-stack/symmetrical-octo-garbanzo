"""Desktop UI tests (offscreen). They drive the real pages, workers and services."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QItemSelectionModel, QSettings  # noqa: E402
from PySide6.QtWidgets import QDialog, QMessageBox  # noqa: E402

from fintax_gst.core.models import Category, ExceptionStatus, Source  # noqa: E402
from fintax_gst.engine.summary import dashboard  # noqa: E402
from fintax_gst.samples import CLIENT  # noqa: E402
from fintax_gst.ui.app import MainWindow, create_app  # noqa: E402
from fintax_gst.ui.dialogs.client_form import ClientDialog  # noqa: E402
from fintax_gst.ui.dialogs.import_preview import ImportPreviewDialog  # noqa: E402
from fintax_gst.ui.dialogs.mapping import MappingDialog  # noqa: E402
from fintax_gst.ui.state import AppState  # noqa: E402
from fintax_gst.ui.theme import money  # noqa: E402
from fintax_gst.ui.widgets import OBJECT_ROLE  # noqa: E402
from fintax_gst.ui.workers import run_task  # noqa: E402

from .conftest import GSTIN_A  # noqa: E402


@pytest.fixture
def messages(monkeypatch):
    seen = []
    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    return seen


@pytest.fixture
def window(qtbot, db, tmp_path, messages):
    create_app(["test"])
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    state = AppState(db, "tester", settings)
    win = MainWindow(state)
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    return win


def _accept_previews(monkeypatch):
    monkeypatch.setattr(ImportPreviewDialog, "exec", lambda self: QDialog.Accepted)


def _setup_demo(window, sample_files, monkeypatch):
    dlg = ClientDialog(window, window.state.clients, "tester")
    dlg.gstin.setText(CLIENT["gstin"])
    dlg.name.setText(CLIENT["name"])
    dlg.fy.setText("2025-26")
    dlg._save()
    assert dlg.saved is not None
    window.state.set_client(window.state.clients.get(dlg.saved.id))
    _accept_previews(monkeypatch)
    window.go("workflow")
    wf = window.pages["workflow"]
    wf.set_period("2025-04")
    assert wf.import_path(sample_files["books_march"], Source.BOOKS, prior=True) is not None
    assert wf.import_path(sample_files["books_april"], Source.BOOKS) is not None
    assert wf.import_path(sample_files["gstr2b_april"], Source.GSTR2B) is not None
    return wf


def test_window_starts_on_empty_database(window):
    assert window.stack.currentWidget() is window.pages["clients"]
    assert window.pages["dashboard"].cards["itc_at_risk"].value.text() == "–"
    for key in ("dashboard", "workflow", "exceptions", "suppliers", "open_items", "history", "imports", "settings"):
        window.go(key)
        assert window.stack.currentWidget() is window.pages[key]


def test_client_dialog_validation(window, messages):
    dlg = ClientDialog(window, window.state.clients, "tester")
    dlg.gstin.setText("27AAPFU0939F1ZA")
    dlg.name.setText("X")
    dlg._save()
    assert dlg.saved is None and "check digit" in messages[-1]
    assert "check digit" in dlg.derived.text()


def test_full_workflow_through_the_ui(window, sample_files, monkeypatch, tmp_path, qtbot, messages):
    wf = _setup_demo(window, sample_files, monkeypatch)
    assert wf.s3.state_lbl.text() == "26 documents" and wf.s4.state_lbl.text() == "26 documents"
    assert wf.files_model.rowCount() == 2
    wf.date_tol.setValue(7)
    wf.start()
    st = window.state
    assert st.run_id is not None, messages
    lines = st.recon.load(st.run_id).result.lines
    d = dashboard(lines)

    # Dashboard cards show exactly the engine's figures.
    window.go("dashboard")
    dash = window.pages["dashboard"]
    assert dash.cards["itc_as_per_books"].value.text() == money(d["itc_as_per_books"], True)
    assert dash.cards["itc_at_risk"].value.text() == money(d["itc_at_risk"], True)
    assert dash.cards["pending_cases"].value.text() == str(d["pending_cases"])
    assert len(dash.chart_views) == 4
    window.go("workflow")
    assert "Run #" in wf.summary_lbl.text()

    # Exceptions: colour-coded category filters.
    window.go("exceptions")
    ex = window.pages["exceptions"]
    assert ex.model.rowCount() == len(lines)
    ex.chips.choose({Category.MISSING_IN_2B})
    assert ex.proxy.rowCount() == 2
    ex.chips.select_all()
    ex.search.setText("DOS-1189")
    assert ex.proxy.rowCount() == 1
    ex.search.setText("")

    # Confirm the probable match.
    monkeypatch.setattr(ex, "ask", lambda *_a: "Supplier confirmed typo")
    probable = next(ln for ln in lines if ln.books and ln.books.invoice_no == "DOS-1189")
    ex.select_line(probable.line_no)
    assert ex.current.line_no == probable.line_no and ex.confirm_btn.isEnabled()
    ex.confirm()
    assert ex.current.category == Category.MANUALLY_MATCHED

    # Manual match of two single-sided lines (Ctrl+click two rows).
    lines = st.recon.load(st.run_id).result.lines
    a = next(ln for ln in lines if ln.category == Category.MISSING_IN_2B and ln.books.invoice_no == "MSL/260/25-26")
    b = next(ln for ln in lines if ln.category == Category.MISSING_IN_BOOKS and ln.gstr2b.invoice_no == "OSL/377")
    sel = ex.table.selectionModel()
    ex.table.clearSelection()
    for r in range(ex.proxy.rowCount()):
        if ex.proxy.index(r, 0).data(OBJECT_ROLE).line_no in (a.line_no, b.line_no):
            sel.select(ex.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert len(ex.selected_lines()) == 2 and ex.match_btn.isEnabled()
    ex.manual_match()
    assert ex.current.category == Category.MANUALLY_MATCHED and ex.model.rowCount() == len(lines) - 1

    # Unmatch, then record a review.
    ex.unmatch()
    assert ex.current.category == Category.MISSING_IN_2B
    ex.status_edit.setCurrentText(ExceptionStatus.SUPPLIER_FOLLOWUP.value)
    ex.remarks.setPlainText("Mailed supplier")
    ex.assigned.setText("Asha")
    ex.action_set.setChecked(True)
    ex.save()
    assert ex.current.status == ExceptionStatus.SUPPLIER_FOLLOWUP and ex.current.assigned_to == "Asha"
    assert ex.history.count() >= 1

    # Evidence.
    evidence = tmp_path / "reply.pdf"
    evidence.write_bytes(b"%PDF evidence")
    ex.attach(evidence, "supplier reply")
    assert ex.evidence.count() == 1

    # Suppliers: drill-down and vendor follow-up register.
    window.go("suppliers")
    sp = window.pages["suppliers"]
    sp.table.selectRow(0)
    gstin = sp.gstin
    assert gstin and sp.lines_proxy.rowCount() >= 1
    assert all(ln.supplier_gstin == gstin or (ln.gstr2b and ln.gstr2b.supplier_gstin == gstin)
               for ln in (sp.lines_proxy.index(r, 0).data(OBJECT_ROLE) for r in range(sp.lines_proxy.rowCount())))
    sp.v_email.setText("accounts@supplier.example")
    sp.v_status.setCurrentText("Mail sent")
    sp.save_vendor()
    assert st.vendors.get(st.client.id, gstin).followup_status == "Mail sent"

    # Export Excel + PDF from step 10.
    window.go("workflow")
    wf.out_dir.setText(str(tmp_path / "reports"))
    paths = wf.export()
    assert len(paths) == 2 and all(p.exists() for p in paths)

    # History: re-run carries the manual decisions forward.
    window.go("history")
    hist = window.pages["history"]
    hist.table.selectRow(0)
    old_run = st.run_id
    hist.rerun_selected()
    assert st.run_id != old_run
    rerun = st.recon.load(st.run_id).result.lines
    assert any(ln.category == Category.MANUALLY_MATCHED and ln.books.invoice_no == "DOS-1189" for ln in rerun)

    # Open items lists each unresolved document once.
    window.go("open_items")
    oi = window.pages["open_items"]
    ids = [oi.model.rows[i][4] for i in range(oi.model.rowCount())]
    assert "MSL/260/25-26" in ids and "DOS-1189" not in ids


def test_mapping_dialog_drag_and_select(qtbot, window):
    dlg = MappingDialog(window, ["Party Code", "Bill Ref", "Bill Dt", "Basic", "Tax A", "Tax B", "Cess 1"])
    qtbot.addWidget(dlg)
    assert "Supplier GSTIN" in dlg.status.text()
    dlg.assign("supplier_gstin", "Party Code")
    dlg.assign("invoice_no", "Bill Ref")
    dlg.assign("invoice_date", "Bill Dt")
    dlg.assign("taxable_value", "Basic")
    dlg.assign("cgst", "Tax A")
    dlg.assign("cgst", "Tax B")  # Σ field: several columns
    dlg.assign("sgst", "Tax B")  # a column feeds one field only → moved
    assert dlg.template()["fields"]["cgst"] == ["Tax A"]
    assert dlg.template()["fields"]["sgst"] == ["Tax B"]
    assert dlg.missing() == []
    # select-a-field + double-click a column
    dlg.fields.selectRow(11)  # cess
    dlg._double_click(dlg.columns_list.item(6))
    assert dlg.template()["fields"]["cess"] == ["Cess 1"]


def test_import_with_unknown_headings_uses_mapping_dialog(window, monkeypatch, tmp_path, messages):
    st = window.state
    st.set_client(st.clients.create(**CLIENT))
    f = tmp_path / "odd.csv"
    f.write_text(f"Party Code,Bill Ref,Bill Dt,Basic,Tax A,Tax B\n{GSTIN_A},Z-1,01-04-2025,1000,90,90\n")

    def fill(self):
        for field, col in (("supplier_gstin", "Party Code"), ("invoice_no", "Bill Ref"), ("invoice_date", "Bill Dt"),
                           ("taxable_value", "Basic"), ("cgst", "Tax A"), ("sgst", "Tax B")):
            self.assign(field, col)
        self.save_check.setChecked(True)
        self.template_name.setText("odd layout")
        return QDialog.Accepted

    monkeypatch.setattr(MappingDialog, "exec", fill)
    _accept_previews(monkeypatch)
    sf = window.pages["workflow"].import_path(f, Source.BOOKS)
    assert sf is not None and sf.documents_imported == 1
    assert st.imports.get_template("odd layout")["fields"]["cgst"] == ["Tax A"]


def test_progress_dialog_cancel_is_safe(window, qtbot):
    from PySide6.QtCore import QTimer

    def slow(progress=None, cancel=None):
        for i in range(200):
            cancel.check()
            progress(i // 2, "working")
            time.sleep(0.01)
        return "done"

    holder = {}

    def press_cancel():
        dlg = next(w for w in window.findChildren(QDialog) if w.isVisible() and hasattr(w, "token"))
        holder["dlg"] = dlg
        dlg.cancel_btn.click()

    QTimer.singleShot(150, press_cancel)
    task = run_task(window, "Slow", slow)
    assert not task.ok and "nothing was saved" in task.message
    assert task.thread.isFinished()


def test_reconcile_failure_is_reported(window, messages):
    st = window.state
    st.set_client(st.clients.create(**CLIENT))
    window.pages["workflow"].start()
    assert st.run_id is None and any("No books" in m for m in messages)


def test_dashboard_figures_after_reload(window, sample_files, monkeypatch):
    _setup_demo(window, sample_files, monkeypatch).start()
    window.go("dashboard")
    st = window.state
    d = dashboard(st.recon.load(st.run_id).result.lines)
    fy_rows = window.pages["dashboard"].fy_model.rows
    april = next(r for r in fy_rows if r[0] == "2025-04")
    assert april[1] == st.run_id and april[2] == d["itc_as_per_books"] and isinstance(april[2], Decimal)
