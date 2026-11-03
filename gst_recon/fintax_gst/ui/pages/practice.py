"""Fees & tasks: the firm's staff task list (with return-filing tasks from the due dates) and fee billing."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from ...core.money import ZERO, fmt_inr
from ...services.billing import MODES, BillingService, FirmProfile
from ...services.common import ServiceError
from ...services.tasks import TaskService
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, section, sortable

ALL = "Everyone"
STATE_COLOURS = {"Overdue": "#FFCDD2", "Due today": "#FFE0B2", "Due soon": "#FFF3C4", "Done": "#E8F5E9"}


def _date_edit(d: date | None = None) -> QDateEdit:
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd-MM-yyyy")
    d = d or date.today()
    w.setDate(QDate(d.year, d.month, d.day))
    return w


def _py(w: QDateEdit) -> date:
    q = w.date()
    return date(q.year(), q.month(), q.day())


class FirmProfileDialog(QDialog):
    def __init__(self, parent, prof: FirmProfile):
        super().__init__(parent)
        self.setWindowTitle("Firm profile (for fee invoices)")
        form = QFormLayout(self)
        self.name, self.gstin, self.pan = QLineEdit(prof.name), QLineEdit(prof.gstin), QLineEdit(prof.pan)
        self.address = QPlainTextEdit(prof.address)
        self.address.setFixedHeight(60)
        self.email, self.phone = QLineEdit(prof.email), QLineEdit(prof.phone)
        self.bank = QPlainTextEdit(prof.bank)
        self.bank.setFixedHeight(50)
        self.bank.setPlaceholderText("Bank name, account number, IFSC / UPI ID")
        self.prefix, self.sac, self.rate = QLineEdit(prof.prefix), QLineEdit(prof.sac), QLineEdit(prof.gst_rate)
        self.gstin.setPlaceholderText("leave blank if the firm is not registered (bill of supply)")
        self.due = QSpinBox()
        self.due.setRange(0, 180)
        self.due.setValue(int(prof.due_days))
        self.due.setSuffix(" days to pay")
        for label, w in (("Firm name", self.name), ("Address", self.address), ("GSTIN", self.gstin), ("PAN", self.pan),
                         ("E-mail", self.email), ("Phone", self.phone), ("Bank details", self.bank),
                         ("Invoice number prefix", self.prefix), ("SAC", self.sac), ("GST rate %", self.rate),
                         ("Payment terms", self.due)):
            form.addRow(label, w)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def profile(self) -> FirmProfile:
        return FirmProfile(self.name.text().strip(), self.address.toPlainText().strip(), self.gstin.text().strip(),
                           "", self.pan.text().strip().upper(), self.email.text().strip(), self.phone.text().strip(),
                           self.bank.toPlainText().strip(), self.prefix.text().strip(), self.sac.text().strip(),
                           self.rate.text().strip() or "0", self.due.value())


class FeeInvoiceDialog(QDialog):
    def __init__(self, parent, clients: list, client_id: int | None):
        super().__init__(parent)
        self.setWindowTitle("New fee invoice")
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.client = QComboBox()
        for c in clients:
            self.client.addItem(f"{c.name} · {c.gstin}", c.id)
        if client_id:
            self.client.setCurrentIndex(max(self.client.findData(client_id), 0))
        self.when = _date_edit()
        form.addRow("Client", self.client)
        form.addRow("Invoice date", self.when)
        lay.addLayout(form)
        self.lines = QTableWidget(6, 2)
        self.lines.setHorizontalHeaderLabels(["Description of service", "Amount (₹)"])
        self.lines.setColumnWidth(0, 440)
        lay.addWidget(self.lines, 1)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Note on the invoice (optional)")
        lay.addWidget(self.notes)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def values(self) -> tuple[int, list[tuple[str, str]], date, str]:
        rows = []
        for r in range(self.lines.rowCount()):
            t, a = (self.lines.item(r, c) for c in (0, 1))
            text, amount = (t.text() if t else ""), (a.text() if a else "")
            if text.strip() or amount.strip():
                rows.append((text, amount))
        return self.client.currentData(), rows, _py(self.when), self.notes.text().strip()


class ReceiptDialog(QDialog):
    def __init__(self, parent, clients: list, invoices: list, client_id: int | None):
        super().__init__(parent)
        self.setWindowTitle("Record fee received")
        self.invoices = invoices
        form = QFormLayout(self)
        self.client = QComboBox()
        for c in clients:
            self.client.addItem(c.name, c.id)
        if client_id:
            self.client.setCurrentIndex(max(self.client.findData(client_id), 0))
        self.invoice = QComboBox()
        self.client.currentIndexChanged.connect(lambda _i: self._fill())
        self.when = _date_edit()
        self.amount, self.tds, self.ref = QLineEdit(), QLineEdit("0"), QLineEdit()
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        for label, w in (("Client", self.client), ("Against invoice", self.invoice), ("Received on", self.when),
                         ("Amount received (₹)", self.amount), ("TDS deducted by client (₹)", self.tds),
                         ("Mode", self.mode), ("UTR / cheque no.", self.ref)):
            form.addRow(label, w)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)
        self._fill()

    def _fill(self) -> None:
        self.invoice.clear()
        self.invoice.addItem("— on account (no particular invoice) —", None)
        for v in self.invoices:
            if v.inv.client_id == self.client.currentData() and v.balance > 0:
                self.invoice.addItem(f"{v.inv.number} · balance ₹{fmt_inr(v.balance)}", v.inv.id)
        if self.invoice.count() > 1:
            self.invoice.setCurrentIndex(1)


class PracticePage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.tasks_svc, self.bill = TaskService(state.db), BillingService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Fees & tasks", "Who does what by when – including the return filings of every "
                                                  "client – and the firm's fee invoices, receipts and outstanding."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tasks_tab(), "Staff tasks")
        self.tabs.addTab(self._fees_tab(), "Fees")
        lay.addWidget(self.tabs, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # --------------------------------------------------------------- tasks
    def _tasks_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.who = QComboBox()
        self.who.currentIndexChanged.connect(lambda _i: self.show_tasks())
        self.show_done = QCheckBox("Show done")
        self.show_done.toggled.connect(lambda _on: self.show_tasks())
        self.gen_period = QLineEdit(f"{date.today():%Y-%m}")
        self.gen_period.setMaximumWidth(90)
        gen = QPushButton("Create return tasks")
        gen.setToolTip("GSTR-1 / GSTR-3B filing tasks for the month for every client, assigned to its responsible "
                       "staff, with the due dates (extensions included). They close when the filing is recorded.")
        gen.clicked.connect(lambda: self.generate())
        add = primary("Add task…")
        add.clicked.connect(lambda: self.add_task())
        for x in (QLabel("Show tasks of"), self.who, self.show_done, QLabel("Month"), self.gen_period, gen):
            bar.addWidget(x)
        bar.addStretch()
        bar.addWidget(add)
        lay.addLayout(bar)
        self.t_model = RowsModel(["Due", "Status", "Task", "Client", "Assigned to", "Notes"],
                                 kinds=["date", "text", "text", "text", "text", "text"], colors=self._task_colour)
        self.t_table = Table()
        self.t_table.setModel(sortable(self.t_model))
        lay.addWidget(self.t_table, 1)
        row = QHBoxLayout()
        for text, fn in (("Mark done", lambda: self.set_done(True)), ("Reopen", lambda: self.set_done(False)),
                         ("Assign to…", lambda: self.assign()), ("Delete", lambda: self.delete_tasks())):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        self.t_info = QLabel()
        row.addWidget(self.t_info, 1)
        lay.addLayout(row)
        return w

    def _task_colour(self, row, _col):
        c = STATE_COLOURS.get(self.t_model.rows[row][1])
        return QColor(c) if c else None

    def _sel_tasks(self) -> list[int]:
        rows = self.t_table.selectionModel().selectedRows()
        return [self.t_table.model().index(r.row(), 0).data(OBJECT_ROLE).task.id for r in rows]

    def show_tasks(self) -> None:
        who = self.who.currentText()
        views = self.tasks_svc.tasks(None if who in ("", ALL) else who, self.show_done.isChecked())
        today = date.today()
        self.t_model.set_rows([[v.task.due_date, v.state(today), v.task.title, v.client, v.task.assignee,
                                v.task.notes] for v in views], views)
        self.t_table.fit(420)
        overdue = sum(1 for v in views if v.state(today) == "Overdue")
        self.t_info.setText(f"{sum(1 for v in views if v.task.status == 'open')} open task(s)"
                            + (f" · <span style='color:#C62828'><b>{overdue} overdue</b></span>" if overdue else ""))

    def generate(self, period: str | None = None):
        try:
            created, closed = self.tasks_svc.return_tasks(period or self.gen_period.text().strip(), self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Tasks", str(exc))
            return None
        self.t_info.setText(f"{created} return task(s) created" + (f", {closed} closed as filed" if closed else ""))
        self.reload()
        return created, closed

    def add_task(self, values: tuple | None = None):
        if values is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Add task")
            form = QFormLayout(dlg)
            title, who, notes = QLineEdit(), QComboBox(), QLineEdit()
            who.setEditable(True)
            who.addItems(self.tasks_svc.assignees())
            who.setCurrentText(self.state.user)
            client = QComboBox()
            client.addItem("— no client —", None)
            for c in self.state.clients.list():
                client.addItem(c.name, c.id)
            if self.state.client:
                client.setCurrentIndex(client.findData(self.state.client.id))
            due = _date_edit()
            for label, x in (("Task", title), ("Client", client), ("Assigned to", who), ("Due by", due),
                             ("Notes", notes)):
                form.addRow(label, x)
            b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            b.accepted.connect(dlg.accept)
            b.rejected.connect(dlg.reject)
            form.addRow(b)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = (title.text(), who.currentText(), _py(due), client.currentData(), notes.text())
        try:
            t = self.tasks_svc.add(values[0], self.state.user, values[1], values[2], values[3], values[4])
        except ServiceError as exc:
            QMessageBox.warning(self, "Tasks", str(exc))
            return None
        self.reload()
        return t

    def set_done(self, done: bool) -> int:
        n = self.tasks_svc.set_status(self._sel_tasks(), done, self.state.user)
        self.reload()
        return n

    def assign(self, name: str | None = None) -> int:
        ids = self._sel_tasks()
        if not ids:
            return 0
        if name is None:
            name, ok = QInputDialog.getItem(self, "Assign to", "Staff member:", self.tasks_svc.assignees(), 0, True)
            if not ok:
                return 0
        n = self.tasks_svc.reassign(ids, name, self.state.user)
        self.reload()
        return n

    def delete_tasks(self) -> int:
        ids = self._sel_tasks()
        if not ids or QMessageBox.question(self, "Tasks", f"Delete {len(ids)} task(s)?") != QMessageBox.Yes:
            return 0
        n = self.tasks_svc.delete(ids, self.state.user)
        self.reload()
        return n

    # ---------------------------------------------------------------- fees
    def _fees_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        buttons = (("Firm profile…", self.edit_profile, "settings"), ("New fee invoice…", self.new_invoice,
                                                                       "manage_clients"),
                   ("Record receipt…", self.new_receipt, "manage_clients"), ("Invoice PDF…", self.invoice_pdf, None),
                   ("E-mail invoice", self.email_invoice, "letters"), ("Cancel invoice…", self.cancel_invoice,
                                                                       "manage_clients"))
        self.fee_btns = {}
        for text, fn, perm in buttons:
            b = primary(text) if text.startswith("New") else QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            b.setEnabled(perm is None or self.state.can(perm))
            self.fee_btns[text] = b
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.f_info = QLabel()
        self.f_info.setWordWrap(True)
        lay.addWidget(self.f_info)
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(section("Fee invoices"))
        self.i_model = RowsModel(["Number", "Date", "Client", "Total", "Received", "Balance", "Status"],
                                 kinds=["text", "date", "text", "money", "money", "money", "text"])
        self.i_table = Table()
        self.i_table.setModel(sortable(self.i_model))
        tl.addWidget(self.i_table)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Outstanding fees by client"))
        self.o_model = RowsModel(["Client", "Billed", "Received", "TDS", "Balance", "Overdue (days)"],
                                 kinds=["text", "money", "money", "money", "money", "int"],
                                 colors=lambda r, _c: QColor("#FFCDD2") if (self.o_model.rows[r][5] or 0) > 30 else None)
        self.o_table = Table()
        self.o_table.setModel(sortable(self.o_model))
        bl.addWidget(self.o_table)
        split.addWidget(top)
        split.addWidget(bottom)
        lay.addWidget(split, 1)
        return w

    def show_fees(self) -> None:
        views = self.bill.invoices()
        self.i_model.set_rows([[v.inv.number, v.inv.invoice_date, v.client, v.inv.total, v.received, v.balance,
                                v.inv.status.capitalize()] for v in views], views)
        self.i_table.fit(360)
        today = date.today()
        outs = self.bill.outstanding()
        self.o_model.set_rows([[o.name, o.billed, o.received, o.tds, o.balance, o.overdue_days(today)] for o in outs],
                              outs)
        self.o_table.fit(360)
        prof = self.bill.profile()
        total = sum((o.balance for o in outs), ZERO)
        self.f_info.setText((f"Billing as <b>{prof.name}</b>" + (f" (GSTIN {prof.gstin})" if prof.gstin else
                                                                 " – not registered: bills of supply")
                             if prof.name else "<span style='color:#C62828'>Fill in the firm profile first</span>")
                            + f" · outstanding <b>₹{fmt_inr(total)}</b>")

    def _sel_invoice(self):
        rows = self.i_table.selectionModel().selectedRows()
        return self.i_table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def edit_profile(self, prof: FirmProfile | None = None) -> bool:
        if prof is None:
            dlg = FirmProfileDialog(self, self.bill.profile())
            if dlg.exec() != QDialog.Accepted:
                return False
            prof = dlg.profile()
        try:
            self.bill.save_profile(prof, self.state.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "Firm profile", str(exc))
            return False
        self.show_fees()
        return True

    def new_invoice(self, values: tuple | None = None):
        if values is None:
            dlg = FeeInvoiceDialog(self, self.state.clients.list(), self.state.client.id if self.state.client else None)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = dlg.values()
        client_id, lines, when, notes = values
        try:
            inv = self.bill.create_invoice(client_id, lines, self.state.session, when, notes)
        except ServiceError as exc:
            QMessageBox.warning(self, "Fee invoice", str(exc))
            return None
        self.reload()
        self.f_info.setText(f"Fee invoice {inv.number} for ₹{fmt_inr(inv.total)} saved.")
        return inv

    def new_receipt(self, values: dict | None = None):
        if values is None:
            dlg = ReceiptDialog(self, self.state.clients.list(), self.bill.invoices(),
                                self.state.client.id if self.state.client else None)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = {"client_id": dlg.client.currentData(), "amount": dlg.amount.text(), "received_on": _py(dlg.when),
                      "mode": dlg.mode.currentText(), "reference": dlg.ref.text(), "tds": dlg.tds.text() or "0",
                      "invoice_id": dlg.invoice.currentData()}
        try:
            r = self.bill.record_receipt(by=self.state.session, **values)
        except ServiceError as exc:
            QMessageBox.warning(self, "Fee received", str(exc))
            return None
        self.reload()
        return r

    def invoice_pdf(self, path: str | None = None, open_file: bool = True):
        v = self._sel_invoice()
        if v is None:
            QMessageBox.information(self, "Fee invoice", "Select an invoice in the list.")
            return None
        path = path or QFileDialog.getSaveFileName(self, "Save invoice", f"{v.inv.number.replace('/', '-')}.pdf",
                                                   "PDF (*.pdf)")[0]
        if not path:
            return None
        out = self.bill.invoice_pdf(v.inv.id, path)
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out

    def email_invoice(self):
        from ...services.mailer import MailService

        v = self._sel_invoice()
        if v is None or v.inv.status == "cancelled":
            QMessageBox.information(self, "Fee invoice", "Select an issued invoice in the list.")
            return None
        folder = Path(self.state.db.data_dir) / "outbox"
        folder.mkdir(parents=True, exist_ok=True)
        pdf = self.bill.invoice_pdf(v.inv.id, folder / f"{v.inv.number.replace('/', '-')}.pdf")
        c = self.state.clients.get(v.inv.client_id)
        prof = self.bill.profile()
        body = (f"Dear {c.contact_person or 'Sir/Madam'},\n\nPlease find attached our invoice {v.inv.number} dated "
                f"{v.inv.invoice_date:%d-%m-%Y} for ₹{fmt_inr(v.inv.total)}"
                + (f", payable by {v.inv.due_date:%d-%m-%Y}" if v.inv.due_date else "") + ".\n\n"
                + (f"Payment details:\n{prof.bank}\n\n" if prof.bank else "") + f"Regards,\n{prof.name}")
        m = MailService(self.state.db).add_draft("other", c.email or "", f"Invoice {v.inv.number} – {prof.name}", body,
                                                 [pdf], c.id, v.inv.number, user=self.state.user)
        self.state.notify()
        self.f_info.setText(f"Invoice {v.inv.number} is in the Outbox – check and send it there.")
        return m

    def cancel_invoice(self, reason: str | None = None) -> bool:
        v = self._sel_invoice()
        if v is None:
            return False
        if reason is None:
            reason, ok = QInputDialog.getText(self, "Cancel invoice", f"Why is {v.inv.number} cancelled? (the number "
                                              "is kept, not reused)")
            if not ok:
                return False
        try:
            self.bill.cancel_invoice(v.inv.id, reason, self.state.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "Cancel invoice", str(exc))
            return False
        self.reload()
        return True

    # -------------------------------------------------------------- reload
    def reload(self) -> None:
        current = self.who.currentText()
        self.who.blockSignals(True)
        self.who.clear()
        self.who.addItems([ALL, *self.tasks_svc.assignees()])
        self.who.setCurrentText(current or ALL)
        self.who.blockSignals(False)
        self.show_tasks()
        self.show_fees()
