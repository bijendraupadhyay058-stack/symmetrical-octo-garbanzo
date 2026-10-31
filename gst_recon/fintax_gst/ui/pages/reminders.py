"""Client document reminders: what each client still has to send for a month, and the message to send."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ...services.common import ServiceError
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, section, sortable
from .firm import ALL, previous_month


class RemindersPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.requests = []
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Client reminders", "What each client still has to send or clarify for the month, "
                                                      "with a ready message. The program never sends anything – "
                                                      "you copy the message or open it in your e-mail or WhatsApp."))
        bar = QHBoxLayout()
        self.period = QLineEdit(previous_month())
        self.period.setMaximumWidth(90)
        self.period.returnPressed.connect(self.reload)
        self.staff_cb = QComboBox()
        self.staff_cb.setMinimumWidth(140)
        self.staff_cb.activated.connect(lambda _i: self.reload())
        self.ask_sales = QCheckBox("Also ask for the sales register")
        self.ask_sales.toggled.connect(lambda _on: self.reload())
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        for w in (QLabel("Month"), self.period, QLabel("Staff"), self.staff_cb, self.ask_sales, refresh):
            bar.addWidget(w)
        bar.addStretch()
        lay.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        ll.addWidget(self.info)
        self.model = RowsModel(["Client", "Contact", "Needed", "Reminded", "Last reminder"],
                               kinds=["text", "text", "text", "int", "text"])
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.show_message())
        ll.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(section("Message (you can edit it before sending)"))
        self.text = QPlainTextEdit()
        rl.addWidget(self.text, 1)
        sig = QHBoxLayout()
        self.signature = QLineEdit(str(state.qsettings.value("reminder_signature", "")))
        self.signature.setPlaceholderText("Your name / firm name for the end of the message")
        self.signature.editingFinished.connect(self._save_signature)
        sig.addWidget(QLabel("Signed"))
        sig.addWidget(self.signature, 1)
        rl.addLayout(sig)
        buttons = QHBoxLayout()
        self.copy_btn = primary("Copy message")
        self.copy_btn.clicked.connect(lambda: self.send("copy"))
        self.mail_btn = QPushButton("Open in e-mail")
        self.mail_btn.clicked.connect(lambda: self.send("email"))
        self.wa_btn = QPushButton("Open WhatsApp")
        self.wa_btn.clicked.connect(lambda: self.send("whatsapp"))
        for w in (self.copy_btn, self.mail_btn, self.wa_btn):
            buttons.addWidget(w)
        rl.addLayout(buttons)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([620, 520])
        lay.addWidget(split, 1)
        for sig_ in (state.dataChanged, state.clientChanged):
            sig_.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _svc(self):
        from ...services.reminders import ReminderService

        return ReminderService(self.state.db)

    def _save_signature(self) -> None:
        self.state.qsettings.setValue("reminder_signature", self.signature.text().strip())
        self.show_message()

    def reload(self) -> None:
        from ...services.firm import FirmService

        current = self.staff_cb.currentText() or ALL
        self.staff_cb.blockSignals(True)
        self.staff_cb.clear()
        self.staff_cb.addItems([ALL, *FirmService(self.state.db).staff_names()])
        self.staff_cb.setCurrentText(current if self.staff_cb.findText(current) >= 0 else ALL)
        self.staff_cb.blockSignals(False)
        staff = None if self.staff_cb.currentText() == ALL else self.staff_cb.currentText()
        try:
            self.requests = self._svc().requests(self.period.text().strip(), staff, self.ask_sales.isChecked())
        except ServiceError as exc:
            self.info.setText(str(exc))
            return
        self.model.set_rows([[r.name, r.contact or r.email or r.mobile, r.summary(), r.times_reminded,
                              f"{r.last_reminded:%d-%m-%Y %H:%M}" if r.last_reminded else ""] for r in self.requests],
                            self.requests)
        self.table.fit(360)
        self.info.setText(f"{len(self.requests)} client(s) with something pending for {self.period.text()}."
                          if self.requests else "Nothing pending from clients for this month.")
        self.text.clear()
        if self.requests:
            self.table.selectRow(0)

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE)

    def show_message(self) -> None:
        r = self._selected()
        self.text.setPlainText(self._svc().message(r, self.signature.text().strip()) if r else "")
        for b in (self.mail_btn, self.wa_btn):
            b.setEnabled(r is not None)
        if r is not None:
            self.mail_btn.setToolTip(r.email or "No e-mail address on the client form – your e-mail program opens "
                                                "without a recipient")
            self.wa_btn.setToolTip(r.mobile or "No mobile number on the client form – WhatsApp asks whom to send to")

    def send(self, channel: str) -> str | None:
        r = self._selected()
        text = self.text.toPlainText().strip()
        if r is None or not text:
            QMessageBox.information(self, "Client reminders", "Select a client in the list first.")
            return None
        svc = self._svc()
        if channel == "copy":
            QApplication.clipboard().setText(text)
            target = None
        else:
            target = svc.mailto(r, text) if channel == "email" else svc.whatsapp(r, text)
            QDesktopServices.openUrl(QUrl(target))
        svc.record(r, channel, self.state.user)
        self.info.setText({"copy": "Message copied – paste it into your e-mail or WhatsApp.",
                           "email": "Opened in your e-mail program – check it and press Send there.",
                           "whatsapp": "Opened WhatsApp – choose the chat and press Send there."}[channel])
        row = self.requests.index(r)
        r.times_reminded += 1
        self.model.rows[row][3] = r.times_reminded
        cell = self.model.index(row, 3)
        self.model.dataChanged.emit(cell, cell)
        return target or text
