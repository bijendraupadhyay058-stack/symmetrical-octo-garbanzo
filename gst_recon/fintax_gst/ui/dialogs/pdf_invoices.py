"""Check screen for purchase invoices read from PDF files: correct anything, then save to the purchase register."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ...core.money import ZERO
from ...importers.parsing import parse_date

COLS = ["File", "Supplier GSTIN", "Supplier name", "Invoice no", "Date", "Taxable value", "IGST", "CGST", "SGST",
        "Cess", "Total", "Check"]
FIELDS = [None, "supplier_gstin", "supplier_name", "invoice_no", "invoice_date", "taxable", "igst", "cgst", "sgst",
          "cess", "total", None]


class PdfInvoicesDialog(QDialog):
    def __init__(self, parent, invoices):
        super().__init__(parent)
        self.invoices = invoices
        self.setWindowTitle(f"Invoices from PDF – {len(invoices)} file(s)")
        self.resize(1300, 560)
        lay = QVBoxLayout(self)
        info = QLabel("Check every row against the PDF (double-click the file name to open it) and correct any cell. "
                      "Yellow rows need attention; rows without GSTIN, number, date or taxable value are not saved. "
                      "Nothing is saved until you click Continue and confirm the import preview.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.grid = QTableWidget(len(invoices), len(COLS))
        self.grid.setHorizontalHeaderLabels(COLS)
        self.grid.cellDoubleClicked.connect(self._open)
        self._fill()
        self.grid.itemChanged.connect(lambda _i: self._recheck())
        lay.addWidget(self.grid, 1)
        row = QHBoxLayout()
        self.summary = QLabel()
        row.addWidget(self.summary, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.ok_btn = QPushButton("Continue to import preview")
        buttons.addButton(self.ok_btn, QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)
        self._recheck()

    def _fill(self) -> None:
        self.grid.blockSignals(True)
        for r, inv in enumerate(self.invoices):
            for c, f in enumerate(FIELDS):
                if c == 0:
                    v = inv.file.name
                elif f is None:
                    v = ""
                else:
                    v = getattr(inv, f)
                    v = f"{v:%d-%m-%Y}" if f == "invoice_date" and v else ("" if v is None else str(v))
                item = QTableWidgetItem(v)
                if c in (0, len(COLS) - 1):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if 5 <= c <= 10:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.grid.setItem(r, c, item)
        self.grid.blockSignals(False)
        self.grid.resizeColumnsToContents()

    def _open(self, row: int, col: int) -> None:
        if col == 0:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.invoices[row].file)))

    def apply_edits(self) -> list[str]:
        """Copy the cells back into the invoices; returns cells that could not be read."""
        bad = []
        for r, inv in enumerate(self.invoices):
            for c, f in enumerate(FIELDS):
                if f is None:
                    continue
                text = self.grid.item(r, c).text().strip()
                if f in ("supplier_gstin",):
                    inv.supplier_gstin = text.upper()
                elif f in ("supplier_name", "invoice_no"):
                    setattr(inv, f, text)
                elif f == "invoice_date":
                    try:
                        inv.invoice_date = parse_date(text) if text else None
                    except ValueError:
                        bad.append(f"{inv.file.name}: date '{text}'")
                else:
                    try:
                        v = Decimal(text.replace(",", "")) if text else (None if f == "total" else ZERO)
                    except InvalidOperation:
                        bad.append(f"{inv.file.name}: {COLS[c]} '{text}'")
                        continue
                    setattr(inv, f, v)
        return bad

    def _recheck(self) -> None:
        self.apply_edits()
        self.grid.blockSignals(True)
        ready = 0
        for r, inv in enumerate(self.invoices):
            problems = inv.problems()
            text = "; ".join(problems + [n for n in inv.notes if n not in problems])
            self.grid.item(r, len(COLS) - 1).setText(text or "OK")
            colour = QColor("#FFF3C4") if text else QColor("#E8F5E9")
            for c in range(len(COLS)):
                self.grid.item(r, c).setBackground(colour)
            usable = inv.supplier_gstin and inv.invoice_no and inv.invoice_date and inv.taxable
            ready += 1 if usable else 0
        self.grid.blockSignals(False)
        self.summary.setText(f"{ready} of {len(self.invoices)} invoice(s) can be saved")
        self.ok_btn.setEnabled(ready > 0)

    def accept(self) -> None:
        bad = self.apply_edits()
        if bad:
            QMessageBox.warning(self, "Invoices from PDF", "Please correct:\n" + "\n".join(bad[:10]))
            return
        super().accept()
