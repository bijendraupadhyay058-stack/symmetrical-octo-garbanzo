"""Prepare GSTR-1: the month's sales register as the GSTR-1 JSON for the GST portal / Offline Tool."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from ...core.money import ZERO
from ...services.common import ServiceError
from ...services.gstr1_prep import Gstr1PrepService
from ..widgets import RowsModel, Table, section, sortable

SECTIONS = {"B2B": "4 – B2B (registered customers)", "B2CL": "5 – B2C large (inter-state)",
            "EXP": "6A – Exports", "B2CS": "7 – B2C others", "NIL": "8 – Nil / exempt / non-GST",
            "CDNR": "9B – Credit / debit notes (registered)", "CDNUR": "9B – Credit / debit notes (unregistered)"}


class Gstr1JsonDialog(QDialog):
    def __init__(self, parent, state, period: str):
        super().__init__(parent)
        self.state, self.period, self.draft = state, period, None
        self.setWindowTitle(f"Prepare GSTR-1 – {state.client.name} – {period}")
        self.resize(1050, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("The GSTR-1 file made from the sales register. Open it in the GST Offline Tool (Import "
                             "→ JSON) or upload it on the portal, check every table, then file. Nothing is sent "
                             "from this program."))
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addWidget(section("Tables"))
        self.sec_model = RowsModel(["Table", "Documents", "Taxable value", "IGST", "CGST", "SGST", "Cess"],
                                   kinds=["text", "int", "money", "money", "money", "money", "money"])
        t1 = Table()
        t1.setModel(sortable(self.sec_model))
        lay.addWidget(t1, 1)
        lay.addWidget(section("Left out / to check"))
        self.issue_model = RowsModel(["", "Document", "Customer", "Finding"], kinds=["text", "text", "text", "text"])
        t2 = Table()
        t2.setModel(sortable(self.issue_model))
        lay.addWidget(t2, 1)
        self.tables = (t1, t2)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save GSTR-1 JSON…")
        self.save_btn.clicked.connect(lambda: self.save())
        row.addWidget(self.save_btn)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.draft = d = Gstr1PrepService(self.state.db).draft(self.state.client.id, self.period)
        except ServiceError as exc:
            self.draft = None
            self.info.setText(str(exc))
            self.save_btn.setEnabled(False)
            return
        rows = []
        for key, label in SECTIONS.items():
            if key in d.counts:
                t = d.totals.get(key, {})
                rows.append([label, d.counts[key], *[t.get(k, ZERO) for k in ("taxable", "igst", "cgst", "sgst",
                                                                              "cess")]])
        self.sec_model.set_rows(rows)
        self.issue_model.set_rows([["Left out" if i.severity == "error" else "Check", i.doc.number if i.doc else "",
                                    (i.doc.name or i.doc.gstin) if i.doc else "", i.message] for i in d.issues])
        for t in self.tables:
            t.fit(520)
        errors = sum(1 for i in d.issues if i.severity == "error")
        self.info.setText(f"<b>{sum(d.counts.values())} document(s)</b> placed in GSTR-1"
                          + (f" · <span style='color:#C62828'><b>{errors} left out</b> – correct them in the sales "
                             "register and import it again, or add them in the Offline Tool</span>" if errors else "")
                          + (f" · {len(d.issues) - errors} point(s) to check" if len(d.issues) > errors else ""))
        self.save_btn.setEnabled(bool(d.counts))

    def save(self, path: str | None = None):
        if self.draft is None:
            return None
        gstin = self.state.client.gstin
        path = path or QFileDialog.getSaveFileName(
            self, "Save GSTR-1 JSON", f"GSTR1_{gstin}_{self.period[5:]}{self.period[:4]}.json", "JSON (*.json)")[0]
        if not path:
            return None
        out = Gstr1PrepService(self.state.db).save(self.state.client.id, self.draft, path, self.state.user)
        QMessageBox.information(self, "GSTR-1", f"Saved {out}.\n\nNext: GST Offline Tool → Import files → Open JSON "
                                "(or the portal: GSTR-1 → Prepare offline → Upload). Check every table before "
                                "filing.")
        return out
