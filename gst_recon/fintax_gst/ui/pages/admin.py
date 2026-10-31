"""Clients, imports and settings pages."""
from __future__ import annotations

import json
from decimal import Decimal

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ... import PRODUCT_FULL_NAME, TAGLINE, __version__
from ...core.models import ReconSettings, Source
from ...importers.pipeline import LAYOUT_LABELS
from ...services.common import ServiceError
from ..dialogs.client_form import ClientDialog
from ..import_flow import import_interactive
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, card, page_header, primary, section, sortable
from .workflow import FILE_FILTER


class ClientsPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Clients", "Each GSTIN is a separate client with its own data and history. "
                                             "Several GSTINs of one PAN are grouped by PAN."))
        self.model = RowsModel(["ID", "Client", "Trade name", "GSTIN", "PAN", "State", "FY", "Registration",
                                "Returns", "Contact", "Email", "Mobile"],
                               kinds=["int"] + ["text"] * 11)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.use_selected())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn, prim in (("New client…", self.new, True), ("Edit…", self.edit, False),
                               ("Work on this client", self.use_selected, False)):
            b = primary(text) if prim else QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            if fn != self.use_selected:
                b.setEnabled(state.can("manage_clients"))
        row.addStretch()
        lay.addLayout(row)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()  # loads when first shown

    def reload(self) -> None:
        clients = self.state.clients.list()
        self.model.set_rows([[c.id, c.name, c.trade_name, c.gstin, c.pan, c.state, c.financial_year,
                              c.registration_type, c.return_frequency, c.contact_person, c.email, c.mobile]
                             for c in clients], clients)
        self.table.fit()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def new(self) -> None:
        dlg = ClientDialog(self, self.state.clients, self.state.user)
        if dlg.exec() and dlg.saved:
            self.state.notify()
            self.state.set_client(self.state.clients.get(dlg.saved.id))

    def edit(self) -> None:
        c = self._selected()
        if c is None:
            return
        dlg = ClientDialog(self, self.state.clients, self.state.user, c)
        if dlg.exec():
            self.state.notify()
            if self.state.client and self.state.client.id == c.id:
                self.state.set_client(self.state.clients.get(c.id))

    def use_selected(self) -> None:
        c = self._selected()
        if c is not None:
            self.state.set_client(c)


class ImportsPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Imports", "Every imported file with its fingerprint, counts and import log. "
                                             "Rejected rows are kept here with their original values."))
        row = QHBoxLayout()
        self.source_cb = QComboBox()
        self.source_cb.addItems(["Purchase register (books)", "GSTR-2B", "GSTR-2A", "IMS download"])
        imp = primary("Import file…")
        imp.setEnabled(state.can("import"))
        imp.clicked.connect(self.import_file)
        self.remove_btn = QPushButton("Remove import…")
        self.remove_btn.setObjectName("Danger")
        self.remove_btn.clicked.connect(self.remove)
        self.remove_btn.setEnabled(state.can("delete_data"))
        row.addWidget(QLabel("Source"))
        row.addWidget(self.source_cb)
        row.addWidget(imp)
        row.addStretch()
        row.addWidget(self.remove_btn)
        lay.addLayout(row)
        self.model = RowsModel(["ID", "File", "Source", "Layout", "Period", "Rows read", "Imported", "Rejected",
                                "Skipped (existing)", "Imported at", "By", "SHA-256"],
                               kinds=["int", "text", "text", "text", "text", "int", "int", "int", "int", "text",
                                      "text", "text"])
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.selectionModel().selectionChanged.connect(self._show_issues)
        lay.addWidget(self.table, 1)
        lay.addWidget(section("Import log of the selected file"))
        self.issues_model = RowsModel(["Severity", "Sheet", "Row", "Message", "Original values"])
        self.issues = Table()
        self.issues.setModel(sortable(self.issues_model))
        lay.addWidget(self.issues, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()  # loads when first shown

    def reload(self) -> None:
        st = self.state
        files = st.imports.list_files(st.client.id) if st.client else []
        self.model.set_rows([[f.id, f.file_name, f.source_type, LAYOUT_LABELS.get(f.layout, f.layout), f.period or "", f.rows_read,
                              f.documents_imported, f.rows_rejected, f.documents_skipped_existing,
                              f"{f.imported_at:%d-%m-%Y %H:%M}", f.imported_by, f.sha256[:16] + "…"]
                             for f in files], files)
        self.table.fit()
        self.issues_model.set_rows([])

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def _show_issues(self, *_):
        f = self._selected()
        if f is None:
            return
        rows = []
        for i in self.state.imports.issues_for([f.id]):
            try:
                raw = json.loads(i.raw_json or "{}")
            except ValueError:
                raw = {}
            rows.append([i.severity.upper(), i.sheet, i.row_ref, i.message,
                         "; ".join(f"{k}={v}" for k, v in raw.items() if v)])
        self.issues_model.set_rows(rows)
        self.issues.fit(420)

    def import_file(self) -> None:
        source = [Source.BOOKS, Source.GSTR2B, Source.GSTR2A, Source.IMS][self.source_cb.currentIndex()]
        path, _ = QFileDialog.getOpenFileName(self, "Select file", "", FILE_FILTER)
        if not path:
            return
        period = None
        if source != Source.BOOKS and not path.lower().endswith((".json", ".zip")):
            from PySide6.QtWidgets import QInputDialog

            period, ok = QInputDialog.getText(self, "Return period", "Return period of this file (YYYY-MM), "
                                              "if it is not stated in the file:")
            if not ok:
                return
        import_interactive(self, self.state, path, source, period or None)

    def remove(self) -> None:
        f = self._selected()
        if f is None or self.state.client is None:
            return
        try:
            u = self.state.imports.usage(self.state.client.id, f.id)
        except ServiceError as exc:
            QMessageBox.warning(self, "Remove import", str(exc))
            return
        also = [f"• reconciliation #{r.id} ({r.period_from}..{r.period_to}, {r.comparison.replace('_', ' ')}) with "
                "its statuses and remarks" for r in u["runs"]]
        for key, label in (("decisions", "manual match decision(s)"), ("reviews", "ITC review decision(s)"),
                           ("claims", "ITC claim register entr(ies)")):
            if u[key]:
                also.append(f"• {u[key]} {label} for documents of this file")
        text = f"Remove import #{f.id} ({f.file_name}) and its documents?"
        if also:
            text += ("\n\nThis file is used by the following, which will be deleted too:\n" + "\n".join(also) +
                     "\n\nAfterwards, import the correct file and click Start Reconciliation again.")
        text += "\n\nThis is recorded in the audit log and cannot be undone."
        if QMessageBox.question(self, "Remove import", text) != QMessageBox.Yes:
            return
        try:
            n = self.state.imports.remove_import(self.state.client.id, f.id, self.state.user,
                                                 with_dependants=bool(also))
        except ServiceError as exc:
            QMessageBox.warning(self, "Remove import", str(exc))
            return
        if u["runs"] and self.state.run_id in {r.id for r in u["runs"]}:
            self.state.set_run(None)
        QMessageBox.information(self, "Remove import", f"Removed {n} document(s)" +
                                (f" and {len(u['runs'])} reconciliation(s)." if u["runs"] else "."))
        self.state.notify()


class SettingsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Settings", "Default matching rules, data location, backup and restore."))
        frame, fl = card()
        fl.addWidget(section("Default matching rules"))
        form = QFormLayout()
        s = state.recon_settings()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1000)
        self.amount.setPrefix("₹ ")
        self.amount.setValue(float(s.amount_tolerance))
        self.days = QSpinBox()
        self.days.setRange(0, 90)
        self.days.setValue(s.date_tolerance_days)
        self.fuzzy = QSpinBox()
        self.fuzzy.setRange(50, 100)
        self.fuzzy.setValue(s.fuzzy_threshold)
        self.gap = QSpinBox()
        self.gap.setRange(0, 50)
        self.gap.setValue(s.fuzzy_min_gap)
        self.large = QDoubleSpinBox()
        self.large.setRange(0, 1e9)
        self.large.setDecimals(0)
        self.large.setPrefix("₹ ")
        self.large.setValue(float(s.large_difference_threshold))
        self.loose = QCheckBox("Match invoice numbers ignoring leading zeros (PP-7 = PP-0007)")
        self.loose.setChecked(s.enable_loose_number_match)
        self.fuzzy_on = QCheckBox("Suggest probable matches for typing differences")
        self.fuzzy_on.setChecked(s.enable_fuzzy)
        self.gstin_on = QCheckBox("Suggest matches where only the supplier GSTIN differs")
        self.gstin_on.setChecked(s.enable_gstin_mismatch_check)
        for label, w in (("Amount tolerance per tax component", self.amount), ("Date tolerance (days)", self.days),
                         ("Fuzzy similarity threshold (%)", self.fuzzy), ("Minimum lead over runner-up", self.gap),
                         ("Highlight differences from", self.large), ("", self.loose), ("", self.fuzzy_on),
                         ("", self.gstin_on)):
            form.addRow(label, w)
        fl.addLayout(form)
        save = primary("Save defaults")
        save.clicked.connect(self.save)
        save.setEnabled(state.can("settings"))
        fl.addWidget(save)
        lay.addWidget(frame)

        frame2, dl = card()
        dl.addWidget(section("Data and backups"))
        dl.addWidget(QLabel(f"Database: {state.db.location}"))
        row = QHBoxLayout()
        for text, fn in (("Back up now", self.backup), ("Restore from backup…", self.restore),
                         ("Open data folder", self.open_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            b.setEnabled({"Back up now": state.can("settings"),
                          "Restore from backup…": state.can("restore")}.get(text, True))
        row.addStretch()
        dl.addLayout(row)
        self.backup_lbl = QLabel("")
        dl.addWidget(self.backup_lbl)
        lay.addWidget(frame2)
        about, al = card()
        al.addWidget(QLabel(f"<b>{PRODUCT_FULL_NAME}</b> v{__version__}<br>{TAGLINE}<br>"
                            "All data stays on this computer. No GST portal credentials are used."))
        from ..updater import auto_check_enabled

        up = QHBoxLayout()
        self.auto_update = QCheckBox("Check for new versions once a day (only the latest version number is read from "
                                     "the download page; no client data is sent)")
        self.auto_update.setChecked(auto_check_enabled(state.qsettings))
        self.auto_update.toggled.connect(lambda on: state.qsettings.setValue("update_check", "true" if on else "false"))
        check = QPushButton("Check for updates now")
        check.clicked.connect(self.check_updates)
        up.addWidget(self.auto_update, 1)
        up.addWidget(check)
        al.addLayout(up)
        lay.addWidget(about)
        lay.addStretch()

    def check_updates(self):
        bar = getattr(self.window(), "update_bar", None)
        return bar.check_now(self) if bar is not None else None

    def settings(self) -> ReconSettings:
        return ReconSettings(
            amount_tolerance=Decimal(str(round(self.amount.value(), 2))), date_tolerance_days=self.days.value(),
            fuzzy_threshold=self.fuzzy.value(), fuzzy_min_gap=self.gap.value(),
            large_difference_threshold=Decimal(str(int(self.large.value()))),
            enable_loose_number_match=self.loose.isChecked(), enable_fuzzy=self.fuzzy_on.isChecked(),
            enable_gstin_mismatch_check=self.gstin_on.isChecked())

    def save(self) -> None:
        self.state.save_recon_settings(self.settings())
        QMessageBox.information(self, "Settings", "Defaults saved. They apply to the next reconciliation.")

    def backup(self) -> None:
        path = self.state.db.backup(suffix="manual")
        self.backup_lbl.setText(f"Backup written to {path}")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", str(self.state.db.data_dir / "backups"),
                                              "SQLite backup (*.db)")
        if not path:
            return
        if QMessageBox.question(self, "Restore", "Replace the current database with this backup? The current "
                                "database is backed up first.") != QMessageBox.Yes:
            return
        try:
            safety = self.state.db.restore(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Restore", str(exc))
            return
        self.backup_lbl.setText(f"Restored. Previous database saved as {safety}")
        self.state.set_client(None)
        self.state.notify()

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.state.db.data_dir)))


