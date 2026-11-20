"""Bank statement vs electronic cash ledger: GST payments debited in the bank and credited on the portal."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from ...core.money import fmt_inr
from ...importers.readers import UnsupportedFileError
from ...services.bank_recon import AMOUNT, MATCHED, NOT_CREDITED, NOT_IN_BANK, BankReconService
from ...services.common import ServiceError
from ..widgets import RowsModel, Table, primary, sortable

COLOURS = {MATCHED: "#C8E6C9", AMOUNT: "#FFF3C4", NOT_CREDITED: "#FFCDD2", NOT_IN_BANK: "#E3F2FD"}


class BankReconDialog(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state, self.rec = state, None
        self.svc = BankReconService(state.db)
        self.setWindowTitle(f"Bank statement vs electronic cash ledger – {state.client.name}")
        self.resize(1150, 620)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        imp = primary("Import bank statement…")
        imp.clicked.connect(lambda: self.import_statement())
        exp = QPushButton("Export to Excel…")
        exp.clicked.connect(lambda: self.export())
        self.info = QLabel()
        self.info.setWordWrap(True)
        top.addWidget(imp)
        top.addWidget(self.info, 1)
        top.addWidget(exp)
        lay.addLayout(top)
        self.model = RowsModel(["Status", "Bank date", "Narration", "Bank amount", "Ledger date", "CPIN / CIN",
                                "Ledger amount", "How / what to do"],
                               kinds=["text", "date", "text", "money", "date", "text", "money", "text"],
                               colors=lambda r, _c: QColor(COLOURS.get(self.model.rows[r][0], "#FFFFFF")))
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.rec = rec = self.svc.reconcile(self.state.client.id)
        except ServiceError as exc:
            self.rec = None
            self.info.setText(f"{exc}. Net banking → account statement → download as Excel or CSV.")
            self.model.set_rows([])
            return
        self.model.set_rows([[p.status, p.bank.txn_date if p.bank else None, p.bank.narration if p.bank else "",
                              p.bank_amount, p.deposit.entry_date if p.deposit else None,
                              p.deposit.reference if p.deposit else "", p.ledger_amount, p.how] for p in rec.pairs])
        self.table.fit(420)
        bad = rec.count(NOT_CREDITED)
        due = sum((p.bank_amount or 0 for p in rec.pairs if p.status == NOT_CREDITED), 0)
        self.info.setText(f"{rec.date_from:%d-%m-%Y} to {rec.date_to:%d-%m-%Y} · {rec.count(MATCHED)} matched · "
                          f"{rec.count(AMOUNT)} amount differs · "
                          + (f"<span style='color:#C62828'><b>{bad} not credited (₹{fmt_inr(due)})</b></span>"
                             if bad else "0 not credited")
                          + f" · {rec.count(NOT_IN_BANK)} deposit(s) not in the statement"
                          + ("<br>" + "<br>".join(rec.notes) if rec.notes else ""))

    def import_statement(self, path: str | None = None):
        path = path or QFileDialog.getOpenFileName(self, "Bank statement", "", "Excel / CSV (*.xlsx *.xls *.csv)")[0]
        if not path:
            return None
        try:
            saved, gst, skipped = self.svc.import_statement(self.state.client.id, path, self.state.user)
        except (ServiceError, UnsupportedFileError) as exc:
            QMessageBox.warning(self, "Bank statement", str(exc))
            return None
        QMessageBox.information(self, "Bank statement", f"{saved} line(s) saved, {gst} GST payment(s) among them."
                                + (f"\n\n{len(skipped)} line(s) not read:\n" + "\n".join(skipped[:8]) if skipped
                                   else ""))
        self.state.notify()
        self.refresh()
        return saved

    def export(self, path: str | None = None):
        if self.rec is None:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Export", f"Bank_vs_cash_ledger_{self.state.client.gstin}.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        return self.svc.export_xlsx(self.rec, self.state.client.name, path)
