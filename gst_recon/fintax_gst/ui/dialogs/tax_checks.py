"""Findings of the tax type and rate checks for the selected client and period."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...compliance.tax_checks import KINDS, TaxIssue
from ..widgets import RowsModel, Table, sortable


class TaxCheckDialog(QDialog):
    def __init__(self, parent, issues: list[TaxIssue], title: str):
        super().__init__(parent)
        self.issues, self.title = issues, title
        self.setWindowTitle(f"Tax type and rate checks – {title}")
        self.resize(1200, 600)
        lay = QVBoxLayout(self)
        counts = {k: sum(1 for i in issues if i.kind == k) for k in KINDS}
        head = QLabel((f"<b>{len(issues)} finding(s)</b>: " + ", ".join(f"{KINDS[k]} {n}" for k, n in counts.items()
                                                                       if n)) if issues else
                      "<b>No findings.</b> Every purchase and sales document has the expected tax type, and the tax "
                      "matches the taxable value at a GST rate.")
        head.setWordWrap(True)
        lay.addWidget(head)
        lay.addWidget(QLabel("These are checks for review – nothing is changed. A wrong tax type is corrected by the "
                             "supplier (purchases) or by you with a credit note and a new invoice (sales)."))
        self.model = RowsModel(["Register", "Check", "GSTIN", "Party", "Invoice no", "Date", "Taxable", "IGST", "CGST",
                                "SGST", "Finding"],
                               kinds=["text", "text", "text", "text", "text", "date", "money", "money", "money",
                                      "money", "text"])
        self.model.set_rows([["Purchase" if i.doc.source == "BOOKS" else "Sales", KINDS[i.kind], i.doc.gstin,
                              i.doc.party, i.doc.invoice_no, i.doc.invoice_date, i.doc.taxable, i.doc.igst, i.doc.cgst,
                              i.doc.sgst, i.message] for i in issues])
        table = Table()
        table.setModel(sortable(self.model))
        table.fit(520)
        lay.addWidget(table, 1)
        row = QHBoxLayout()
        export = QPushButton("Export to Excel…")
        export.clicked.connect(lambda: self.export())
        export.setEnabled(bool(issues))
        row.addWidget(export)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)

    def export(self, path: str | None = None):
        from ...services.tax_checks import TaxCheckService

        path = path or QFileDialog.getSaveFileName(self, "Export tax checks", "tax_checks.xlsx", "Excel (*.xlsx)")[0]
        return TaxCheckService.export_xlsx(self.issues, path, f"Tax type and rate checks – {self.title}") if path \
            else None
