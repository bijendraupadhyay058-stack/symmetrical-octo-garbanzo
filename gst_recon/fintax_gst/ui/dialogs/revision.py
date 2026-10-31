"""What a revised file changes compared with the import it replaces – shown before anything is saved."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ...services.revision import RevisionDiff
from ..widgets import RowsModel, Table, sortable

COLORS = {"Changed": "#FFF3C4", "New": "#C8E6C9", "No longer in the file": "#FFCDD2"}
LABELS = {"taxable": "taxable", "igst": "IGST", "cgst": "CGST", "sgst": "SGST", "cess": "cess",
          "invoice_date": "date", "period": "month", "invoice_value": "value", "supplier_name": "name",
          "place_of_supply": "place of supply", "reverse_charge": "reverse charge", "supply_type": "supply type",
          "itc_availability": "ITC availability", "description": "narration", "hsn_json": "HSN lines"}


class RevisionDialog(QDialog):
    def __init__(self, parent, diff: RevisionDiff):
        super().__init__(parent)
        self.diff = diff
        self.setWindowTitle(f"Replace {diff.old_file} with {diff.new_file}")
        self.resize(1050, 600)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{len(diff.unchanged)} unchanged</b> (kept with their review work) · "
                      f"<b>{len(diff.changed)} changed</b> (corrected) · <b>{len(diff.added)} new</b> · "
                      f"<b>{len(diff.removed)} no longer in the file</b> (removed)"
                      + (f" · {len(diff.already_elsewhere)} already in another import (not added again)"
                         if diff.already_elsewhere else ""))
        head.setWordWrap(True)
        lay.addWidget(head)
        if diff.needs_confirmation:
            runs = ", ".join(f"#{r.id} ({r.period_from})" for r in diff.runs_affected)
            warn = QLabel("<span style='color:#C62828'><b>Documents no longer in the file are used</b>"
                          + (f" in reconciliation(s) {runs}" if runs else "")
                          + (f"{' and' if runs else ''} by {diff.removed_in_use} match decision(s) / ITC record(s)"
                             if diff.removed_in_use else "")
                          + ". Replacing removes them too – reconcile the month again afterwards.</span>")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        rows = []
        for ch, _rec in diff.changed:
            what = "; ".join(f"{LABELS.get(f, f)}: {a if a not in (None, '') else '–'} → {b if b not in (None, '') else '–'}"
                             for f, (a, b) in ch.differences.items() if f != "hsn_json")
            rows.append(["Changed", ch.party, ch.number, what or "HSN lines"])
        rows += [["New", r.supplier_name or r.supplier_gstin, r.invoice_no,
                  f"{r.invoice_date:%d-%m-%Y} · taxable {r.taxable}"] for r in diff.added]
        rows += [["No longer in the file", i.supplier_name or i.supplier_gstin, i.invoice_no,
                  f"{i.invoice_date:%d-%m-%Y} · taxable {i.taxable}"] for i in diff.removed]
        self.model = RowsModel(["", "Party", "Number", "What changes"], colors=self._color)
        self.model.set_rows(rows)
        t = Table()
        t.setModel(sortable(self.model))
        t.fit(520)
        lay.addWidget(t, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Replace")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _color(self, row, col):
        return QColor(COLORS.get(self.model.rows[row][0], "#FFFFFF")) if col == 0 else None
