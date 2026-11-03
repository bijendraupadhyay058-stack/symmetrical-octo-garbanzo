"""ITC review → Claim plan: what to claim in the month's GSTR-3B, what to hold and what is carried forward."""
from __future__ import annotations

from datetime import date

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from ...core.money import fmt_inr
from ...itc.claim_plan import BARRED, CHECK, CLAIM, HOLD, ORDER, WRITTEN_OFF
from ...services.common import ServiceError
from ..widgets import OBJECT_ROLE, RowsModel, Table, primary, section, sortable

COLOURS = {CLAIM: "#C8E6C9", CHECK: "#FFF3C4", HOLD: "#E3F2FD", BARRED: "#FFCDD2", WRITTEN_OFF: "#EEEEEE"}


class ClaimPlanTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state, self.plan = state, None
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.period = QLineEdit(f"{date.today():%Y-%m}")
        self.period.setMaximumWidth(90)
        self.period.setToolTip("GSTR-3B month (YYYY-MM)")
        show = primary("Prepare plan")
        show.clicked.connect(lambda: self.refresh())
        self.only_open = QCheckBox("Hide written-off")
        self.only_open.setChecked(True)
        self.only_open.toggled.connect(lambda _on: self.fill())
        for w in (QLabel("GSTR-3B month"), self.period, show, self.only_open):
            bar.addWidget(w)
        bar.addStretch()
        export = QPushButton("Export to Excel…")
        export.clicked.connect(lambda: self.export())
        bar.addWidget(export)
        lay.addLayout(bar)
        self.summary = QLabel("Choose the month and click Prepare plan.")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.model = RowsModel(["Plan", "Supplier", "GSTIN", "Invoice no", "Date", "Booked in", "In GSTR-2B of", "ITC",
                                "Last date", "Days left", "Why"],
                               kinds=["text", "text", "text", "text", "date", "text", "text", "money", "date", "int",
                                      "text"],
                               colors=lambda r, _c: QColor(COLOURS.get(self.model.rows[r][0], "#FFFFFF")))
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.claim_btn = primary("Record claim for selected")
        self.claim_btn.setToolTip("Records the selected documents as claimed in this month's GSTR-3B (claim register)")
        self.claim_btn.clicked.connect(lambda: self.claim_selected())
        self.claim_all_btn = QPushButton("Record all 'Claim now'")
        self.claim_all_btn.clicked.connect(lambda: self.claim_all())
        self.off_btn = QPushButton("Do not claim (write off)…")
        self.off_btn.clicked.connect(lambda: self.write_off())
        self.undo_btn = QPushButton("Undo write-off")
        self.undo_btn.clicked.connect(lambda: self.undo())
        for b in (self.claim_btn, self.claim_all_btn, self.off_btn, self.undo_btn):
            row.addWidget(b)
            b.setEnabled(state.can("claim"))
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(section("In GSTR-2B but not in the books – ask the client"))
        self.nb_model = RowsModel(["Supplier", "GSTIN", "Invoice no", "Date", "GSTR-2B of", "ITC"],
                                  kinds=["text", "text", "text", "date", "text", "money"])
        self.nb_table = Table()
        self.nb_table.setModel(sortable(self.nb_model))
        self.nb_table.setMaximumHeight(170)
        lay.addWidget(self.nb_table)
        self.notes = QLabel()
        self.notes.setObjectName("Muted")
        self.notes.setWordWrap(True)
        lay.addWidget(self.notes)

    def _svc(self):
        from ...services.claim_plan import ClaimPlanService

        return ClaimPlanService(self.state.db)

    def _as_of(self) -> date:
        page = self.parent()
        while page is not None and not hasattr(page, "as_of"):
            page = page.parent()
        if page is None:
            return date.today()
        q = page.as_of.date()
        return date(q.year(), q.month(), q.day())

    def refresh(self) -> None:
        if self.state.client is None:
            self.summary.setText("Select a client.")
            return
        try:
            self.plan = self._svc().build(self.state.client.id, self.period.text().strip(), self._as_of())
        except ServiceError as exc:
            self.plan = None
            self.summary.setText(str(exc))
            return
        self.fill()

    def fill(self) -> None:
        p = self.plan
        if p is None:
            return
        lines = [ln for ln in p.lines if not (self.only_open.isChecked() and ln.bucket == WRITTEN_OFF)]
        self.model.set_rows([[ln.bucket, ln.doc.supplier_name, ln.doc.supplier_gstin, ln.doc.invoice_no,
                              ln.doc.invoice_date, ln.doc.period, ln.gstr2b_period, ln.itc, ln.deadline, ln.days_left,
                              ln.reason] for ln in lines], lines)
        self.table.fit(420)
        self.summary.setText(f"GSTR-3B <b>{p.period}</b>: " + " · ".join(
            f"<b>{b}</b> {len(p.bucket(b))} (₹{fmt_inr(p.total(b))})" for b in ORDER if p.bucket(b)))
        self.nb_model.set_rows([[g.supplier_name, g.supplier_gstin, g.invoice_no, g.invoice_date, g.period,
                                 g.igst + g.cgst + g.sgst + g.cess] for g in p.not_in_books])
        self.nb_table.fit(300)
        self.notes.setText("<br>".join(f"• {n}" for n in p.notes))

    def _selected(self) -> list:
        rows = self.table.selectionModel().selectedRows()
        return [self.table.model().index(r.row(), 0).data(OBJECT_ROLE) for r in rows]

    def _claim(self, ids: list[int]):
        if not ids or self.plan is None:
            return None
        try:
            res = self._svc().record_claims(self.state.client.id, self.plan.period, ids, self.state.user,
                                            self._as_of())
        except ServiceError as exc:
            QMessageBox.warning(self, "Claim plan", str(exc))
            return None
        self.state.notify()
        self.refresh()
        self.summary.setText(f"{len(res.claimed)} document(s) recorded as claimed in {self.plan.period}. "
                             + self.summary.text())
        return res

    def claim_selected(self):
        sel = [ln for ln in self._selected() if ln.bucket in (CLAIM, CHECK)]
        if not sel:
            QMessageBox.information(self, "Claim plan", "Select 'Claim now' (or checked 'Check first') rows.")
            return None
        return self._claim([ln.doc.db_id for ln in sel])

    def claim_all(self):
        if self.plan is None:
            return None
        ids = [ln.doc.db_id for ln in self.plan.bucket(CLAIM)]
        if not ids:
            QMessageBox.information(self, "Claim plan", "Nothing to claim now.")
            return None
        return self._claim(ids)

    def write_off(self, reason: str | None = None) -> int:
        sel = [ln for ln in self._selected() if ln.bucket in (HOLD, CHECK, BARRED)]
        if not sel:
            return 0
        if reason is None:
            reason, ok = QInputDialog.getText(self, "Do not claim", f"Why will {len(sel)} document(s) not be claimed?")
            if not ok:
                return 0
        try:
            n = self._svc().write_off(self.state.client.id, [ln.doc.db_id for ln in sel], reason, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Claim plan", str(exc))
            return 0
        self.refresh()
        return n

    def undo(self) -> int:
        sel = [ln for ln in self._selected() if ln.bucket == WRITTEN_OFF]
        if not sel:
            return 0
        n = self._svc().undo_write_off(self.state.client.id, [ln.doc.db_id for ln in sel], self.state.user)
        self.refresh()
        return n

    def export(self, path: str | None = None):
        if self.plan is None:
            return None
        path = path or QFileDialog.getSaveFileName(
            self, "Export claim plan", f"ITC_claim_plan_{self.state.client.gstin}_{self.plan.period}.xlsx",
            "Excel (*.xlsx)")[0]
        if not path:
            return None
        return self._svc().export_xlsx(self.plan, self.state.client.name, path)
