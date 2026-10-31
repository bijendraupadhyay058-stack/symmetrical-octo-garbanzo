"""GST Portal: open the official portal to download reports, then pick the downloads up from the Downloads folder
and import them with one click; electronic cash and credit ledger balances.

The user signs in on the official portal in their own browser. No portal password is asked for or stored."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ...core.models import Source
from ...core.money import fmt_inr
from ...importers.readers import UnsupportedFileError
from ...services.common import ServiceError
from ...services.portal import PORTAL_LOGIN, REPORTS, SOURCE_OF, PortalService, default_downloads
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, section, sortable


class PortalPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.svc = PortalService(state.db)
        self.files = []
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header(
            "GST Portal", "Open the official GST portal, sign in there yourself and download the reports. Files you "
                          "save in the Downloads folder are recognised here and imported with one click. Your portal "
                          "password is never asked for or stored by this program."))
        top = QHBoxLayout()
        self.status_lbl = QLabel("Checking the internet connection…")
        self.login_btn = QPushButton("Log in to GST portal")
        self.login_btn.setToolTip(PORTAL_LOGIN)
        self.login_btn.clicked.connect(lambda: self.open_portal(PORTAL_LOGIN))
        top.addWidget(self.status_lbl)
        top.addStretch()
        top.addWidget(self.login_btn)
        lay.addLayout(top)
        lay.addWidget(section("1. Download from the portal (opens in your browser)"))
        grid = QGridLayout()
        self.report_btns = {}
        for n, (key, (label, url, where)) in enumerate(REPORTS.items()):
            b = QPushButton(label)
            b.setToolTip(f"After signing in: {where}")
            b.clicked.connect(lambda _c=False, k=key: self.open_report(k))
            self.report_btns[key] = b
            grid.addWidget(b, n // 4, n % 4)
        lay.addLayout(grid)
        self.hint = QLabel("Point at a button to see where the report is on the portal.")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        lay.addWidget(section("2. Files downloaded – recognised by type, client (GSTIN) and month"))
        bar = QHBoxLayout()
        self.folder = QLineEdit(str(state.qsettings.value("portal_downloads", str(default_downloads()))))
        self.folder.editingFinished.connect(self._folder_changed)
        change = QPushButton("Change…")
        change.clicked.connect(lambda: self.choose_folder())
        self.days = QComboBox()
        for d in (1, 3, 7, 30, 90):
            self.days.addItem(f"last {d} day(s)", d)
        self.days.setCurrentIndex(2)
        self.days.currentIndexChanged.connect(lambda _i: self.refresh())
        self.watch_cb = QCheckBox("Watch the folder")
        self.watch_cb.setChecked(str(state.qsettings.value("portal_watch", "true")).lower() == "true")
        self.watch_cb.toggled.connect(self._watch_toggled)
        check = QPushButton("Check now")
        check.clicked.connect(lambda: self.refresh())
        for w in (QLabel("Folder"), self.folder, change, self.days, self.watch_cb, check):
            bar.addWidget(w)
        lay.addLayout(bar)
        split = QSplitter(Qt.Vertical)
        top_w = QWidget()
        tl = QVBoxLayout(top_w)
        tl.setContentsMargins(0, 0, 0, 0)
        self.model = RowsModel(["File", "Report", "Client", "GSTIN", "Month", "Status"])
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.import_selected())
        tl.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.import_btn = QPushButton("Import selected")
        self.import_btn.clicked.connect(lambda: self.import_selected())
        self.import_all_btn = QPushButton("Import all ready")
        self.import_all_btn.clicked.connect(lambda: self.import_all())
        manual = QPushButton("Import a file…")
        manual.clicked.connect(lambda: self.import_other())
        self.found_lbl = QLabel()
        for w in (self.import_btn, self.import_all_btn, manual):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.found_lbl)
        tl.addLayout(row)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("3. Electronic cash and credit ledgers of the selected client"))
        lrow = QHBoxLayout()
        self.ledger_cb = QComboBox()
        self.ledger_cb.addItem("Electronic cash ledger", "CASH")
        self.ledger_cb.addItem("Electronic credit ledger", "CREDIT")
        self.ledger_cb.currentIndexChanged.connect(lambda _i: self.show_ledger())
        self.balance_lbl = QLabel()
        self.balance_lbl.setWordWrap(True)
        lrow.addWidget(self.ledger_cb)
        lrow.addWidget(self.balance_lbl, 1)
        bl.addLayout(lrow)
        self.ledger_model = RowsModel(["Date", "Reference", "Tax period", "Description", "Cr / Dr", "IGST", "CGST",
                                       "SGST", "Cess"],
                                      kinds=["date", "text", "text", "text", "text", "money", "money", "money",
                                             "money"])
        self.ledger_table = Table()
        self.ledger_table.setModel(sortable(self.ledger_model))
        bl.addWidget(self.ledger_table, 1)
        split.addWidget(top_w)
        split.addWidget(bottom)
        lay.addWidget(split, 1)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self._debounce.start())
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(2500)  # let the browser finish writing the file
        self._debounce.timeout.connect(self.lazy(self.refresh))
        self._set_watch()
        online = getattr(state, "online", None)
        if online is not None:
            online.changed.connect(self._online_changed)
            self._online_changed(online.online)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.refresh))
        self.lazy(self.refresh)()

    # ------------------------------------------------------------ portal
    def _online_changed(self, ok) -> None:
        if ok is None:
            self.status_lbl.setText("Checking the internet connection…")
        elif ok:
            self.status_lbl.setText("<span style='color:#2E7D32'>● Online</span> – the portal can be opened")
        else:
            self.status_lbl.setText("<span style='color:#C62828'>● Offline</span> – the portal cannot be opened now; "
                                    "files already downloaded can still be imported and all other work continues")

    def open_portal(self, url: str) -> bool:
        online = getattr(self.state, "online", None)
        if online is not None and online.online is False:
            QMessageBox.information(self, "GST portal", "There is no internet connection right now. Connect to the "
                                    "internet and try again – everything else in the program works offline.")
            return False
        return bool(QDesktopServices.openUrl(QUrl(url)))

    def open_report(self, key: str) -> bool:
        label, url, where = REPORTS[key]
        self.hint.setText(f"<b>{label}</b>: sign in on the portal, then {where}. Save the file in "
                          f"{self.folder.text()} – it appears in the list below.")
        return self.open_portal(url)

    # ------------------------------------------------------------- folder
    def _folder_changed(self) -> None:
        self.state.qsettings.setValue("portal_downloads", self.folder.text().strip())
        self._set_watch()
        self.refresh()

    def choose_folder(self, path: str | None = None) -> None:
        path = path or QFileDialog.getExistingDirectory(self, "Downloads folder", self.folder.text())
        if path:
            self.folder.setText(path)
            self._folder_changed()

    def _watch_toggled(self, on: bool) -> None:
        self.state.qsettings.setValue("portal_watch", "true" if on else "false")
        self._set_watch()

    def _set_watch(self) -> None:
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        folder = self.folder.text().strip()
        if self.watch_cb.isChecked() and folder and Path(folder).is_dir():
            self.watcher.addPath(folder)

    # ------------------------------------------------------------- files
    def refresh(self) -> None:
        client_id = self.state.client.id if self.state.client else None
        self.files = self.svc.scan(self.folder.text().strip(), self.days.currentData(), client_id)
        self.model.set_rows([[f.path.name, f.label, f.client_name, f.gstin, f.period or "", f.status]
                             for f in self.files], self.files)
        self.table.fit(360)
        ready = sum(1 for f in self.files if f.ready)
        self.found_lbl.setText(f"{len(self.files)} GST file(s) found · {ready} ready to import")
        self.import_all_btn.setEnabled(ready > 0)
        self.show_ledger()

    def selected(self) -> list:
        rows = self.table.selectionModel().selectedRows()
        return [self.table.model().index(r.row(), 0).data(OBJECT_ROLE) for r in rows]

    def import_one(self, pf) -> str | None:
        """Import one recognised file for its client (the client is selected first)."""
        from ..import_flow import import_interactive
        from ..workers import run_task

        if not pf.ready:
            QMessageBox.information(self, "Import", f"{pf.path.name}: {pf.status}")
            return None
        if self.state.client is None or self.state.client.id != pf.client_id:
            self.state.set_client(self.state.clients.get(pf.client_id))
        if pf.kind in SOURCE_OF:  # documents: shown in the import preview first
            sf = import_interactive(self, self.state, pf.path, Source(SOURCE_OF[pf.kind]), pf.period)
            return f"{pf.label}: {sf.documents_imported} document(s) saved" if sf is not None else None
        task = run_task(self, f"Importing {pf.path.name}", self.svc.import_file, pf, self.state.user,
                        cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "Import", task.message)
            return None
        self.state.notify()
        return task.result_value

    def import_selected(self) -> list[str]:
        done = [r for f in self.selected() if f is not None and (r := self.import_one(f))]
        self._report(done)
        return done

    def import_all(self) -> list[str]:
        done = [r for f in list(self.files) if f.ready and (r := self.import_one(f))]
        self._report(done)
        return done

    def import_other(self, path: str | None = None) -> str | None:
        path = path or QFileDialog.getOpenFileName(self, "GST portal file", self.folder.text(),
                                                   "Portal files (*.json *.zip *.xlsx *.xls *.csv)")[0]
        if not path:
            return None
        pf = self.svc.inspect(path, self.state.client.id if self.state.client else None)
        if pf is None:
            QMessageBox.warning(self, "Import", f"{Path(path).name} is not a GST portal download this program "
                                "recognises. Import it from the page for that return instead.")
            return None
        result = self.import_one(pf)
        self._report([result] if result else [])
        return result

    def _report(self, done: list[str]) -> None:
        if done:
            QMessageBox.information(self, "Imported", "\n".join(done))
        self.refresh()

    # ------------------------------------------------------------ ledgers
    def show_ledger(self) -> None:
        if self.state.client is None:
            self.ledger_model.set_rows([])
            self.balance_lbl.setText("Select a client to see its ledgers.")
            return
        ledger = self.ledger_cb.currentData()
        try:
            rows = self.svc.ledger_rows(self.state.client.id, ledger)
            balances = self.svc.balances(self.state.client.id)
        except (ServiceError, UnsupportedFileError) as exc:  # pragma: no cover
            self.balance_lbl.setText(str(exc))
            return
        self.ledger_model.set_rows([[r.entry_date, r.reference, r.tax_period, r.description, r.txn, r.igst, r.cgst,
                                     r.sgst, r.cess] for r in rows], rows)
        self.ledger_table.fit(320)
        if ledger in balances:
            as_on, b = balances[ledger]
            total = sum(b.values())
            self.balance_lbl.setText(
                f"<b>Balance as on {as_on:%d-%m-%Y}: Rs. {fmt_inr(total)}</b> – IGST {fmt_inr(b['igst'])} · CGST "
                f"{fmt_inr(b['cgst'])} · SGST {fmt_inr(b['sgst'])} · Cess {fmt_inr(b['cess'])}" if as_on else
                f"Balance: Rs. {fmt_inr(total)}")
        else:
            self.balance_lbl.setText("No ledger downloaded yet – use the cash / credit ledger buttons above.")
