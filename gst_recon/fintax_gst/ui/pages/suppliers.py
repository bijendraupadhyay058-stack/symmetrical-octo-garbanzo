"""Vendor-wise reconciliation with drill-down and the vendor follow-up register."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QSplitter, QVBoxLayout, QWidget,
)

from ...engine.summary import supplier_summary
from ...services.common import ServiceError
from ...services.followup import FOLLOWUP_STATUSES
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, LinesFilter, LinesModel, RowsModel, Table, card, page_header, primary, sortable

SORTS = [("Highest ITC difference", "itc_difference"), ("Highest taxable value", "taxable"),
         ("Most missing invoices", "missing"), ("Highest ITC exposure", "exposure"), ("Supplier name", "name")]


class SuppliersPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        self.gstin: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        self.header = page_header("Suppliers", "Supplier-wise reconciliation of the selected run")
        lay.addWidget(self.header)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Sort by"))
        self.sort_cb = QComboBox()
        self.sort_cb.addItems([s for s, _ in SORTS])
        self.sort_cb.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.sort_cb)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter suppliers…")
        bar.addWidget(self.search, 1)
        self.due_lbl = QLabel()
        self.due_lbl.setObjectName("Warn")
        bar.addWidget(self.due_lbl)
        lay.addLayout(bar)

        vsplit = QSplitter(Qt.Vertical)
        self.model = RowsModel(
            ["Supplier GSTIN", "Supplier", "Books Docs", "2B Docs", "Books Taxable", "2B Taxable", "Books ITC",
             "2B ITC", "ITC Difference", "Missing in 2B", "Missing in Books", "Duplicates", "Unresolved",
             "ITC at Risk", "Follow-up"],
            kinds=["text", "text", "int", "int", "money", "money", "money", "money", "money", "int", "int", "int",
                   "int", "money", "text"])
        self.proxy = sortable(self.model)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = Table()
        self.table.setModel(self.proxy)
        self.table.selectionModel().selectionChanged.connect(self._selected)
        vsplit.addWidget(self.table)

        bottom = QSplitter(Qt.Horizontal)
        self.lines_model = LinesModel()
        self.lines_proxy = LinesFilter()
        self.lines_proxy.setSourceModel(self.lines_model)
        self.lines_table = Table()
        self.lines_table.setModel(self.lines_proxy)
        bottom.addWidget(self.lines_table)
        bottom.addWidget(self._vendor_form())
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 2)
        vsplit.addWidget(bottom)
        lay.addWidget(vsplit, 1)
        for sig in (state.runChanged, state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()  # loads when first shown

    def _vendor_form(self) -> QWidget:
        frame, lay = card()
        self.vendor_title = QLabel("<b>Vendor follow-up</b> – select a supplier")
        lay.addWidget(self.vendor_title)
        form = QFormLayout()
        self.v_name, self.v_contact, self.v_email, self.v_phone = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.v_status = QComboBox()
        self.v_status.addItem("")
        self.v_status.addItems(FOLLOWUP_STATUSES)
        self.v_next_set = QCheckBox("Set")
        self.v_next = QDateEdit()
        self.v_next.setCalendarPopup(True)
        self.v_next.setDisplayFormat("dd-MM-yyyy")
        self.v_next.setDate(QDate.currentDate().addDays(7))
        nd = QHBoxLayout()
        nd.addWidget(self.v_next_set)
        nd.addWidget(self.v_next)
        self.v_remarks = QPlainTextEdit()
        self.v_remarks.setFixedHeight(70)
        for label, w in (("Name", self.v_name), ("Contact person", self.v_contact), ("Email", self.v_email),
                         ("Phone", self.v_phone), ("Follow-up status", self.v_status), ("Next follow-up", nd),
                         ("Remarks", self.v_remarks)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.v_save = primary("Save vendor follow-up")
        self.v_save.clicked.connect(self.save_vendor)
        self.v_save.setEnabled(False)
        lay.addWidget(self.v_save)
        lay.addStretch()
        return frame

    def reload(self) -> None:
        st = self.state
        self.vendors = st.vendors.all(st.client.id) if st.client else {}
        due = st.vendors.due(st.client.id) if st.client else []
        self.due_lbl.setText(f"{len(due)} vendor follow-up(s) due" if due else "")
        if st.run_id is None:
            self.model.set_rows([])
            self.lines_model.set_lines([])
            return
        ctx = st.run_context()
        self.lines = ctx.result.lines
        self.header.subtitle.setText(f"Run #{ctx.run.id} · {ctx.run.period_from} to {ctx.run.period_to} · "
                                     "select a supplier to drill down to its invoices")
        key = SORTS[self.sort_cb.currentIndex()][1]
        rows, payload = [], []
        for r in supplier_summary(self.lines, key):
            v = self.vendors.get(r.gstin)
            rows.append([r.gstin, (v.name if v and v.name else r.name), r.books.count, r.gstr2b.count,
                         r.books.taxable, r.gstr2b.taxable, r.books.itc, r.gstr2b.itc, r.itc_difference,
                         r.missing_in_2b, r.missing_in_books, r.duplicates, r.unresolved, r.itc_at_risk,
                         v.followup_status if v else ""])
            payload.append(r.gstin)
        self.model.set_rows(rows, payload)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.proxy.sort(-1)
        self.table.fit(240)
        self.lines_model.set_lines(self.lines)
        self.select(self.gstin)

    def select(self, gstin: str | None) -> None:
        for r in range(self.proxy.rowCount()):
            if self.proxy.index(r, 0).data(OBJECT_ROLE) == gstin:
                self.table.selectRow(r)
                return
        self._show(None)

    def _selected(self, *_) -> None:
        rows = self.table.selectionModel().selectedRows()
        self._show(self.proxy.index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None)

    def _show(self, gstin: str | None) -> None:
        self.gstin = gstin
        self.lines_proxy.gstin = gstin or "-"
        self.lines_proxy.refresh()
        self.lines_table.fit(200)
        self.v_save.setEnabled(gstin is not None)
        v = self.vendors.get(gstin) if gstin else None
        name = next((ln.supplier_name for ln in getattr(self, "lines", []) if ln.supplier_gstin == gstin), "")
        self.vendor_title.setText(f"<b>Vendor follow-up</b> – {gstin}" if gstin else
                                  "<b>Vendor follow-up</b> – select a supplier")
        self.v_name.setText(v.name if v and v.name else name)
        self.v_contact.setText(v.contact_person if v else "")
        self.v_email.setText(v.email if v else "")
        self.v_phone.setText(v.phone if v else "")
        self.v_status.setCurrentText(v.followup_status if v else "")
        self.v_next_set.setChecked(bool(v and v.next_followup))
        if v and v.next_followup:
            self.v_next.setDate(QDate(v.next_followup.year, v.next_followup.month, v.next_followup.day))
        self.v_remarks.setPlainText(v.remarks if v else "")

    def save_vendor(self) -> None:
        if not (self.gstin and self.state.client):
            return
        d = self.v_next.date()
        try:
            self.state.vendors.upsert(
                self.state.client.id, self.gstin, self.state.user, name=self.v_name.text().strip(),
                contact_person=self.v_contact.text().strip(), email=self.v_email.text().strip(),
                phone=self.v_phone.text().strip(), followup_status=self.v_status.currentText(),
                next_followup=date(d.year(), d.month(), d.day()) if self.v_next_set.isChecked() else None,
                remarks=self.v_remarks.toPlainText().strip())
        except ServiceError as exc:
            QMessageBox.warning(self, "Vendor", str(exc))
            return
        self.reload()
