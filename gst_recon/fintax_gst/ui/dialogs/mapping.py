"""Drag-and-select column mapping.

Source columns (left) can be dragged onto a field (right), or a field can be
selected and a column double-clicked. Amount fields accept several columns,
which are added together. The mapping can be saved as a reusable template.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...importers.column_mapping import AMOUNT_FIELDS, FIELD_LABELS, REQUIRED_FIELDS

FIELD_ORDER = [
    "supplier_gstin", "supplier_name", "invoice_no", "invoice_date", "voucher_date", "voucher_type", "doc_type",
    "taxable_value", "igst", "cgst", "sgst", "cess", "invoice_value", "rate", "place_of_supply", "reverse_charge",
    "original_invoice_no", "original_invoice_date", "itc_availability", "itc_reason", "supply_type",
    "supplier_period", "description", "ims_action",
]
MIME = "application/x-qabstractitemmodeldatalist"


class _FieldTable(QTableWidget):
    def __init__(self, dialog: "MappingDialog"):
        super().__init__(len(FIELD_ORDER), 2)
        self.dialog = dialog
        self.setHorizontalHeaderLabels(["Field", "Mapped column(s) – drop here"])
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        for r, f in enumerate(FIELD_ORDER):
            label = FIELD_LABELS[f] + (" *" if f in REQUIRED_FIELDS else "") + (" (Σ)" if f in AMOUNT_FIELDS else "")
            item = QTableWidgetItem(label)
            item.setData(Qt.UserRole, f)
            self.setItem(r, 0, item)
            self.setItem(r, 1, QTableWidgetItem(""))

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.source() is self.dialog.columns_list else e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if e.source() is self.dialog.columns_list else e.ignore()

    def dropEvent(self, e):
        row = self.indexAt(e.position().toPoint()).row()
        items = self.dialog.columns_list.selectedItems()
        if row >= 0 and items:
            for it in items:
                self.dialog.assign(FIELD_ORDER[row], it.text())
            e.acceptProposedAction()
        else:
            e.ignore()


class MappingDialog(QDialog):
    def __init__(self, parent, columns: list[str], current: dict[str, list[str]] | None = None,
                 context: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Column mapping")
        self.resize(900, 620)
        self.mapping: dict[str, list[str]] = {k: list(v) for k, v in (current or {}).items()}
        lay = QVBoxLayout(self)
        intro = QLabel(
            f"<b>Map the columns of your file{(' – ' + context) if context else ''}.</b><br>"
            "Drag a column from the left onto a field, or select a field and double-click a column. "
            "Fields marked * are required (and a taxable value or invoice value). "
            "Σ fields add up several columns, e.g. one column per tax ledger.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        body = QHBoxLayout()
        self.columns_list = QListWidget()
        self.columns_list.addItems(columns)
        self.columns_list.setDragEnabled(True)
        self.columns_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.columns_list.itemDoubleClicked.connect(self._double_click)
        left = QVBoxLayout()
        left.addWidget(QLabel("Columns in the file"))
        left.addWidget(self.columns_list)
        self.fields = _FieldTable(self)
        right = QVBoxLayout()
        right.addWidget(QLabel("Fields"))
        right.addWidget(self.fields)
        clear = QPushButton("Clear selected field")
        clear.clicked.connect(self._clear_selected)
        right.addWidget(clear)
        body.addLayout(left, 2)
        body.addLayout(right, 3)
        lay.addLayout(body)
        tpl = QHBoxLayout()
        self.save_check = QCheckBox("Save as template:")
        self.template_name = QLineEdit()
        self.template_name.setPlaceholderText("e.g. Client X – Busy purchase register")
        tpl.addWidget(self.save_check)
        tpl.addWidget(self.template_name)
        lay.addLayout(tpl)
        self.status = QLabel()
        lay.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Use this mapping")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refresh()

    def assign(self, field: str, column: str) -> None:
        cols = self.mapping.setdefault(field, [])
        if field in AMOUNT_FIELDS:
            if column not in cols:
                cols.append(column)
        else:
            self.mapping[field] = [column]
        for other, ocols in self.mapping.items():  # a column feeds one field only
            if other != field and column in ocols:
                ocols.remove(column)
        self._refresh()

    def clear(self, field: str) -> None:
        self.mapping.pop(field, None)
        self._refresh()

    def _double_click(self, item) -> None:
        row = self.fields.currentRow()
        if row >= 0:
            self.assign(FIELD_ORDER[row], item.text())

    def _clear_selected(self) -> None:
        row = self.fields.currentRow()
        if row >= 0:
            self.clear(FIELD_ORDER[row])

    def missing(self) -> list[str]:
        miss = [FIELD_LABELS[f] for f in REQUIRED_FIELDS if not self.mapping.get(f)]
        if not self.mapping.get("taxable_value") and not self.mapping.get("invoice_value"):
            miss.append("Taxable value (or invoice value)")
        return miss

    def _refresh(self) -> None:
        for r, f in enumerate(FIELD_ORDER):
            self.fields.item(r, 1).setText(" + ".join(self.mapping.get(f, [])))
        miss = self.missing()
        self.status.setText("Missing: " + ", ".join(miss) if miss else "All required fields mapped.")
        self.status.setObjectName("Error" if miss else "Ok")
        self.status.setStyleSheet("")

    def template(self) -> dict:
        return {"fields": {f: c for f, c in self.mapping.items() if c}}

    def _accept(self) -> None:
        if self.missing():
            self._refresh()
            return
        self.accept()
