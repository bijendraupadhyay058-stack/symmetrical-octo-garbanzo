"""180-day payment rule (Rule 37): purchase bills not paid within 180 days, ITC to reverse and to re-claim."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from ...core.money import ZERO, fmt_inr
from ...services.common import ServiceError
from ...services.rule37 import STATUSES
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, sortable

COLORS = {"Reverse ITC": "#FFCDD2", "Paid late – re-claim": "#FFF3C4", "Not yet due": "#ECEFF1",
          "Paid in time": "#C8E6C9"}
ALL = "All bills"


def _pydate(e: QDateEdit) -> date:
    d = e.date()
    return date(d.year(), d.month(), d.day())


def import_payments_dialog(parent, state: AppState, path: str | None = None):
    """Choose and import a payment register for the current client; tells the user the outcome."""
    from ...importers.readers import UnsupportedFileError
    from ...services.rule37 import Rule37Service

    if state.client is None:
        return None
    path = path or QFileDialog.getOpenFileName(parent, "Payment register", "",
                                               "Payment register (*.xlsx *.xlsm *.csv *.xml)")[0]
    if not path:
        return None
    try:
        sf, result = Rule37Service(state.db).import_payments(state.client.id, path, state.user)
    except (ServiceError, UnsupportedFileError) as exc:
        QMessageBox.warning(parent, "Payment register", str(exc))
        return None
    skipped = "".join(f"\n• row {r}: {why}" for r, why in result.ignored[:8])
    more = f"\n… and {len(result.ignored) - 8} more" if len(result.ignored) > 8 else ""
    QMessageBox.information(parent, "Payment register", f"{len(result.rows)} payment(s) imported, "
                            f"Rs. {fmt_inr(result.total)} in all. The 180-day rule page shows the bills not paid "
                            "in time." + (f"\n\nNot imported:{skipped}{more}" if result.ignored else ""))
    state.notify()
    return sf


class MarkPaidDialog(QDialog):
    def __init__(self, parent, bill):
        super().__init__(parent)
        self.setWindowTitle("Mark bill as paid")
        form = QFormLayout(self)
        form.addRow("Bill", QLabel(f"{bill.supplier} · {bill.invoice_no} dated {bill.invoice_date:%d-%m-%Y}"))
        self.when = QDateEdit(QDate.currentDate())
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd-MM-yyyy")
        self.amount = QLineEdit(str(bill.unpaid_now))
        self.note = QLineEdit()
        self.note.setPlaceholderText("e.g. cheque / UTR number")
        form.addRow("Paid on", self.when)
        form.addRow("Amount paid", self.amount)
        form.addRow("Note", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[date, Decimal, str]:
        return _pydate(self.when), Decimal(self.amount.text().replace(",", "").strip()), self.note.text().strip()


class Rule37Page(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.bills = []
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header(
            "180-day payment rule", "Purchase bills not paid to the supplier within 180 days of the invoice date: "
            "the ITC on the unpaid part is reversed (GSTR-3B 4(B)(2)) with interest, and claimed again when paid "
            "(Rule 37). Import the payment register, or mark bills as paid."))
        bar = QHBoxLayout()
        self.as_of = QDateEdit(QDate.currentDate())
        self.as_of.setCalendarPopup(True)
        self.as_of.setDisplayFormat("dd-MM-yyyy")
        self.as_of.dateChanged.connect(lambda _d: self.reload())
        self.filter = QComboBox()
        self.filter.addItems([ALL, *STATUSES])
        self.filter.currentIndexChanged.connect(lambda _i: self._fill())
        self.import_btn = primary("Import payment register…")
        self.import_btn.clicked.connect(lambda: self.import_payments())
        self.paid_btn = QPushButton("Mark as paid…")
        self.paid_btn.clicked.connect(lambda: self.mark_paid())
        self.record_btn = QPushButton("Record reversals in claim register")
        self.record_btn.setToolTip("Adds the 'Reverse ITC' bills shown to the ITC claim register (ITC review page) "
                                   "for their reversal month – only bills whose ITC is recorded there as claimed")
        self.record_btn.clicked.connect(lambda: self.record_reversals())
        export = QPushButton("Export to Excel…")
        export.clicked.connect(lambda: self.export())
        journals = QPushButton("Tally journals…")
        journals.setToolTip("The month's 180-day reversals and re-claims as journal vouchers for TallyPrime")
        journals.clicked.connect(lambda: self.tally_journals())
        for w in (QLabel("As on"), self.as_of, QLabel("Show"), self.filter, self.import_btn, self.paid_btn,
                  self.record_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(journals)
        bar.addWidget(export)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.model = RowsModel(["Status", "Supplier", "GSTIN", "Invoice no", "Date", "Bill value", "ITC", "Day 180",
                                "Unpaid on day 180", "Unpaid now", "ITC to reverse", "Reverse in", "Paid in full on",
                                "ITC to re-claim", "Re-claim in", "Interest (est.)"],
                               kinds=["text", "text", "text", "text", "date", "money", "money", "date", "money",
                                      "money", "money", "text", "date", "money", "text", "money"],
                               colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _svc(self):
        from ...services.rule37 import Rule37Service

        return Rule37Service(self.state.db)

    def _color(self, row, col):
        return QColor(COLORS.get(self.model.rows[row][0], "#FFFFFF")) if col == 0 else None

    def reload(self) -> None:
        st = self.state
        can = st.client is not None and st.can("import")
        for b in (self.import_btn, self.paid_btn):
            b.setEnabled(can)
        self.record_btn.setEnabled(st.client is not None and st.can("claim"))
        if st.client is None:
            self.bills = []
            self.model.set_rows([])
            self.summary.setText("Select a client.")
            return
        svc = self._svc()
        self.bills = svc.track(st.client.id, _pydate(self.as_of))
        unmatched = svc.unmatched_payments(st.client.id)
        rev = [b for b in self.bills if b.status == "Reverse ITC"]
        late = [b for b in self.bills if b.status == "Paid late – re-claim"]
        periods = sorted({b.reversal_period for b in rev + late})
        parts = [f"<b>ITC to reverse: Rs. {fmt_inr(sum((b.itc_to_reverse for b in rev + late), ZERO))}</b> "
                 f"({len(rev) + len(late)} bill(s){', in ' + ', '.join(periods) if periods else ''})",
                 f"ITC to re-claim after late payment: Rs. {fmt_inr(sum((b.itc_to_reclaim for b in late), ZERO))}",
                 f"interest estimate: Rs. {fmt_inr(sum((b.interest for b in rev + late), ZERO))}",
                 f"{sum(1 for b in self.bills if b.status == 'Not yet due')} bill(s) not yet due"]
        if unmatched:
            names = ", ".join(sorted({p.party_name for p in unmatched})[:5])
            parts.append(f"<span style='color:#C62828'>{len(unmatched)} payment(s) not matched to any supplier "
                         f"(name spelt differently?): {names}</span>")
        self.summary.setText(" · ".join(parts) if self.bills else
                             "No purchase bills imported for this client yet.")
        self._fill()

    def _fill(self) -> None:
        f = self.filter.currentText()
        shown = [b for b in self.bills if f == ALL or b.status == f]
        self.model.set_rows([[b.status, b.supplier, b.supplier_gstin, b.invoice_no, b.invoice_date, b.value, b.itc,
                              b.day180, b.unpaid_at_day180, b.unpaid_now, b.itc_to_reverse, b.reversal_period,
                              b.paid_in_full_on, b.itc_to_reclaim, b.reclaim_period, b.interest] for b in shown],
                            shown)
        self.table.fit(260)

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    # --------------------------------------------------------------- actions
    def import_payments(self, path: str | None = None):
        return import_payments_dialog(self, self.state, path)

    def mark_paid(self, values: tuple[date, Decimal, str] | None = None) -> bool:
        b = self._selected()
        if b is None:
            QMessageBox.information(self, "Mark as paid", "Select a bill in the list first.")
            return False
        if values is None:
            dlg = MarkPaidDialog(self, b)
            if dlg.exec() != QDialog.Accepted:
                return False
            try:
                values = dlg.values()
            except InvalidOperation:
                QMessageBox.warning(self, "Mark as paid", "The amount is not a number.")
                return False
        try:
            self._svc().mark_paid(self.state.client.id, b.invoice_id, values[0], values[1], values[2],
                                  self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Mark as paid", str(exc))
            return False
        self.state.notify()
        return True

    def record_reversals(self) -> tuple[int, list] | None:
        due = [b for b in self.bills if b.status == "Reverse ITC"]
        if not due:
            QMessageBox.information(self, "Record reversals", "No bill needs a reversal as on this date.")
            return None
        if QMessageBox.question(self, "Record reversals", f"Record the reversal of ITC on {len(due)} unpaid bill(s) "
                                "in the ITC claim register, each in its reversal month?") != QMessageBox.Yes:
            return None
        done, skipped = self._svc().record_reversals(self.state.client.id, due, self.state.user)
        text = f"{done} reversal(s) recorded."
        if skipped:
            text += f"\n\n{len(skipped)} not recorded (ITC not recorded as claimed in the claim register):\n" + \
                "\n".join(f"• {no}" for no, _why in skipped[:10])
        QMessageBox.information(self, "Record reversals", text)
        self.state.notify()
        return done, skipped

    def tally_journals(self, show: bool = True):
        if self.state.client is None:
            return None
        from ..dialogs.tally_journals import TallyJournalDialog

        d = _pydate(self.as_of)
        dlg = TallyJournalDialog(self, self.state, f"{d:%Y-%m}", "rule37")
        if show:
            dlg.exec()
        return dlg

    def export(self, path: str | None = None):
        if not self.bills:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Export 180-day rule", "rule37_180_days.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        name = self.state.client.name if self.state.client else ""
        return self._svc().export_xlsx(self.bills, path, f"180-day payment rule – {name} – as on "
                                                         f"{_pydate(self.as_of):%d-%m-%Y}")
