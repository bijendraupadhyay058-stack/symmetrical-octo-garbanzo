"""Annual return pack: GSTR-9 / 9C working papers for many clients at once, with what is pending for each."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ..state import AppState
from ..widgets import RowsModel, Table, page_header, primary, section, sortable
from ..workers import run_task

FILLS = {"Final": "#C8E6C9", "Ready to review": "#E3F2FD", "Pending": "#FFF3C4", "Error": "#FFCDD2"}


class AnnualPackPage(QWidget):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.rows, self.summary = state, [], None
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Annual return pack", "For the chosen clients: bring ITC and ledger classification up "
                                                        "to date and save each client's GSTR-9 / 9C working papers, with "
                                                        "a list of what is still pending. Nothing is approved or filed "
                                                        "for you."))
        bar = QHBoxLayout()
        self.fy = QLineEdit(state.fy)
        self.fy.setMaximumWidth(90)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Folder for the packs")
        browse = QPushButton("Choose folder…")
        browse.clicked.connect(self.choose)
        self.pdf = QCheckBox("Review PDFs too")
        self.pdf.setChecked(True)
        for w in (QLabel("Financial year"), self.fy, QLabel("Folder"), self.folder, browse, self.pdf):
            bar.addWidget(w)
        lay.addLayout(bar)
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(section("Clients"))
        self.clients = QListWidget()
        left.addWidget(self.clients, 1)
        sel = QHBoxLayout()
        for text, on in (("All", True), ("None", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, v=on: self.check_all(v))
            sel.addWidget(b)
        left.addLayout(sel)
        self.run_btn = primary("▶ Make the packs")
        self.run_btn.clicked.connect(lambda: self.start())
        left.addWidget(self.run_btn)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(section("Result"))
        self.model = RowsModel(["Client", "GSTIN", "Status", "Transactions", "Unclassified", "Claims to confirm",
                                "TB pending", "Pending"], colors=lambda r, c: QColor(FILLS.get(self.model.rows[r][2],
                                                                                              "#FFFFFF")) if c == 2
                               else None)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        right.addWidget(self.table, 1)
        ob = QHBoxLayout()
        self.open_btn = QPushButton("Open summary")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self.open_summary())
        self.status = QLabel()
        self.status.setWordWrap(True)
        ob.addWidget(self.open_btn)
        ob.addWidget(self.status, 1)
        right.addLayout(ob)
        body.addLayout(right, 3)
        lay.addLayout(body, 1)
        state.clientChanged.connect(lambda *_: self.load_clients())
        self.load_clients()

    def showEvent(self, event):  # noqa: N802 - Qt name
        super().showEvent(event)
        self.fy.setText(self.state.fy)  # the year chosen in the window
        self.load_clients()

    def load_clients(self) -> None:
        self.clients.clear()
        for c in self.state.clients.list():
            if not c.active:
                continue
            item = QListWidgetItem(f"{c.name} ({c.gstin})")
            item.setData(Qt.UserRole, c.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.clients.addItem(item)

    def check_all(self, on: bool) -> None:
        for i in range(self.clients.count()):
            self.clients.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def chosen(self) -> list[int]:
        return [self.clients.item(i).data(Qt.UserRole) for i in range(self.clients.count())
                if self.clients.item(i).checkState() == Qt.Checked]

    def choose(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder for the annual packs", self.folder.text())
        if d:
            self.folder.setText(d)

    def start(self):
        from ...services.annual_pack import AnnualPackService

        ids, folder, fy = self.chosen(), self.folder.text().strip(), self.fy.text().strip()
        if not ids or not folder:
            QMessageBox.information(self, "Annual return pack", "Tick the clients and choose the folder first.")
            return None
        task = run_task(self, "Annual return pack", AnnualPackService(self.state.db).run, ids, fy, folder,
                        self.state.user, pdf=self.pdf.isChecked())
        if not task.ok:
            QMessageBox.warning(self, "Annual return pack", task.message)
            return None
        self.rows, self.summary = task.result_value
        self.model.set_rows([[r.name, r.gstin, r.status, str(r.txns), str(r.unclassified), str(r.claims_proposable),
                              str(r.ledgers_pending), "; ".join(r.pending)] for r in self.rows], self.rows)
        self.table.fit(420)
        self.open_btn.setEnabled(True)
        done = sum(1 for r in self.rows if r.status in ("Final", "Ready to review"))
        self.status.setText(f"{len(self.rows)} client(s): {done} ready to review or final, "
                            f"{sum(1 for r in self.rows if r.status == 'Pending')} with pending items. "
                            f"Summary: {Path(self.summary).name}")
        self.state.notify()
        return self.rows

    def open_summary(self) -> None:
        if self.summary:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.summary)))
