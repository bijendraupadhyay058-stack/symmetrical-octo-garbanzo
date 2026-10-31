"""GSTR-3B draft of a month: the figures to enter on the portal and the cash to pay, saved as one PDF page."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...compliance.gstr3b_draft import HEADS
from ...core.money import ZERO, fmt_inr
from ...importers.gstr3b import TABLE4, TABLE31
from ...services.common import ServiceError
from ...services.gstr3b_draft import Gstr3bDraftService
from ..widgets import RowsModel, Table, section, sortable


class Gstr3bDraftDialog(QDialog):
    def __init__(self, parent, state, period: str):
        super().__init__(parent)
        self.state, self.period, self.draft = state, period, None
        self.setWindowTitle(f"GSTR-3B draft – {state.client.name} – {period}")
        self.resize(1000, 700)
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addWidget(section("Figures for the portal"))
        self.model = RowsModel(["Table", "Taxable value", "IGST", "CGST", "SGST", "Cess"],
                               kinds=["text", "money", "money", "money", "money", "money"])
        t1 = Table()
        t1.setModel(sortable(self.model))
        lay.addWidget(t1, 2)
        lay.addWidget(section("6.1 Payment of tax – ITC set-off and cash"))
        self.pay_model = RowsModel(["Tax", "Payable", "IGST credit", "CGST credit", "SGST credit", "Cess credit",
                                    "Cash"], kinds=["text", "money", "money", "money", "money", "money", "money"])
        t2 = Table()
        t2.setModel(sortable(self.pay_model))
        lay.addWidget(t2, 1)
        self.tables = (t1, t2)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setObjectName("Muted")
        lay.addWidget(self.notes)
        row = QHBoxLayout()
        self.pdf_btn = QPushButton("Save as PDF (one page)…")
        self.pdf_btn.clicked.connect(lambda: self.save_pdf())
        row.addWidget(self.pdf_btn)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.draft = d = Gstr3bDraftService(self.state.db).draft(self.state.client.id, self.period)
        except ServiceError as exc:
            self.draft = None
            self.info.setText(str(exc))
            self.pdf_btn.setEnabled(False)
            return
        rows = [[f"3.1{TABLE31[c][3:6]} {TABLE31[c][7:60]}", d.t31[c].taxable, d.t31[c].igst, d.t31[c].cgst,
                 d.t31[c].sgst, d.t31[c].cess] for c in TABLE31]
        rows += [[f"3.2 Inter-state to unregistered – {p}", t, i, None, None, None] for p, t, i in d.t32]
        rows += [[TABLE4[c][:70], None, d.t4[c].igst, d.t4[c].cgst, d.t4[c].sgst, d.t4[c].cess] for c in TABLE4]
        if d.t5["inter"] or d.t5["intra"]:
            rows.append(["5 Exempt / nil / non-GST purchases – inter-state", d.t5["inter"], None, None, None, None])
            rows.append(["5 Exempt / nil / non-GST purchases – intra-state", d.t5["intra"], None, None, None, None])
        self.model.set_rows(rows)
        so = d.setoff
        pay = []
        for h in HEADS:
            paid = so.paid_by(h)
            pay.append([h.upper(), so.liability[h] + so.rcm[h], *[paid[c] for c in HEADS], so.cash[h]])
        pay.append(["Total", sum((so.liability[h] + so.rcm[h] for h in HEADS), ZERO),
                    *[sum((so.paid_by(x)[c] for x in HEADS), ZERO) for c in HEADS], so.total_cash])
        self.pay_model.set_rows(pay)
        for t in self.tables:
            t.fit(420)
        carried = ", ".join(f"{h.upper()} Rs. {fmt_inr(so.carried[h])}" for h in HEADS if so.carried[h])
        self.info.setText(f"<b>Cash to pay: Rs. {fmt_inr(so.total_cash)}</b>"
                          + (f" · credit carried forward: {carried}" if carried else "")
                          + f"<br>ITC basis: {d.t4_basis}")
        self.notes.setText("<br>".join(f"• {n}" for n in d.notes) if d.notes else
                           "Set-off as per section 49(5) and rule 88A (IGST credit first). Interest and late fee are "
                           "not included.")
        self.pdf_btn.setEnabled(True)

    def save_pdf(self, path: str | None = None, open_file: bool = True):
        if self.draft is None:
            return None
        from ...reports.gstr3b_draft_pdf import build_pdf

        path = path or QFileDialog.getSaveFileName(
            self, "Save GSTR-3B draft", f"GSTR3B_draft_{self.state.client.gstin}_{self.period}.pdf", "PDF (*.pdf)")[0]
        if not path:
            return None
        firm = str(self.state.qsettings.value("reminder_signature", "")).strip()
        out = build_pdf(self.draft, path, firm)
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out
