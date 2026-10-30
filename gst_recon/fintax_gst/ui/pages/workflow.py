"""The ten-step reconciliation journey on one page."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ...core.models import ReconSettings, Source
from ...importers.pipeline import LAYOUT_LABELS
from ...engine.summary import category_summary, dashboard
from ...services.reconciliation import fy_periods, months_between
from ...services.reports import export_run
from ..dialogs.client_form import ClientDialog
from ..import_flow import import_interactive
from ..state import AppState
from ..theme import money
from ..widgets import LazyPage, RowsModel, Table, card, page_header, primary, sortable
from ..workers import run_task

FILE_FILTER = "Supported files (*.xlsx *.xlsm *.csv *.json *.zip);;All files (*)"
MODES = ["Single month", "Quarter", "Full financial year", "Custom range"]


class StepCard(QWidget):
    def __init__(self, number: int, title: str, hint: str = ""):
        super().__init__()
        frame, lay = card()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        head = QHBoxLayout()
        self.badge = QLabel(str(number))
        self.badge.setObjectName("StepBadge")
        self.number = number
        t = QLabel(title)
        t.setObjectName("StepTitle")
        self.state_lbl = QLabel("")
        self.state_lbl.setObjectName("Muted")
        head.addWidget(self.badge)
        head.addWidget(t)
        head.addStretch()
        head.addWidget(self.state_lbl)
        lay.addLayout(head)
        if hint:
            h = QLabel(hint)
            h.setObjectName("Muted")
            h.setWordWrap(True)
            lay.addWidget(h)
        self.body = QVBoxLayout()
        lay.addLayout(self.body)

    def set_done(self, done: bool, text: str = "") -> None:
        self.badge.setObjectName("StepBadgeDone" if done else "StepBadge")
        self.badge.setText("✓" if done else str(self.number))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.state_lbl.setText(text)


class WorkflowPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        self.last_export: list[Path] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(page_header("Reconcile", "Import, validate, reconcile, review and export – step by step."))

        # 1 client
        self.s1 = StepCard(1, "Select client")
        self.client_lbl = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.client_lbl, 1)
        new_btn = QPushButton("New client…")
        new_btn.clicked.connect(self.new_client)
        all_btn = QPushButton("All clients")
        all_btn.clicked.connect(lambda: self.navigate.emit("clients"))
        row.addWidget(new_btn)
        row.addWidget(all_btn)
        self.s1.body.addLayout(row)

        # 2 period
        self.s2 = StepCard(2, "Select financial year and period")
        grid = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.from_cb, self.to_cb = QComboBox(), QComboBox()
        for w, label in ((self.mode, "Scope"), (self.from_cb, "From"), (self.to_cb, "To")):
            grid.addWidget(QLabel(label))
            grid.addWidget(w)
        grid.addStretch()
        self.s2.body.addLayout(grid)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.from_cb.currentIndexChanged.connect(self._from_changed)
        self.to_cb.currentIndexChanged.connect(lambda _i: self.lazy(self.refresh_status)())

        # 3 / 4 / 5 imports
        self.s3 = StepCard(3, "Import purchase register",
                           "TallyPrime purchase register / GST purchase report or any Excel/CSV register. "
                           "Booking period is taken from the voucher date column when present.")
        b3 = self.books_btn = primary("Import purchase register…")
        b3.clicked.connect(lambda: self.import_dialog(Source.BOOKS))
        self.books_lbl = QLabel()
        self.tally_btn = QPushButton("Import from Tally…")
        self.tally_btn.setToolTip("Fetch the purchase vouchers straight from TallyPrime (XML interface, port 9000)")
        self.tally_btn.clicked.connect(lambda: self.tally_dialog(Source.BOOKS))
        r3 = QHBoxLayout()
        r3.addWidget(b3)
        r3.addWidget(self.tally_btn)
        r3.addWidget(self.books_lbl, 1)
        self.s3.body.addLayout(r3)
        self.s4 = StepCard(4, "Import GSTR-2B", "GST portal Excel, JSON or ZIP download. The return period is read "
                                                "from the file; otherwise the From month is used.")
        b4 = self.g2b_btn = primary("Import GSTR-2B…")
        b4.clicked.connect(lambda: self.import_dialog(Source.GSTR2B))
        self.g2b_lbl = QLabel()
        r4 = QHBoxLayout()
        r4.addWidget(b4)
        r4.addWidget(self.g2b_lbl, 1)
        self.s4.body.addLayout(r4)
        self.s5 = StepCard(5, "Optional: GSTR-3B, IMS, prior-period books and GSTR-2A",
                           "GSTR-3B (portal JSON or template) feeds the Table 4 working; the IMS download is compared "
                           "with books and GSTR-2B; earlier months' purchase registers let the engine recognise "
                           "invoices booked earlier that appear in this GSTR-2B.")
        r5 = QHBoxLayout()
        b5c = QPushButton("Import GSTR-3B…")
        b5c.clicked.connect(lambda: self.navigate.emit("returns"))
        b5d = QPushButton("Import IMS…")
        b5d.clicked.connect(lambda: self.navigate.emit("ims"))
        b5a = QPushButton("Import earlier purchase register…")
        b5a.clicked.connect(lambda: self.import_dialog(Source.BOOKS, prior=True))
        b5b = QPushButton("Import GSTR-2A…")
        b5b.clicked.connect(lambda: self.import_dialog(Source.GSTR2A))
        self.optional_btns = (b5a, b5b, b5c, b5d)
        for b in self.optional_btns:
            r5.addWidget(b)
        r5.addStretch()
        self.s5.body.addLayout(r5)

        # 6 validate
        self.s6 = StepCard(6, "Preview and validate data", "Files contributing documents to the selected period.")
        self.files_model = RowsModel(["Import", "File", "Source", "Layout", "Period", "Docs in period", "Rows read",
                                      "Imported", "Rejected", "Skipped (existing)"],
                                     kinds=["int", "text", "text", "text", "text", "int", "int", "int", "int", "int"])
        self.files_table = Table()
        self.files_table.setModel(sortable(self.files_model))
        self.files_table.setMinimumHeight(140)
        self.validate_lbl = QLabel()
        self.s6.body.addWidget(self.files_table)
        r6 = QHBoxLayout()
        r6.addWidget(self.validate_lbl, 1)
        imports_btn = QPushButton("Import details / issues")
        imports_btn.clicked.connect(lambda: self.navigate.emit("imports"))
        r6.addWidget(imports_btn)
        self.s6.body.addLayout(r6)

        # 7 reconcile
        self.s7 = StepCard(7, "Start reconciliation")
        form = QHBoxLayout()
        self.amount_tol = QDoubleSpinBox()
        self.amount_tol.setRange(0, 1000)
        self.amount_tol.setDecimals(2)
        self.amount_tol.setPrefix("₹ ")
        self.date_tol = QSpinBox()
        self.date_tol.setRange(0, 90)
        self.date_tol.setSuffix(" days")
        self.fuzzy = QSpinBox()
        self.fuzzy.setRange(50, 100)
        self.fuzzy.setSuffix(" %")
        self.fuzzy_on = QCheckBox("Suggest probable matches")
        self.compare = QComboBox()
        self.compare.addItems(["GSTR-2B", "GSTR-2A"])
        for label, w in (("Amount tolerance", self.amount_tol), ("Date tolerance", self.date_tol),
                         ("Fuzzy threshold", self.fuzzy), ("Compare books with", self.compare)):
            form.addWidget(QLabel(label))
            form.addWidget(w)
        form.addWidget(self.fuzzy_on)
        form.addStretch()
        self.s7.body.addLayout(form)
        self.start_btn = primary("▶  Start Reconciliation")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.clicked.connect(self.start)
        r7 = QHBoxLayout()
        r7.addWidget(self.start_btn)
        r7.addStretch()
        self.s7.body.addLayout(r7)
        self._load_settings()

        # 8 review
        self.s8 = StepCard(8, "Review matching summary")
        self.summary_lbl = QLabel()
        self.summary_lbl.setWordWrap(True)
        self.cat_model = RowsModel(["Category", "Lines", "Books ITC", "GSTR-2B ITC", "ITC Difference", "ITC at Risk"],
                                   kinds=["text", "int", "money", "money", "money", "money"])
        self.cat_table = Table()
        self.cat_table.setModel(sortable(self.cat_model))
        self.cat_table.setMinimumHeight(200)
        self.s8.body.addWidget(self.summary_lbl)
        self.s8.body.addWidget(self.cat_table)
        dash_btn = QPushButton("Open dashboard")
        dash_btn.clicked.connect(lambda: self.navigate.emit("dashboard"))
        self.s8.body.addWidget(dash_btn)

        # 9 exceptions
        self.s9 = StepCard(9, "Resolve exceptions")
        self.pending_lbl = QLabel()
        r9 = QHBoxLayout()
        r9.addWidget(self.pending_lbl, 1)
        ex_btn = primary("Open exceptions")
        ex_btn.clicked.connect(lambda: self.navigate.emit("exceptions"))
        r9.addWidget(ex_btn)
        self.s9.body.addLayout(r9)

        # 10 export
        self.s10 = StepCard(10, "Export Excel and PDF reports")
        r10 = QHBoxLayout()
        self.out_dir = QLineEdit(str(Path.home() / "Documents" / "FinTaxPro Reports"))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_out)
        self.pdf_check = QCheckBox("Also PDF summary")
        self.pdf_check.setChecked(True)
        self.export_btn = primary("Export reports")
        self.export_btn.clicked.connect(self.export)
        self.open_folder_btn = QPushButton("Open folder")
        self.open_folder_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_dir.text())))
        for w in (QLabel("Folder"), self.out_dir, browse, self.pdf_check, self.export_btn, self.open_folder_btn):
            r10.addWidget(w)
        self.s10.body.addLayout(r10)
        self.export_lbl = QLabel()
        self.export_lbl.setWordWrap(True)
        self.s10.body.addWidget(self.export_lbl)

        for c in (self.s1, self.s2, self.s3, self.s4, self.s5, self.s6, self.s7, self.s8, self.s9, self.s10):
            lay.addWidget(c)
        lay.addStretch()
        state.clientChanged.connect(self._fill_months_quiet)
        state.clientChanged.connect(self.lazy(self.refresh_status))
        state.runChanged.connect(self.lazy(self.refresh_status))
        state.dataChanged.connect(self.lazy(self.refresh_status))
        self._fill_months()
        self.lazy(self.refresh_status)()  # loads when first shown

    # ---------------------------------------------------------------- period
    def on_client(self) -> None:
        self._fill_months()
        self.refresh_status()

    def _fill_months_quiet(self) -> None:
        """Keep the month lists in step with the FY even while hidden (cheap, no queries)."""
        months = months_between(*fy_periods(self.state.fy))
        if [self.from_cb.itemText(i) for i in range(self.from_cb.count())] != months:
            self._fill_months()

    def _fill_months(self) -> None:
        months = months_between(*fy_periods(self.state.fy))
        for cb in (self.from_cb, self.to_cb):
            cb.blockSignals(True)
            cur = cb.currentText()
            cb.clear()
            cb.addItems(months)
            if cur in months:
                cb.setCurrentText(cur)
            cb.blockSignals(False)
        self._mode_changed()

    def _mode_changed(self) -> None:
        mode = self.mode.currentText()
        months = [self.from_cb.itemText(i) for i in range(self.from_cb.count())]
        if not months:
            return
        self.to_cb.setEnabled(mode == "Custom range")
        self.from_cb.setEnabled(mode != "Full financial year")
        if mode == "Full financial year":
            self.from_cb.setCurrentIndex(0)
            self.to_cb.setCurrentIndex(len(months) - 1)
        self._from_changed()

    def _from_changed(self) -> None:
        mode = self.mode.currentText()
        i = self.from_cb.currentIndex()
        if mode == "Single month":
            self.to_cb.setCurrentIndex(i)
        elif mode == "Quarter":
            self.from_cb.blockSignals(True)
            q = i - i % 3
            self.from_cb.setCurrentIndex(q)
            self.from_cb.blockSignals(False)
            self.to_cb.setCurrentIndex(min(q + 2, self.to_cb.count() - 1))
        elif self.to_cb.currentIndex() < i:
            self.to_cb.setCurrentIndex(i)
        self.lazy(self.refresh_status)()

    def period(self) -> tuple[str, str]:
        return self.from_cb.currentText(), self.to_cb.currentText()

    def set_period(self, p_from: str, p_to: str | None = None, mode: str = "Single month") -> None:
        self.mode.setCurrentText(mode)
        self.from_cb.setCurrentText(p_from)
        if p_to:
            self.to_cb.setCurrentText(p_to)

    # --------------------------------------------------------------- status
    def refresh_status(self) -> None:
        st = self.state
        if st.client is None:
            self.client_lbl.setText("<b>No client selected.</b> Choose one in the selector above or create one.")
            self.s1.set_done(False)
            for c in (self.s2, self.s3, self.s4, self.s6, self.s7, self.s8, self.s9, self.s10):
                c.setEnabled(False)
            return
        for c in (self.s2, self.s3, self.s4, self.s5, self.s6, self.s7, self.s8, self.s9, self.s10):
            c.setEnabled(True)
        cl = st.client
        self.client_lbl.setText(f"<b>{cl.name}</b> · GSTIN {cl.gstin} · {cl.state} · {cl.return_frequency} returns")
        self.s1.set_done(True, cl.gstin)
        p_from, p_to = self.period()
        if not p_from:
            return
        self.s2.set_done(True, f"FY {st.fy}: {p_from} to {p_to}")
        scope = st.tracking.scope(cl.id, p_from, p_to)
        self.books_lbl.setText(f"{scope['books']} purchase documents in {p_from}..{p_to}")
        self.g2b_lbl.setText(f"{scope['gstr2b']} GSTR-2B documents in {p_from}..{p_to}"
                             + (f" · {scope['gstr2a']} GSTR-2A" if scope["gstr2a"] else ""))
        self.s3.set_done(scope["books"] > 0, f"{scope['books']} documents")
        self.s4.set_done(scope["gstr2b"] > 0, f"{scope['gstr2b']} documents")
        rows = [[f.id, f.file_name, f.source_type, LAYOUT_LABELS.get(f.layout, f.layout), f.period or "", n, f.rows_read, f.documents_imported,
                 f.rows_rejected, f.documents_skipped_existing] for f, n in scope["files"]]
        self.files_model.set_rows(rows)
        self.files_table.fit()
        rejected = sum(f.rows_rejected for f, _n in scope["files"])
        self.validate_lbl.setText(
            f"{len(rows)} file(s); {rejected} rejected row(s) kept with reasons in the import log."
            if rows else "No files imported for this period yet.")
        self.s6.set_done(bool(rows), f"{rejected} rejected rows" if rows else "")
        self.start_btn.setEnabled(scope["books"] + scope["gstr2b"] > 0 and st.can("reconcile"))
        for b in (self.books_btn, self.tally_btn, self.g2b_btn, *self.optional_btns):
            b.setEnabled(st.can("import"))
        self.export_btn.setEnabled(st.can("export"))
        self._show_run()

    def _show_run(self) -> None:
        st = self.state
        if st.run_id is None:
            for c in (self.s7, self.s8, self.s9, self.s10):
                c.set_done(False)
            self.summary_lbl.setText("Run a reconciliation to see the summary.")
            self.cat_model.set_rows([])
            self.pending_lbl.setText("")
            return
        ctx = st.run_context()
        lines = ctx.result.lines
        d = dashboard(lines)
        run = ctx.run
        self.s7.set_done(True, f"Run #{run.id} · {run.period_from}..{run.period_to}")
        self.s8.set_done(True)
        self.summary_lbl.setText(
            f"<b>Run #{run.id}</b> ({run.period_from} to {run.period_to}): {d['total_lines']} lines · "
            f"{d['fully_matched']} fully matched · {d['partially_matched']} partially matched · "
            f"{d['missing_in_gstr2b']} missing in GSTR-2B · {d['missing_in_books']} missing in books · "
            f"ITC books {money(d['itc_as_per_books'], True)} vs GSTR-2B {money(d['itc_as_per_gstr2b'], True)} · "
            f"<span style='color:#C62828'>ITC at risk {money(d['itc_at_risk'], True)}</span>")
        self.cat_model.set_rows([[r.category.value, r.lines, r.books.itc, r.gstr2b.itc, r.itc_difference,
                                  r.itc_at_risk] for r in category_summary(lines) if r.lines])
        self.cat_table.fit(320)
        self.pending_lbl.setText(f"<b>{d['pending_cases']}</b> case(s) pending review, including "
                                 f"{d['probable_matches']} probable match(es) to confirm or reject.")
        self.s9.set_done(d["pending_cases"] == 0, f"{d['pending_cases']} pending")
        self.s10.set_done(bool(self.last_export))

    # --------------------------------------------------------------- actions
    def new_client(self) -> None:
        dlg = ClientDialog(self, self.state.clients, self.state.user)
        if dlg.exec() and dlg.saved:
            self.state.notify()
            self.state.set_client(self.state.clients.get(dlg.saved.id))

    def tally_dialog(self, source: Source) -> None:
        from ..tally_import import tally_import

        if tally_import(self, self.state, source, self.from_cb.currentText(), self.to_cb.currentText()):
            self.lazy(self.refresh_status)()

    def import_dialog(self, source: Source, prior: bool = False) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Select {source.value} file", "", FILE_FILTER)
        if path:
            self.import_path(path, source, prior)

    def import_path(self, path: str | Path, source: Source, prior: bool = False):
        period = None
        if source != Source.BOOKS:
            period = None if Path(path).suffix.lower() in (".json", ".zip") else self.period()[0]
        elif prior:
            period = None  # booking month comes from voucher dates in the earlier register
        result = import_interactive(self, self.state, path, source, period)
        self.refresh_status()
        return result

    def settings(self) -> ReconSettings:
        s = self.state.recon_settings()
        s.amount_tolerance = Decimal(str(round(self.amount_tol.value(), 2)))
        s.date_tolerance_days = self.date_tol.value()
        s.fuzzy_threshold = self.fuzzy.value()
        s.enable_fuzzy = self.fuzzy_on.isChecked()
        return s

    def _load_settings(self) -> None:
        s = self.state.recon_settings()
        self.amount_tol.setValue(float(s.amount_tolerance))
        self.date_tol.setValue(s.date_tolerance_days)
        self.fuzzy.setValue(s.fuzzy_threshold)
        self.fuzzy_on.setChecked(s.enable_fuzzy)

    def start(self) -> None:
        st = self.state
        if st.client is None:
            return
        p_from, p_to = self.period()
        settings = self.settings()
        st.save_recon_settings(settings)
        compare = Source.GSTR2B if self.compare.currentText() == "GSTR-2B" else Source.GSTR2A
        task = run_task(self, "Reconciling", st.recon.run, st.client.id, p_from, p_to, settings,
                        compare_with=compare, user=st.user)
        if not task.ok:
            QMessageBox.information(self, "Reconciliation", task.message)
            return
        self.last_export = []
        st.set_run(task.result_value)
        st.notify()

    def _browse_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Report folder", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def export(self) -> list[Path]:
        st = self.state
        if st.run_id is None:
            QMessageBox.information(self, "Export", "Run a reconciliation first.")
            return []
        task = run_task(self, "Exporting reports", export_run, st.db, st.run_id, self.out_dir.text(),
                        pdf=self.pdf_check.isChecked(), user=st.user, cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "Export", task.message)
            return []
        self.last_export = task.result_value
        self.export_lbl.setText("Saved:<br>" + "<br>".join(str(p) for p in self.last_export))
        self.s10.set_done(True, "exported")
        return self.last_export

