"""The firm's e-mail account for sending from the outbox."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox,
)

from ...services.common import ServiceError
from ...services.mailer import PRESETS, SECURITY, MailAccount, MailService


class MailAccountDialog(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state, self.svc = state, MailService(state.db)
        self.setWindowTitle("E-mail account")
        acc = self.svc.account()
        form = QFormLayout(self)
        note = QLabel("Mails are sent from your firm's own mailbox. For Gmail and Outlook, turn on 2-step "
                      "verification and create an <b>app password</b> – use that here, not your normal password.")
        note.setWordWrap(True)
        form.addRow(note)
        self.preset = QComboBox()
        self.preset.addItem("— choose your mail provider —", None)
        for name in PRESETS:
            self.preset.addItem(name, name)
        self.preset.currentIndexChanged.connect(self._preset)
        self.host = QLineEdit(acc.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(acc.port)
        self.security = QComboBox()
        for k, label in SECURITY.items():
            self.security.addItem(label, k)
        self.security.setCurrentIndex(list(SECURITY).index(acc.security))
        self.sender = QLineEdit(acc.sender)
        self.sender.setPlaceholderText("gst@yourfirm.in")
        self.sender_name = QLineEdit(acc.sender_name)
        self.sender_name.setPlaceholderText("Sharma & Co, Chartered Accountants")
        self.username = QLineEdit(acc.username)
        self.username.setPlaceholderText("usually the same as the e-mail address")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("saved – leave blank to keep" if self.svc.has_saved_password() else
                                         "app password")
        self.remember = QCheckBox("Remember the password on this computer (kept encrypted)")
        self.remember.setChecked(acc.save_password)
        for label, w in (("Provider", self.preset), ("Mail server (SMTP)", self.host), ("Port", self.port),
                         ("Security", self.security), ("From address", self.sender), ("From name", self.sender_name),
                         ("User name", self.username), ("Password", self.password), ("", self.remember)):
            form.addRow(label, w)
        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(lambda: self.test())
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.addButton(self.test_btn, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(lambda: self.save() and self.accept())
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _preset(self, _i) -> None:
        name = self.preset.currentData()
        if name:
            host, port, sec = PRESETS[name]
            self.host.setText(host)
            self.port.setValue(port)
            self.security.setCurrentIndex(list(SECURITY).index(sec))

    def account(self) -> MailAccount:
        sender = self.sender.text().strip()
        return MailAccount(self.host.text().strip(), self.port.value(), self.security.currentData(),
                           self.username.text().strip() or sender, sender, self.sender_name.text().strip(),
                           self.remember.isChecked())

    def save(self) -> bool:
        pw = self.password.text()
        try:
            self.svc.save_account(self.account(), pw if pw else (None if self.remember.isChecked() else ""),
                                  self.state.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "E-mail account", str(exc))
            return False
        return True

    def test(self) -> str | None:
        if not self.save():
            return None
        from ..workers import run_task

        task = run_task(self, "Connecting to the mail server", self.svc.test_account, self.password.text() or None,
                        cancellable=False)
        (QMessageBox.information if task.ok else QMessageBox.warning)(
            self, "E-mail account", task.result_value if task.ok else task.message)
        return task.result_value if task.ok else None
