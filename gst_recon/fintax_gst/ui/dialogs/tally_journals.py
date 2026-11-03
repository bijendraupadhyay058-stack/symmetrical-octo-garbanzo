"""Tally journal export: ITC reversal / re-claim journals of a month as a TallyPrime import file."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

from ...compliance.tally_journals import LEDGER_LABELS
from ...services.common import ServiceError
from ...services.tally_journals import SOURCES, TallyJournalService
from ..widgets import RowsModel, Table, sortable


class TallyJournalDialog(QDialog):
    def __init__(self, parent, state, period: str, source: str = "claims"):
        super().__init__(parent)
        self.state, self.entries = state, []
        self.svc = TallyJournalService(state.db)
        cid = state.client.id
        self.setWindowTitle(f"Tally journals – {state.client.name}")
        self.resize(1000, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("ITC reversal and re-claim journal vouchers as a file for TallyPrime (Gateway of Tally "
                             "→ Import → Vouchers). Nothing is sent to Tally. The ledgers below must exist in the "
                             "Tally company with exactly these names."))
        form = QFormLayout()
        self.period = QLineEdit(period)
        self.period.setMaximumWidth(100)
        self.period.editingFinished.connect(self.refresh)
        self.source = QComboBox()
        for key, label in SOURCES.items():
            self.source.addItem(label, key)
        self.source.setCurrentIndex(list(SOURCES).index(source))
        self.source.currentIndexChanged.connect(lambda _i: self.refresh())
        self.company = QLineEdit(state.client.name)
        form.addRow("Month (YYYY-MM)", self.period)
        form.addRow("Entries from", self.source)
        form.addRow("Tally company", self.company)
        self.ledger_edits = {}
        for key, value in self.svc.ledgers(cid).items():
            e = QLineEdit(value)
            e.editingFinished.connect(self.refresh)
            self.ledger_edits[key] = e
            form.addRow(LEDGER_LABELS[key], e)
        lay.addLayout(form)
        self.info = QLabel()
        lay.addWidget(self.info)
        self.model = RowsModel(["Date", "Narration", "Debit", "Credit", "Amount"],
                               kinds=["date", "text", "text", "text", "money"])
        table = Table()
        table.setModel(sortable(self.model))
        lay.addWidget(table, 1)
        self.table = table
        row = QHBoxLayout()
        save_names = QPushButton("Save ledger names")
        save_names.clicked.connect(self.save_ledgers)
        self.save_btn = QPushButton("Save Tally XML…")
        self.save_btn.clicked.connect(lambda: self.save())
        row.addWidget(save_names)
        row.addStretch()
        row.addWidget(self.save_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)
        self.refresh()

    def _ledgers(self) -> dict[str, str]:
        return {k: e.text().strip() for k, e in self.ledger_edits.items()}

    def refresh(self) -> None:
        cid = self.state.client.id
        self.info.clear()
        try:
            self.entries = self.svc.entries(cid, self.period.text().strip(), self.source.currentData(),
                                            self._ledgers())
        except ServiceError as exc:
            self.entries = []
            self.info.setText(str(exc))
        rows = []
        for e in self.entries:
            debit = ", ".join(lg for lg, a in e.lines if a > 0)
            credit = ", ".join(lg for lg, a in e.lines if a < 0)
            rows.append([e.on, e.narration, debit, credit, e.total])
        self.model.set_rows(rows)
        self.table.fit(520)
        self.save_btn.setEnabled(bool(self.entries))
        if self.entries:
            self.info.setText(f"{len(self.entries)} journal(s), Rs. {sum(e.total for e in self.entries)} in all.")
        elif not self.info.text():
            self.info.setText("No reversal or re-claim for this month from the chosen source.")

    def save_ledgers(self) -> None:
        self.svc.set_ledgers(self.state.client.id, self._ledgers(), self.state.user)
        self.refresh()

    def save(self, path: str | None = None):
        if not self.entries:
            return None
        path = path or QFileDialog.getSaveFileName(
            self, "Save Tally journals", f"ITC_journals_{self.state.client.gstin}_{self.period.text().strip()}.xml",
            "Tally XML (*.xml)")[0]
        if not path:
            return None
        try:
            out = self.svc.save_xml(self.state.client.id, self.entries, path, self.company.text().strip(),
                                    self.state.user)
        except (ServiceError, ValueError) as exc:
            QMessageBox.warning(self, "Tally journals", str(exc))
            return None
        self.info.setText(f"Saved {out}. In TallyPrime: Import → Vouchers → choose this file.")
        return out
