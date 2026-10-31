"""Batch processing: import, reconcile and report a whole folder of clients in one go."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..state import AppState
from ..widgets import RowsModel, Table, card, page_header, primary, section, sortable
from ..workers import run_task

HELP = ("Put each client's files in a folder whose name contains the client's GSTIN, with one folder per month "
        "inside it, for example:  <b>Shree Ganesh Traders 27AAPFU0939F1ZV \\ 2025-04 \\ purchase_register.xlsx</b>."
        "<br>The file name says what it is: <b>purchase</b>, <b>sales</b>, <b>gstr2b</b>, <b>gstr1</b>, "
        "<b>gstr3b</b>, <b>einvoice</b>, <b>ewb</b>, <b>ims</b>, <b>tds</b>. Files already imported are skipped; "
        "reports are saved in a <b>reports</b> folder inside each month folder.")
COLORS = {"error": "#FFCDD2", "cancelled": "#FFCDD2", "imported": "#C8E6C9", "reconciled": "#C8E6C9",
          "client": "#BBDEFB", "skipped": "#FFF3C4"}
ACTIONS = {"planned": "Will be done", "imported": "Imported", "skipped": "Skipped", "reconciled": "Reconciled",
           "report": "Report saved", "client": "Client added", "error": "Problem", "cancelled": "Cancelled"}


class BatchPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.result = None
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Batch processing", "Import, reconcile and save the reports for many clients "
                                                      "and months in one go."))
        frame, fl = card()
        info = QLabel(HELP)
        info.setWordWrap(True)
        fl.addWidget(info)
        row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Batch folder")
        browse = QPushButton("Choose folder…")
        browse.clicked.connect(self.choose)
        example = QPushButton("Create example folder…")
        example.setToolTip("Creates a folder with the demo client's April 2025 files, to try batch processing")
        example.clicked.connect(self.make_example)
        row.addWidget(QLabel("Folder"))
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        row.addWidget(example)
        fl.addLayout(row)
        opts = QHBoxLayout()
        self.create_clients = QCheckBox("Add clients that do not exist yet (name taken from the folder)")
        self.pdf = QCheckBox("Also save PDF reports")
        self.rerun = QCheckBox("Reconcile again even if no new file")
        for w in (self.create_clients, self.pdf, self.rerun):
            opts.addWidget(w)
        opts.addStretch()
        fl.addLayout(opts)
        buttons = QHBoxLayout()
        self.check_btn = QPushButton("Check folder")
        self.check_btn.setToolTip("Lists what would be imported, without changing anything")
        self.check_btn.clicked.connect(lambda: self.start(dry_run=True))
        self.run_btn = primary("▶ Run batch")
        self.run_btn.clicked.connect(lambda: self.start(dry_run=False))
        self.open_btn = QPushButton("Open summary")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_summary)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        for w in (self.check_btn, self.run_btn, self.open_btn):
            buttons.addWidget(w)
        buttons.addWidget(self.status, 1)
        fl.addLayout(buttons)
        lay.addWidget(frame)
        lay.addWidget(section("Result"))
        self.model = RowsModel(["Client folder", "Month", "File / reconciliation", "Result", "Detail"],
                               colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)
        can = state.can("import") and state.can("reconcile")
        self.run_btn.setEnabled(can)
        self.create_clients.setEnabled(state.can("manage_clients"))
        if not can:
            self.status.setText("Your login may only check the folder; running a batch needs import and "
                                "reconcile rights.")

    def _color(self, row, col):
        if col != 3:
            return None
        c = COLORS.get(self.model.rows[row][5] if len(self.model.rows[row]) > 5 else "")
        return QColor(c) if c else None

    def choose(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Batch folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def make_example(self, parent_dir: str | None = None) -> Path | None:
        from ...services.batch import write_example

        parent_dir = parent_dir or QFileDialog.getExistingDirectory(self, "Where to create the example folder")
        if not parent_dir:
            return None
        out = write_example(Path(parent_dir) / "FIN TAX PRO batch example")
        self.folder.setText(str(out))
        self.status.setText(f"Example folder created: {out}. Tick 'Add clients that do not exist yet' if the demo "
                            "client is not in the program, then click Run batch.")
        return out

    def start(self, dry_run: bool) -> None:
        from ...services.batch import BatchService

        folder = self.folder.text().strip()
        if not folder:
            QMessageBox.information(self, "Batch processing", "Choose the batch folder first.")
            return
        title = "Checking the batch folder" if dry_run else "Batch processing"
        task = run_task(self, title, BatchService(self.state.db).run, folder, user=self.state.user,
                        pdf=self.pdf.isChecked(), rerun=self.rerun.isChecked(), dry_run=dry_run,
                        create_clients=self.create_clients.isChecked() and self.state.can("manage_clients"))
        if not task.ok:
            QMessageBox.warning(self, "Batch processing", task.message)
            return
        self.show_result(task.result_value, dry_run)
        if not dry_run:
            self.state.notify()

    def show_result(self, res, dry_run: bool) -> None:
        self.result = res
        self.model.set_rows([[r.client, r.period, r.item, ACTIONS.get(r.action, r.action), r.detail, r.action]
                             for r in res.rows])
        self.table.fit(420)
        self.open_btn.setEnabled(res.summary_path is not None)
        if dry_run:
            n = res.count("planned")
            self.status.setText(f"Check only – nothing changed. {n} item(s) would be done, {res.count('skipped')} "
                                f"skipped, {res.count('error')} problem(s).")
        else:
            self.status.setText(res.text().capitalize() + ". Summary: " + str(res.summary_path))

    def open_summary(self) -> None:
        if self.result is not None and self.result.summary_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.summary_path)))
