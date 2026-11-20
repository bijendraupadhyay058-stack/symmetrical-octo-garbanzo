"""Purchase and sales documents of a client: enter by hand, correct or delete single documents."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from ...core.models import Source
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, sortable

REGISTERS = {"Purchases": Source.BOOKS, "Sales": Source.SALES}
DOC_TYPES = {Source.BOOKS: [("INV", "Invoice"), ("CRN", "Credit note from the supplier (purchase return / discount)"),
                            ("DBN", "Debit note from the supplier")],
             Source.SALES: [("INV", "Invoice"), ("CRN", "Credit note issued (sales return / discount)"),
                            ("DBN", "Debit note issued")]}
AMOUNTS = (("taxable_value", "Taxable value"), ("igst", "IGST"), ("cgst", "CGST"), ("sgst", "SGST/UTGST"),
           ("cess", "Cess"), ("invoice_value", "Invoice value (optional)"))


class InvoiceDialog(QDialog):
    """New document, or correction of an existing one (``values`` filled in)."""

    def __init__(self, parent, source: Source, values: dict | None = None):
        super().__init__(parent)
        self.source = source
        v = values or {}
        party = "Supplier" if source == Source.BOOKS else "Customer"
        self.setWindowTitle(("Correct " if values else "New ") + ("purchase" if source == Source.BOOKS else "sales")
                            + " document")
        form = QFormLayout(self)
        self.gstin = QLineEdit(v.get("supplier_gstin", ""))
        self.gstin.setPlaceholderText("15 characters" + ("" if source == Source.BOOKS else
                                                         " – leave blank for unregistered customers"))
        self.name = QLineEdit(v.get("supplier_name", ""))
        self.doc_type = QComboBox()
        for code, label in DOC_TYPES[source]:
            self.doc_type.addItem(label, code)
        self.doc_type.setCurrentIndex(max(self.doc_type.findData(v.get("doc_type", "INV")), 0))
        self.number = QLineEdit(v.get("invoice_no", ""))
        d = v.get("invoice_date") or date.today()
        self.date = QDateEdit(QDate(d.year, d.month, d.day))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd-MM-yyyy")
        self.period = QLineEdit(v.get("period", ""))
        self.period.setPlaceholderText("YYYY-MM – blank: the month of the date")
        self.amounts = {}
        for key, _label in AMOUNTS:
            e = QLineEdit("" if v.get(key) in (None, "") else str(v.get(key)))
            e.setPlaceholderText("0.00")
            self.amounts[key] = e
        self.pos = QLineEdit(v.get("place_of_supply", ""))
        self.pos.setPlaceholderText("e.g. 27 or Maharashtra")
        self.rcm = QCheckBox("Reverse charge")
        self.rcm.setChecked(bool(v.get("reverse_charge")))
        self.supply = QLineEdit(v.get("supply_type", ""))
        self.supply.setPlaceholderText("e.g. Regular, SEZ with payment, Export (LUT), Exempt")
        self.narration = QLineEdit(v.get("description", ""))
        form.addRow(f"{party} GSTIN", self.gstin)
        form.addRow(f"{party} name", self.name)
        form.addRow("Document", self.doc_type)
        form.addRow("Number", self.number)
        form.addRow("Date", self.date)
        form.addRow("Booked in month", self.period)
        for key, label in AMOUNTS:
            form.addRow(label, self.amounts[key])
        form.addRow("Place of supply", self.pos)
        form.addRow("", self.rcm)
        if source == Source.SALES:
            form.addRow("Type of supply", self.supply)
        form.addRow("Narration", self.narration)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _check(self) -> None:
        try:
            self.values()
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Document", "An amount is not a number – use digits only, e.g. 1180.50.")
            return
        self.accept()

    def values(self) -> dict:
        d = self.date.date()
        out = {"supplier_gstin": self.gstin.text().strip().upper(), "supplier_name": self.name.text().strip(),
               "doc_type": self.doc_type.currentData(), "invoice_no": self.number.text().strip(),
               "invoice_date": date(d.year(), d.month(), d.day()), "period": self.period.text().strip() or None,
               "place_of_supply": self.pos.text().strip(), "reverse_charge": self.rcm.isChecked(),
               "supply_type": self.supply.text().strip(), "description": self.narration.text().strip()}
        for key, e in self.amounts.items():
            text = e.text().replace(",", "").strip()
            out[key] = Decimal(text) if text else None
        return out


class InvoicesPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Invoices", "Enter purchase or sales documents by hand, or correct a single "
                                              "document without importing the whole file again. Every change is "
                                              "recorded in the audit log."))
        bar = QHBoxLayout()
        self.register = QComboBox()
        self.register.addItems(list(REGISTERS))
        self.register.currentIndexChanged.connect(lambda _i: self.reload())
        self.period = QLineEdit()
        self.period.setPlaceholderText("Month YYYY-MM (blank: all)")
        self.period.setMaximumWidth(170)
        self.period.returnPressed.connect(self.reload)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search number, GSTIN or name")
        self.search.returnPressed.connect(self.reload)
        self.new_btn = primary("New document…")
        self.new_btn.clicked.connect(lambda: self.new())
        self.edit_btn = QPushButton("Correct…")
        self.edit_btn.clicked.connect(lambda: self.edit())
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.clicked.connect(lambda: self.delete())
        for w in (self.register, self.period, self.search, self.new_btn, self.edit_btn, self.delete_btn):
            bar.addWidget(w)
        bar.addStretch()
        lay.addLayout(bar)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        lay.addWidget(self.info)
        self.model = RowsModel(["Type", "GSTIN", "Party", "Number", "Date", "Month", "Taxable", "IGST", "CGST", "SGST",
                                "From"], kinds=["text", "text", "text", "text", "date", "text", "money", "money",
                                                "money", "money", "text"])
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.edit())
        lay.addWidget(self.table, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _svc(self):
        from ...services.manual_entry import ManualEntryService

        return ManualEntryService(self.state.db)

    @property
    def source(self) -> Source:
        return REGISTERS[self.register.currentText()]

    def reload(self) -> None:
        st = self.state
        can = st.client is not None and st.can("import")
        for b in (self.new_btn, self.edit_btn):
            b.setEnabled(can)
        self.delete_btn.setEnabled(st.client is not None and st.can("delete_data"))
        if st.client is None:
            self.model.set_rows([])
            self.info.setText("Select a client.")
            return
        docs = self._svc().documents(st.client.id, self.source, self.period.text().strip() or None,
                                     self.search.text())
        self.model.set_rows([[d.doc_type, d.supplier_gstin, d.supplier_name, d.invoice_no, d.invoice_date, d.period,
                              d.taxable, d.igst, d.cgst, d.sgst, d.file_name] for d in docs], docs)
        self.table.fit(260)
        self.info.setText(f"{len(docs)} document(s)" + (" (first 5,000 shown – narrow the month or search)"
                                                         if len(docs) == 5000 else ""))

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def _report(self, result, verb: str) -> None:
        text = f"Document {verb}."
        if result.warnings:
            text += "\n\nPlease check:\n" + "\n".join(f"• {w}" for w in result.warnings)
        if result.in_reconciliation:
            text += (f"\n\nIt was used in {result.in_reconciliation} reconciliation(s) – click Start Reconciliation "
                     "again for that month so the results show the correction.")
        QMessageBox.information(self, "Invoices", text)

    def new(self, values: dict | None = None) -> bool:
        st = self.state
        if st.client is None:
            return False
        if values is None:
            dlg = InvoiceDialog(self, self.source)
            if dlg.exec() != QDialog.Accepted:
                return False
            values = dlg.values()
        try:
            result = self._svc().add(st.client.id, self.source, values, st.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Invoices", str(exc))
            return False
        self._report(result, "saved")
        st.notify()
        return True

    def edit(self, values: dict | None = None) -> bool:
        doc = self._selected()
        if doc is None:
            QMessageBox.information(self, "Invoices", "Select a document in the list first.")
            return False
        if values is None:
            from ...services.manual_entry import values_of

            dlg = InvoiceDialog(self, self.source, values_of(doc))
            if dlg.exec() != QDialog.Accepted:
                return False
            values = dlg.values()
        try:
            result = self._svc().update(self.state.client.id, doc.id, values, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Invoices", str(exc))
            return False
        self._report(result, "corrected")
        self.state.notify()
        return True

    def delete(self) -> bool:
        doc = self._selected()
        if doc is None:
            QMessageBox.information(self, "Invoices", "Select a document in the list first.")
            return False
        if QMessageBox.question(self, "Invoices", f"Delete document {doc.invoice_no} of "
                                f"{doc.supplier_name or doc.supplier_gstin}? This is recorded in the audit log."
                                ) != QMessageBox.Yes:
            return False
        try:
            self._svc().delete(self.state.client.id, doc.id, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Invoices", str(exc))
            return False
        self.state.notify()
        return True
