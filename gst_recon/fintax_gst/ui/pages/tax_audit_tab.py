"""GSTR-3B & annual → Tax audit: Form 3CD clause 44 and the books-vs-returns check for the year."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ...core.money import fmt_inr
from ...services.common import ServiceError
from ...services.tax_audit import TaxAuditService
from ..widgets import OBJECT_ROLE, RowsModel, Table, primary, section, sortable


class TaxAuditTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state, self.c44 = state, None
        self.svc = TaxAuditService(state.db)
        lay = QVBoxLayout(self)
        lay.addWidget(section("Form 3CD clause 44 – break-up of expenditure"))
        bar = QHBoxLayout()
        self.total = QLineEdit()
        self.total.setPlaceholderText("Total expenditure as per accounts (₹)")
        self.total.setMaximumWidth(260)
        save = QPushButton("Save total")
        save.clicked.connect(lambda: self.save_total())
        show = primary("Prepare clause 44")
        show.clicked.connect(lambda: self.refresh())
        mark = QPushButton("Mark selected as composition")
        mark.clicked.connect(lambda: self.mark(True))
        unmark = QPushButton("Unmark")
        unmark.clicked.connect(lambda: self.mark(False))
        exp = QPushButton("Export to Excel…")
        exp.clicked.connect(lambda: self.export())
        for w in (self.total, save, show, mark, unmark):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(exp)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.model = RowsModel(["GSTIN", "Supplier", "Category", "Bills", "Taxable value", "With GST", "Without GST"],
                               kinds=["text", "text", "text", "int", "money", "money", "money"],
                               colors=lambda r, _c: QColor("#FFF3C4") if self.model.rows[r][2] in (
                                   "Exempt",) else None)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 2)
        lay.addWidget(section("Books vs returns – month by month"))
        self.b_model = RowsModel(["Month", "Output tax – books", "Output tax – GSTR-3B", "Difference", "ITC – books",
                                  "ITC – GSTR-2B", "ITC – GSTR-3B", "3B − books"],
                                 kinds=["text", "money", "money", "money", "money", "money", "money", "money"],
                                 colors=self._b_colour)
        bt = Table()
        bt.setModel(self.b_model)
        bt.setSortingEnabled(False)
        lay.addWidget(bt, 1)
        self.b_table = bt

    def _b_colour(self, row, col):
        v = self.b_model.rows[row][col]
        if col in (3, 7) and v is not None and abs(v) >= 1:
            return QColor("#FFCDD2")
        return None

    def refresh(self) -> None:
        st = self.state
        if st.client is None:
            self.summary.setText("Select a client.")
            return
        cfg = self.svc.settings(st.client.id, st.fy)
        if cfg.get("total_expenditure") and not self.total.text():
            self.total.setText(cfg["total_expenditure"])
        try:
            self.c44 = c = self.svc.clause44(st.client.id, st.fy)
        except ServiceError as exc:
            self.summary.setText(str(exc))
            return
        self.model.set_rows([[s.gstin, s.name, s.category, s.bills, s.taxable, s.taxed, s.untaxed]
                             for s in c.suppliers], c.suppliers)
        self.table.fit(320)

        def m(v):
            return "–" if v is None else f"₹{fmt_inr(v)}"

        self.summary.setText(
            f"<b>FY {c.fy}</b> · total {m(c.total_expenditure)} · registered: exempt {m(c.exempt)}, composition "
            f"{m(c.composition)}, others {m(c.other_registered)} (total {m(c.registered_total)}) · unregistered "
            f"{m(c.unregistered)} · not in the registers {m(c.not_in_registers)}<br>"
            + "<br>".join(f"• {n}" for n in c.notes))
        rows = self.svc.books_check(st.client.id, st.fy)
        self.b_model.set_rows([[r["period"], r["output_books"], r["output_3b"], r["output_diff"], r["itc_books"],
                                r["itc_2b"], r["itc_3b"], r["itc_diff"]] for r in rows])
        self.b_table.fit(300)

    def save_total(self) -> None:
        if self.state.client is None:
            return
        try:
            self.svc.save_settings(self.state.client.id, self.state.fy, self.total.text(), user=self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Clause 44", str(exc))
            return
        self.refresh()

    def mark(self, on: bool) -> int:
        if self.state.client is None:
            return 0
        rows = self.table.selectionModel().selectedRows()
        picked = {self.table.model().index(r.row(), 0).data(OBJECT_ROLE).gstin for r in rows}
        if not picked:
            return 0
        cur = set(self.svc.settings(self.state.client.id, self.state.fy).get("composition", []))
        cur = cur | picked if on else cur - picked
        self.svc.save_settings(self.state.client.id, self.state.fy, composition=sorted(cur), user=self.state.user)
        self.refresh()
        return len(picked)

    def export(self, path: str | None = None):
        if self.c44 is None:
            return None
        st = self.state
        path = path or QFileDialog.getSaveFileName(self, "Clause 44", f"Clause44_{st.client.gstin}_{st.fy}.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        return self.svc.export_xlsx(self.c44, st.client.name, st.client.gstin, path)
