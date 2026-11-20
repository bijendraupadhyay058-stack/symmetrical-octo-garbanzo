"""Rule 37A: ITC of suppliers who did not file GSTR-3B by 30 September – reversal and re-availment."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QItemSelectionModel, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ...services.common import ServiceError
from ...services.rule37a import HEADS, STATES, Rule37aService
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary

COLOURS = {"not_filed": "#FFCDD2", "filed_late": "#FFE0B2", "unknown": "#FFF3C4", "filed": "#E8F5E9"}


class Rule37aPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.w = state, None
        self.svc = Rule37aService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header(
            "Rule 37A reversal", "ITC shown in GSTR-2B from suppliers who had not furnished their GSTR-3B for the "
            "period by 30 September after the year: reverse it in GSTR-3B Table 4B(2) by 30 November, and re-avail "
            "in Table 4A(5) once the supplier files. Filing status comes from GSTR-2A or is entered by you – "
            "nothing is assumed. A reversal / re-availment recorded for a month appears in that month's GSTR-3B "
            "draft (GSTR-3B & annual page)."))
        bar = QHBoxLayout()
        imp = primary("Import filing status (GSTR-2A / list)…")
        imp.clicked.connect(lambda: self.import_status())
        self.status_btn = QPushButton("Set filing status…")
        self.status_btn.clicked.connect(lambda: self.set_status())
        self.rev_btn = QPushButton("Record reversal…")
        self.rev_btn.clicked.connect(lambda: self.record("reversed_in"))
        self.rec_btn = QPushButton("Record re-availment…")
        self.rec_btn.clicked.connect(lambda: self.record("reclaimed_in"))
        self.show_cb = QComboBox()
        for k, v in (("act", "Needing action"), ("all", "All suppliers")):
            self.show_cb.addItem(v, k)
        self.show_cb.currentIndexChanged.connect(lambda _i: self.fill())
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda: self.export())
        for b in (imp, self.status_btn, self.rev_btn, self.rec_btn, self.show_cb):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.model = RowsModel(["Supplier GSTIN", "Name", "Period", "Docs", "IGST", "CGST", "SGST", "Cess",
                                "Total ITC", "GSTR-3B status", "Filed on", "Reversed in", "Re-availed in", "Action",
                                "Note"],
                               kinds=["text", "text", "text", "int"] + ["money"] * 5 + ["text"] * 6,
                               colors=lambda r, _c: QColor(COLOURS.get(self.model.payload[r].state, "#FFFFFF")))
        self.table = Table()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        self.table.setSelectionMode(Table.ExtendedSelection)
        lay.addWidget(self.table, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy = st.client.id, st.fy
        return lambda: Rule37aService(st.db).working(cid, fy)

    def reload(self) -> None:
        st = self.state
        self.w = None
        if st.client is None:
            self.summary.setText("Select a client.")
            self.model.set_rows([], [])
            return
        try:
            self.w = self.svc.working(st.client.id, st.fy)
        except ServiceError as exc:
            self.summary.setText(str(exc))
            return
        self.fill()

    def fill(self) -> None:
        w = self.w
        if w is None:
            return
        lines = [ln for ln in w.lines if self.show_cb.currentData() == "all" or ln.action not in
                 ("No reversal", "Reclaimed")]
        self.model.set_rows([[ln.gstin, ln.name, ln.period, ln.docs, *[ln.tax[h] for h in HEADS], ln.total,
                              STATES[ln.state], ln.filed_on, ln.reversed_in, ln.reclaimed_in, ln.action, ln.note]
                             for ln in lines], lines)
        self.table.fit(300)
        prov = (f" <span style='color:#EF6C00'>Provisional – suppliers can still file until "
                f"{w.check_date:%d-%m-%Y}.</span>" if w.provisional else "")
        self.summary.setText(
            f"<b>{w.client} · FY {w.fy}</b> · to reverse ₹{w.total('reverse'):,.2f} (not yet reversed "
            f"₹{w.total('pending'):,.2f}, due by {w.reverse_by:%d-%m-%Y}) · can be re-availed now "
            f"₹{w.total('reclaim'):,.2f} · status not known ₹{w.total('unknown'):,.2f}" + prov
            if w.lines else f"<b>{w.client} · FY {w.fy}</b>: no GSTR-2B ITC imported for the year.")

    def selected(self) -> list:
        return [self.model.payload[i.row()] for i in self.table.selectionModel().selectedRows()]

    def select(self, rows: list[int]) -> None:
        self.table.clearSelection()
        for r in rows:
            self.table.selectionModel().select(self.model.index(r, 0), QItemSelectionModel.Select |
                                               QItemSelectionModel.Rows)

    # ------------------------------------------------------------ actions
    def import_status(self, path: str | None = None) -> int | None:
        path = path or QFileDialog.getOpenFileName(self, "GSTR-2A or filing status list", "",
                                                   "GSTR-2A / list (*.json *.xlsx *.xls *.csv)")[0]
        if not path:
            return None
        try:
            n, notes = self.svc.import_file(path, self.state.user)
        except (ServiceError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Rule 37A", str(exc))
            return None
        self.state.db.invalidate()
        self.reload()
        QMessageBox.information(self, "Rule 37A", f"GSTR-3B filing status saved for {n} supplier period(s)."
                                + ("\n\n" + "\n".join(notes[:10]) if notes else ""))
        return n

    def set_status(self, filed: bool | None = None, filed_on: date | None = None) -> int:
        sel = self.selected()
        if not sel:
            QMessageBox.information(self, "Rule 37A", "Select the supplier period(s) first.")
            return 0
        if filed is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Supplier GSTR-3B filing status")
            form = QFormLayout(dlg)
            cb = QComboBox()
            cb.addItems(["Filed", "Not filed"])
            when = QDateEdit(date.today())
            when.setCalendarPopup(True)
            when.setDisplayFormat("dd-MM-yyyy")
            form.addRow("GSTR-3B", cb)
            form.addRow("Date of filing (if filed)", when)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            form.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return 0
            filed = cb.currentIndex() == 0
            filed_on = when.date().toPython() if filed else None
        for ln in sel:
            self.svc.set_status(ln.gstin, ln.period, filed, filed_on, "entered", self.state.user)
        self.state.db.invalidate()
        self.reload()
        return len(sel)

    def record(self, what: str, month: str | None = None, note: str = "") -> int:
        sel = self.selected()
        if not sel:
            QMessageBox.information(self, "Rule 37A", "Select the supplier period(s) first.")
            return 0
        if month is None:
            label = "reversal (Table 4B(2))" if what == "reversed_in" else "re-availment (Table 4A(5))"
            month, ok = QInputDialog.getText(self, "Rule 37A", f"GSTR-3B month of the {label}, e.g. "
                                             f"{date.today():%Y-%m} (blank clears it):", QLineEdit.Normal,
                                             f"{date.today():%Y-%m}")
            if not ok:
                return 0
        try:
            for ln in sel:
                self.svc.record(self.state.client.id, ln.gstin, ln.period, user=self.state.user, note=note,
                                **{what: month.strip()})
        except ServiceError as exc:
            QMessageBox.warning(self, "Rule 37A", str(exc))
            return 0
        self.state.db.invalidate()
        self.reload()
        return len(sel)

    def export(self, path: str | None = None, open_file: bool = True):
        st = self.state
        if st.client is None:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Save Rule 37A working",
                                                   f"Rule37A_{st.client.gstin}_{st.fy}.xlsx", "Excel (*.xlsx)")[0]
        if not path:
            return None
        try:
            out = self.svc.export_xlsx(st.client.id, st.fy, path)
        except (OSError, ServiceError) as exc:
            QMessageBox.warning(self, "Rule 37A", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out


__all__ = ["Rule37aPage", "Qt"]
