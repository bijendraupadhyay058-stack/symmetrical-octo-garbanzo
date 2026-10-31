"""Rule 42/43 tab of the GSTR-3B & annual page: common credit reversal of a month, capital goods, year-end."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...compliance.rule42 import HEADS
from ...core.money import fmt_inr
from ...itc.annual import fy_months
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import OBJECT_ROLE, RowsModel, Table, primary, section, sortable


def _dec(text: str) -> Decimal:
    t = text.replace(",", "").strip()
    return Decimal(t) if t else Decimal(0)


class CapitalGoodDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Common capital good (Rule 43)")
        form = QFormLayout(self)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("e.g. Generator, delivery van")
        self.inv = QLineEdit()
        self.when = QDateEdit(QDate.currentDate())
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd-MM-yyyy")
        self.amounts = {h: QLineEdit() for h in HEADS}
        form.addRow("Description", self.desc)
        form.addRow("Invoice no", self.inv)
        form.addRow("Invoice date", self.when)
        for h, e in self.amounts.items():
            e.setPlaceholderText("0.00")
            form.addRow(f"ITC – {h.upper()}", e)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        d = self.when.date()
        return {"description": self.desc.text(), "invoice_no": self.inv.text().strip(),
                "invoice_date": date(d.year(), d.month(), d.day()), **{h: _dec(e.text()) for h, e in self.amounts.items()}}


class Rule42Tab(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.working = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("For clients with both taxable and exempt (nil-rated, exempt, non-GST) sales: the common "
                             "credit to reverse each month (Rules 42 and 43). Saving a month puts its reversal into "
                             "the GSTR-3B draft at 4(B)(1)."))
        row = QHBoxLayout()
        self.month = QComboBox()
        self.month.setMinimumWidth(110)
        show = primary("Show")
        show.clicked.connect(lambda: self.show_month())
        self.t = {k: QLineEdit() for k in ("t1", "t2", "t4")}
        for k, e in self.t.items():
            e.setPlaceholderText("0.00")
            e.setMaximumWidth(120)
        self.non_business = QCheckBox("Common inputs also used for non-business purposes (5 %)")
        self.save_btn = QPushButton("Save month")
        self.save_btn.clicked.connect(lambda: self.save())
        self.clear_btn = QPushButton("Clear month")
        self.clear_btn.clicked.connect(lambda: self.clear())
        journals = QPushButton("Tally journals…")
        journals.clicked.connect(lambda: self.journals())
        for w in (QLabel("Month"), self.month, show):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(journals)
        lay.addLayout(row)
        form = QHBoxLayout()
        for label, key in (("T1 non-business only", "t1"), ("T2 exempt supplies only", "t2"),
                           ("T4 taxable supplies only", "t4")):
            form.addWidget(QLabel(label))
            form.addWidget(self.t[key])
        form.addWidget(self.non_business)
        form.addWidget(self.save_btn)
        form.addWidget(self.clear_btn)
        form.addStretch()
        lay.addLayout(form)
        self.result = RowsModel(["", "Amount"], kinds=["text", "text"])
        t1 = Table()
        t1.setModel(self.result)
        lay.addWidget(t1, 2)
        self.result_table = t1
        cg = QHBoxLayout()
        cg.addWidget(section("Common capital goods (Rule 43 – ITC spread over 60 months)"))
        cg.addStretch()
        add = QPushButton("Add capital good…")
        add.clicked.connect(lambda: self.add_good())
        rem = QPushButton("Remove")
        rem.clicked.connect(lambda: self.remove_good())
        cg.addWidget(add)
        cg.addWidget(rem)
        lay.addLayout(cg)
        self.goods = RowsModel(["Description", "Invoice", "Date", "IGST", "CGST", "SGST", "Cess"],
                               kinds=["text", "text", "date", "money", "money", "money", "money"])
        t2 = Table()
        t2.setModel(sortable(self.goods))
        lay.addWidget(t2, 1)
        self.goods_table = t2
        yr = QHBoxLayout()
        year_btn = QPushButton("Year-end re-calculation (Rule 42(2))")
        year_btn.clicked.connect(lambda: self.show_year())
        self.year_lbl = QLabel()
        self.year_lbl.setWordWrap(True)
        yr.addWidget(year_btn)
        yr.addWidget(self.year_lbl, 1)
        lay.addLayout(yr)

    def _svc(self):
        from ...services.common_credit import CommonCreditService

        return CommonCreditService(self.state.db)

    def reload(self) -> None:
        current = self.month.currentText()
        self.month.blockSignals(True)
        self.month.clear()
        self.month.addItems(fy_months(self.state.fy))
        if current:
            self.month.setCurrentText(current)
        self.month.blockSignals(False)
        can = self.state.client is not None and self.state.can("claim")
        for w in (self.save_btn, self.clear_btn):
            w.setEnabled(can)
        if self.state.client is None:
            self.goods.set_rows([])
            self.result.set_rows([])
            return
        gs = self._svc().goods(self.state.client.id)
        self.goods.set_rows([[g.description, g.invoice_no, g.invoice_date, g.igst, g.cgst, g.sgst, g.cess] for g in gs],
                            gs)
        self.goods_table.fit(260)

    def show_month(self):
        st = self.state
        if st.client is None or not self.month.currentText():
            return None
        try:
            m = self._svc().month(st.client.id, self.month.currentText())
        except ServiceError as exc:
            QMessageBox.warning(self, "Rule 42/43", str(exc))
            return None
        self.working = m
        saved = self._svc().inputs(st.client.id, m.period)
        for k, e in self.t.items():
            e.setText(str(getattr(m, k)) if getattr(m, k) else "")
        self.non_business.setChecked(m.non_business)
        rs = lambda v: "Rs. " + fmt_inr(v)  # noqa: E731
        rows = [["C1 – ITC of the month after blocked credit (Table 4)", rs(m.c1_total)],
                ["less T1 + T2 + T4 (entered)", rs(m.t1 + m.t2 + m.t4)],
                ["C2 – common credit", rs(m.c2)],
                [f"E – exempt / nil / non-GST turnover{' (of ' + m.ratio_from + ')' if m.ratio_from else ''}",
                 rs(m.exempt)],
                ["F – total turnover", rs(m.turnover)],
                ["E ÷ F", f"{m.ratio * 100:.4f} %" if m.turnover else "no turnover – nothing to apportion"],
                ["D1 = E ÷ F × C2 (Rule 42)", rs(m.d1)], ["D2 = 5 % of C2 (non-business)", rs(m.d2)],
                ["Te – capital goods (Rule 43)", rs(sum(m.te.values()))]]
        rows += [[f"Reverse in 4(B)(1) – {h.upper()}", rs(m.reversal[h])] for h in HEADS if m.reversal[h]]
        rows.append(["Total to reverse", rs(m.total) + ("" if saved or m.capital_goods else
                                                        "  (save the month to put it in the GSTR-3B draft)")])
        self.result.set_rows(rows)
        self.result_table.fit(520)
        return m

    def save(self) -> bool:
        st = self.state
        if st.client is None:
            return False
        try:
            vals = {k: _dec(e.text()) for k, e in self.t.items()}
        except InvalidOperation:
            QMessageBox.warning(self, "Rule 42/43", "An amount is not a number.")
            return False
        try:
            self._svc().save(st.client.id, self.month.currentText(), non_business=self.non_business.isChecked(),
                             user=st.user, **vals)
        except ServiceError as exc:
            QMessageBox.warning(self, "Rule 42/43", str(exc))
            return False
        self.show_month()
        st.notify()
        return True

    def clear(self) -> None:
        if self.state.client is not None:
            self._svc().clear(self.state.client.id, self.month.currentText(), self.state.user)
            self.show_month()
            self.state.notify()

    def add_good(self, values: dict | None = None) -> bool:
        if self.state.client is None:
            return False
        if values is None:
            dlg = CapitalGoodDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return False
            try:
                values = dlg.values()
            except InvalidOperation:
                QMessageBox.warning(self, "Rule 43", "An amount is not a number.")
                return False
        try:
            self._svc().add_good(self.state.client.id, user=self.state.user, **values)
        except ServiceError as exc:
            QMessageBox.warning(self, "Rule 43", str(exc))
            return False
        self.reload()
        self.state.notify()
        return True

    def remove_good(self) -> None:
        rows = self.goods_table.selectionModel().selectedRows()
        if not rows or self.state.client is None:
            return
        g = self.goods_table.model().index(rows[0].row(), 0).data(OBJECT_ROLE)
        if QMessageBox.question(self, "Rule 43", f"Remove '{g.description}' from the capital goods?") == \
                QMessageBox.Yes:
            self._svc().remove_good(self.state.client.id, g.id, self.state.user)
            self.reload()
            self.state.notify()

    def show_year(self):
        if self.state.client is None:
            return None
        y = self._svc().year(self.state.client.id, self.state.fy)
        if not y.months:
            self.year_lbl.setText(f"No month of FY {y.fy} is saved yet.")
            return y
        diff = y.difference
        what = (f"<b>Reverse Rs. {fmt_inr(diff)} more</b> with interest (about Rs. {fmt_inr(y.interest(date.today()))} "
                "to today, 18 % from 1 April)" if diff > 0 else
                f"<b>Claim Rs. {fmt_inr(-diff)} again</b>" if diff < 0 else "no difference")
        self.year_lbl.setText(f"FY {y.fy}: on the year's turnover (E ÷ F = "
                              f"{(y.exempt / y.turnover * 100 if y.turnover else 0):.4f} %) D1 + D2 = Rs. "
                              f"{fmt_inr(y.d1 + y.d2)}; reversed month by month Rs. {fmt_inr(y.reversed_monthly)} – "
                              f"{what}. Do this by the September return after the year.")
        return y

    def journals(self, show: bool = True):
        if self.state.client is None or not self.month.currentText():
            return None
        from ..dialogs.tally_journals import TallyJournalDialog

        dlg = TallyJournalDialog(self, self.state, self.month.currentText(), "rule42")
        if show:
            dlg.exec()
        return dlg
