"""Ledger Mapping Master: the client's permanent classification of each Tally ledger, reused every year by Ledger
classification and ITC classification (a year's own manual classification always wins)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ...ledgers.classify import ELIGIBILITY, GST_CLASSES, GST_SOURCES
from ...services.common import ServiceError
from ...services.mapping_master import MappingMasterService
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary, sortable
from .bifurcation import BulkDialog


class MappingMasterPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.entries = state, []
        self.svc = MappingMasterService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Mapping master", "The client's permanent ledger mapping – how each Tally ledger is "
                                                    "classified – reused every year in Ledger classification and ITC "
                                                    "classification. A year's own classification always wins."))
        bar = QHBoxLayout()
        self.add_btn = primary("Add…")
        self.add_btn.clicked.connect(lambda: self.add())
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(lambda: self.edit())
        self.off_btn = QPushButton("Switch off / on")
        self.off_btn.clicked.connect(lambda: self.toggle())
        self.apply_btn = QPushButton("Apply to this year")
        self.apply_btn.setToolTip("Suggest from the master for this year's pending ledgers and every transaction not "
                                  "classified by hand")
        self.apply_btn.clicked.connect(lambda: self.apply())
        self.exp_btn = QPushButton("Export to Excel…")
        self.exp_btn.clicked.connect(lambda: self.export())
        self.imp_btn = QPushButton("Import from Excel…")
        self.imp_btn.clicked.connect(lambda: self.import_dialog())
        self.copy_btn = QPushButton("Copy from another client…")
        self.copy_btn.clicked.connect(lambda: self.copy_from())
        for b in (self.add_btn, self.edit_btn, self.off_btn, self.apply_btn, self.exp_btn, self.imp_btn, self.copy_btn):
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search ledger or classification…")
        self.find.textChanged.connect(lambda _t: self.show_rows())
        lay.addWidget(self.find)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.model = RowsModel(["Ledger", "Accounting classification", "GST nature", "GST classification", "Source",
                                "9C head", "ITC eligibility", "Active", "Origin", "Approved by", "Years in trial balance",
                                "Transactions", "Note"],
                               colors=lambda r, c: QColor("#EEEEEE") if not self.model.payload[r].m.active else None)
        self.proxy = sortable(self.model)
        self.table = Table()
        self.table.setModel(self.proxy)
        self.table.setSelectionMode(Table.ExtendedSelection)
        self.table.doubleClicked.connect(lambda _i: self.edit())
        lay.addWidget(self.table, 1)
        lay.addWidget(QLabel("The master holds classification and eligibility only – whether ITC was claimed is recorded "
                             "each year from GSTR-3B (ITC classification → Record claim)."))
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def reload(self) -> None:
        on = self.state.client is not None
        for b in (self.add_btn, self.edit_btn, self.off_btn, self.apply_btn, self.exp_btn, self.imp_btn, self.copy_btn):
            b.setEnabled(on)
        self.entries = self.svc.entries(self.state.client.id) if on else []
        active = sum(1 for e in self.entries if e.m.active)
        self.info.setText(f"{len(self.entries)} ledger mapping(s), {active} active." if on else "Select a client.")
        self.show_rows()

    def show_rows(self) -> None:
        text = self.find.text().strip().lower()
        out = [e for e in self.entries if not text or text in f"{e.m.ledger_key} {e.m.acct_class} {e.nature}".lower()]
        self.model.set_rows([[e.m.ledger_key, e.m.acct_class, e.nature, GST_CLASSES.get(e.m.gst_class, e.m.gst_class),
                              GST_SOURCES.get(e.m.gst_source, e.m.gst_source), e.m.head_9c,
                              ELIGIBILITY.get(e.m.eligibility, ""), "yes" if e.m.active else "no", e.m.source,
                              e.m.approved_by, ", ".join(e.tb_years), str(e.txns), e.m.note] for e in out], out)
        self.table.fit(240)

    def selected(self) -> list:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.payload[r] for r in rows]

    def select_ledger(self, key: str) -> None:
        from PySide6.QtCore import QItemSelectionModel

        sel = self.table.selectionModel()
        sel.clearSelection()
        for r, e in enumerate(self.model.payload or []):
            if e.m.ledger_key == key:
                sel.select(self.proxy.mapFromSource(self.model.index(r, 0)),
                           QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _changed(self) -> None:
        self.state.notify()

    def _dialog(self, entry=None) -> tuple | None:
        dlg = BulkDialog(self)
        dlg.setWindowTitle("Ledger mapping")
        name = QLineEdit(entry.m.ledger_key if entry else "")
        note = QLineEdit(entry.m.note if entry else "")
        dlg.layout().insertRow(0, "Ledger (as in Tally)", name)
        dlg.layout().insertRow(dlg.layout().rowCount() - 1, "Note", note)
        if entry:
            m = entry.m
            dlg.acct.setEditText(m.acct_class)
            dlg.gst.setCurrentIndex(dlg.gst.findData(m.gst_class))
            dlg.src.setCurrentIndex(dlg.src.findData(m.gst_source))
            dlg.head.setCurrentIndex(max(dlg.head.findData(m.head_9c), 0))
            dlg.elig.setCurrentIndex(max(dlg.elig.findData(m.eligibility), 0))
        if dlg.exec() != QDialog.Accepted:
            return None
        return (name.text(), dlg.acct.currentText(), dlg.gst.currentData(), dlg.src.currentData(),
                dlg.head.currentData(), dlg.elig.currentData(), note.text())

    def add(self, values: tuple | None = None) -> bool:
        values = values or self._dialog()
        if not values:
            return False
        name, acct, gst, src, head, elig, note = values
        try:
            self.svc.save(self.state.client.id, name, acct, gst, self.state.user, src, head, elig, note)
        except ServiceError as exc:
            QMessageBox.warning(self, "Mapping master", str(exc))
            return False
        self._changed()
        return True

    def edit(self, values: tuple | None = None) -> bool:
        sel = self.selected()
        if len(sel) != 1:
            QMessageBox.information(self, "Mapping master", "Select one ledger mapping.")
            return False
        values = values or self._dialog(sel[0])
        if not values:
            return False
        if values[0].strip().lower() != sel[0].m.ledger_key:
            QMessageBox.information(self, "Mapping master", "The ledger name cannot be changed – add a new mapping and "
                                    "switch this one off.")
            return False
        return self.add(values)

    def toggle(self) -> int:
        sel = self.selected()
        if not sel:
            return 0
        n = self.svc.set_active([e.m.id for e in sel], not sel[0].m.active, self.state.user)
        self._changed()
        return n

    def apply(self) -> dict:
        st = self.state
        res = self.svc.apply(st.client.id, st.fy, st.user)
        self._changed()
        QMessageBox.information(self, "Mapping master", f"{st.fy}: {res['ledgers']} trial-balance ledger(s) suggested, "
                                f"{res['transactions']} transaction(s) re-suggested. Ledgers and transactions you "
                                "classified by hand are unchanged; suggestions still need your approval.")
        return res

    def export(self, path: str | None = None, open_file: bool = True):
        st = self.state
        path = path or QFileDialog.getSaveFileName(self, "Export mapping master",
                                                   f"Ledger_mapping_{st.client.gstin}.xlsx", "Excel (*.xlsx)")[0]
        if not path:
            return None
        out = self.svc.export_xlsx(st.client.id, path)
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out))))
        return out

    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import mapping master", "", "Excel (*.xlsx)")
        if path:
            self.import_path(path)

    def import_path(self, path) -> tuple[int, list[str]]:
        try:
            n, errors = self.svc.import_xlsx(self.state.client.id, path, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Mapping master", str(exc))
            return 0, [str(exc)]
        self._changed()
        QMessageBox.information(self, "Mapping master", f"{n} mapping(s) saved." + (
            "\n\nNot saved:\n" + "\n".join(errors[:15]) if errors else ""))
        return n, errors

    def copy_from(self, from_client_id: int | None = None, overwrite: bool = False) -> tuple[int, int]:
        st = self.state
        if from_client_id is None:
            others = [c for c in st.clients.list() if c.id != st.client.id]
            if not others:
                QMessageBox.information(self, "Mapping master", "There is no other client to copy from.")
                return 0, 0
            names = [f"{c.name} ({c.gstin})" for c in others]
            choice, ok = QInputDialog.getItem(self, "Copy from another client", "Client:", names, 0, False)
            if not ok:
                return 0, 0
            from_client_id = others[names.index(choice)].id
            overwrite = QMessageBox.question(
                self, "Copy from another client", "Replace mappings this client already has for the same ledgers?\n"
                "(No = keep this client's own mappings)") == QMessageBox.Yes
        try:
            copied, kept = self.svc.copy_from(st.client.id, from_client_id, st.user, overwrite)
        except ServiceError as exc:
            QMessageBox.warning(self, "Mapping master", str(exc))
            return 0, 0
        self._changed()
        QMessageBox.information(self, "Mapping master", f"{copied} mapping(s) copied, {kept} of this client's own kept.")
        return copied, kept


__all__ = ["MappingMasterPage", "Qt"]
