"""PAN-level view: all GST registrations of one business (same PAN) for the financial year."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QVBoxLayout,
    QWidget,
)

from ...core.money import fmt_inr
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, section, sortable

RAG = {"red": "#FFCDD2", "amber": "#FFF3C4", "green": "#C8E6C9"}


class PanViewPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.view = None
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("PAN view", "One business with GST registrations in several states: every GSTIN "
                                              "of the PAN side by side for the financial year, with totals."))
        bar = QHBoxLayout()
        self.pan_cb = QComboBox()
        self.pan_cb.setMinimumWidth(380)
        self.pan_cb.activated.connect(lambda _i: self.show_view())
        self.single = QCheckBox("Also single-state businesses")
        self.single.toggled.connect(lambda _on: self.reload())
        export = QPushButton("Export to Excel…")
        export.clicked.connect(lambda: self.export())
        for w in (QLabel("Business (PAN)"), self.pan_cb, self.single):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(export)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(section("Registrations (double-click to open)"))
        self.model = RowsModel(["State", "GSTIN", "Name", "Months reconciled", "ITC books", "ITC GSTR-2B",
                                "ITC GSTR-3B", "ITC at risk", "Output GSTR-1", "Output GSTR-3B", "Returns overdue",
                                "Open notices"],
                               kinds=["text", "text", "text", "int", "money", "money", "money", "money", "money",
                                      "money", "int", "int"], colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.open_registration())
        tl.addWidget(self.table)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Suppliers to follow up – across the registrations"))
        self.sup_model = RowsModel(["Supplier", "GSTIN", "ITC at risk", "Invoices not in GSTR-2B",
                                    "Your registrations affected"], kinds=["text", "text", "money", "int", "text"])
        self.sup_table = Table()
        self.sup_table.setModel(sortable(self.sup_model))
        bl.addWidget(self.sup_table)
        split.addWidget(top)
        split.addWidget(bottom)
        lay.addWidget(split, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _svc(self):
        from ...services.pan_view import PanViewService

        return PanViewService(self.state.db)

    def _color(self, row, col):
        if col != 2 or self.view is None:
            return None
        reg = self.model.payload[row] if self.model.payload else None
        return QColor(RAG[reg.rag]) if reg is not None and reg.rag in RAG else None

    def reload(self) -> None:
        current = self.pan_cb.currentData()
        self.pan_cb.blockSignals(True)
        self.pan_cb.clear()
        for pan, clients in self._svc().groups(self.single.isChecked()):
            self.pan_cb.addItem(f"{clients[0].name} – PAN {pan} ({len(clients)} registration(s))", pan)
        idx = self.pan_cb.findData(current)
        if idx < 0 and self.state.client is not None:
            idx = self.pan_cb.findData(self.state.client.pan)
        self.pan_cb.setCurrentIndex(max(idx, 0))
        self.pan_cb.blockSignals(False)
        if self.pan_cb.count() == 0:
            self.view = None
            self.model.set_rows([])
            self.sup_model.set_rows([])
            self.summary.setText("No business has GST registrations in more than one state. Tick 'Also single-state "
                                 "businesses' to see the others.")
            return
        self.show_view()

    def show_view(self) -> None:
        pan = self.pan_cb.currentData()
        if not pan:
            return
        try:
            self.view = v = self._svc().view(pan, self.state.fy)
        except ServiceError as exc:
            self.summary.setText(str(exc))
            return
        self.model.set_rows([[r.state, r.gstin, r.name, r.months_reconciled, r.itc_books, r.itc_2b, r.itc_3b,
                              r.itc_at_risk, r.output_gstr1, r.output_3b, r.returns_overdue, r.notices_open]
                             for r in v.registrations], v.registrations)
        self.table.fit(300)
        self.sup_model.set_rows([[a.name, a.gstin, a.itc_at_risk, a.missing_in_2b, ", ".join(sorted(a.registrations))]
                                 for a in v.suppliers])
        self.sup_table.fit(360)
        self.summary.setText(
            f"<b>FY {v.fy} – {len(v.registrations)} registration(s)</b> · ITC as per books Rs. "
            f"{fmt_inr(v.total('itc_books'))} · GSTR-2B Rs. {fmt_inr(v.total('itc_2b'))} · GSTR-3B Rs. "
            f"{fmt_inr(v.total('itc_3b'))} · <b>ITC at risk Rs. {fmt_inr(v.total('itc_at_risk'))}</b> · "
            f"returns overdue {v.total('returns_overdue')} · suppliers to follow up {len(v.suppliers)}")

    def open_registration(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        reg = self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE)
        self.state.set_client(self.state.clients.get(reg.client_id))
        self.navigate.emit("dashboard")

    def export(self, path: str | None = None):
        if self.view is None:
            QMessageBox.information(self, "PAN view", "Choose a business first.")
            return None
        path = path or QFileDialog.getSaveFileName(self, "Export PAN view", f"PAN_{self.view.pan}_{self.view.fy}.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        name = self.view.registrations[0].name if self.view.registrations else ""
        return self._svc().export_xlsx(self.view, path, name)
