"""Login and first-administrator dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from ... import PRODUCT_NAME, TAGLINE, __version__
from ...services.auth import AuthService, Session
from ...services.common import ServiceError


class LoginDialog(QDialog):
    """Asks for credentials; in setup mode (no users yet) creates the first administrator."""

    def __init__(self, parent, auth: AuthService):
        super().__init__(parent)
        self.auth = auth
        self.setup = not auth.has_users()
        self.session: Session | None = None
        self.setWindowTitle(f"{PRODUCT_NAME} {__version__} – " + ("create administrator" if self.setup else "log in"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        head = QLabel(f"<span style='font-size:16pt;font-weight:700;color:#1F3864'>{PRODUCT_NAME}</span><br>"
                      f"<span style='color:#5C6B80'>{TAGLINE}</span>")
        lay.addWidget(head)
        if self.setup:
            info = QLabel("No users exist yet. Create the administrator account. Passwords need at least 8 "
                          "characters with letters and digits.")
            info.setWordWrap(True)
            lay.addWidget(info)
        form = QFormLayout()
        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        form.addRow("User name", self.username)
        if self.setup:
            form.addRow("Full name", self.full_name)
        form.addRow("Password", self.password)
        if self.setup:
            form.addRow("Confirm password", self.confirm)
        lay.addLayout(form)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create and log in" if self.setup else "Log in")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.username.setFocus(Qt.OtherFocusReason)

    def submit(self) -> None:
        try:
            if self.setup:
                if self.password.text() != self.confirm.text():
                    raise ServiceError("Passwords do not match")
                self.auth.create_user(self.username.text(), self.password.text(), "admin", self.full_name.text())
            self.session = self.auth.login(self.username.text(), self.password.text())
        except ServiceError as exc:
            self.error.setText(str(exc))
            self.password.clear()
            return
        self.accept()
