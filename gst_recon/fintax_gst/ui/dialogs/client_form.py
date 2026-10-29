from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from ...core.gstin import normalize_gstin, pan_of, state_of, validate_gstin
from ...db.models import Client
from ...services.clients import ClientService
from ...services.common import ServiceError

REGISTRATION_TYPES = ["Regular", "Composition", "SEZ Unit", "SEZ Developer", "Casual Taxable Person", "ISD",
                      "Non-Resident"]


class ClientDialog(QDialog):
    def __init__(self, parent, service: ClientService, user: str, client: Client | None = None):
        super().__init__(parent)
        self.service, self.user, self.client = service, user, client
        self.saved: Client | None = None
        self.setWindowTitle("Edit client" if client else "New client")
        self.resize(520, 520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.gstin = QLineEdit(client.gstin if client else "")
        self.gstin.setEnabled(client is None)
        self.gstin.setPlaceholderText("15-character GSTIN")
        self.derived = QLabel("")
        self.gstin.textChanged.connect(self._gstin_changed)
        self.name = QLineEdit(client.name if client else "")
        self.trade = QLineEdit(client.trade_name if client else "")
        self.fy = QLineEdit(client.financial_year if client else "")
        self.fy.setPlaceholderText("2025-26")
        self.reg = QComboBox()
        self.reg.addItems(REGISTRATION_TYPES)
        self.freq = QComboBox()
        self.freq.addItems(["Monthly", "Quarterly"])
        if client:
            self.reg.setCurrentText(client.registration_type)
            self.freq.setCurrentText(client.return_frequency)
        self.address = QPlainTextEdit(client.address if client else "")
        self.address.setFixedHeight(60)
        self.contact = QLineEdit(client.contact_person if client else "")
        self.email = QLineEdit(client.email if client else "")
        self.mobile = QLineEdit(client.mobile if client else "")
        for label, w in (("GSTIN *", self.gstin), ("", self.derived), ("Client name *", self.name),
                         ("Trade name", self.trade), ("Financial year", self.fy), ("Registration type", self.reg),
                         ("Return frequency", self.freq), ("Business address", self.address),
                         ("Contact person", self.contact), ("Email", self.email), ("Mobile", self.mobile)):
            form.addRow(label, w)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._gstin_changed(self.gstin.text())

    def _gstin_changed(self, text: str) -> None:
        g = normalize_gstin(text)
        if len(g) < 15:
            self.derived.setText("<span style='color:#5C6B80'>PAN and state are derived from the GSTIN</span>")
            return
        ok, problem = validate_gstin(g)
        if ok and not problem:
            self.derived.setText(f"<span style='color:#2E7D32'>✔ PAN {pan_of(g)} · {state_of(g)}</span>")
        else:
            self.derived.setText(f"<span style='color:#C62828'>✖ {problem}</span>")

    def values(self) -> dict:
        return {"name": self.name.text().strip(), "trade_name": self.trade.text().strip() or self.name.text().strip(),
                "financial_year": self.fy.text().strip(), "registration_type": self.reg.currentText(),
                "return_frequency": self.freq.currentText(), "address": self.address.toPlainText().strip(),
                "contact_person": self.contact.text().strip(), "email": self.email.text().strip(),
                "mobile": self.mobile.text().strip()}

    def _save(self) -> None:
        try:
            if self.client:
                self.saved = self.service.update(self.client.id, self.user, **self.values())
            else:
                self.saved = self.service.create(self.gstin.text(), self.user, **self.values())
        except ServiceError as exc:
            QMessageBox.warning(self, "Client", str(exc))
            return
        self.accept()
