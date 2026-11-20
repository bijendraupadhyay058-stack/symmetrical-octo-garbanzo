"""Suppliers → GSTIN status: registration status of the client's suppliers and the ITC at stake."""
from __future__ import annotations

from datetime import date

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from ...core.money import fmt_inr
from ...importers.readers import UnsupportedFileError
from ...services.common import ServiceError
from ...services.gstin_status import GstinStatusService
from ..widgets import OBJECT_ROLE, RowsModel, Table, primary, sortable

COLOURS = {"high": "#FFCDD2", "medium": "#FFF3C4", "info": "#E3F2FD"}


class GstinStatusTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.svc = GstinStatusService(state.db)
        lay = QVBoxLayout(self)
        note = QLabel("Check suppliers on the GST portal (Search Taxpayer) or with your verification service, save the "
                      "results as Excel / CSV (GSTIN, status, date of cancellation, taxpayer type) and import them "
                      "here. ITC on bills after a cancellation, from a suspended registration or from a composition "
                      "dealer is flagged.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        lay.addWidget(note)
        bar = QHBoxLayout()
        show = primary("Check suppliers")
        show.clicked.connect(lambda: self.refresh())
        imp = QPushButton("Import status list…")
        imp.clicked.connect(lambda: self.import_list())
        edit = QPushButton("Set status…")
        edit.clicked.connect(lambda: self.set_status())
        verify = QPushButton("List to verify (CSV)…")
        verify.setToolTip("Suppliers not checked yet or checked more than 90 days ago")
        verify.clicked.connect(lambda: self.verify_list())
        for w in (show, imp, edit, verify):
            bar.addWidget(w)
        bar.addStretch()
        lay.addLayout(bar)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.model = RowsModel(["Supplier", "GSTIN", "Status", "Cancelled on", "Bills", "ITC", "What to do"],
                               kinds=["text", "text", "text", "date", "int", "money", "text"],
                               colors=lambda r, _c: QColor(COLOURS.get(self.model.payload[r].severity, "#FFFFFF")))
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        if self.state.client is None:
            self.info.setText("Select a client.")
            return
        flags = self.svc.flags(self.state.client.id)
        self.model.set_rows([[f.name, f.gstin, f.status, f.cancelled_on, f.invoices, f.itc, f.message] for f in flags],
                            flags)
        self.table.fit(420)
        high = [f for f in flags if f.severity == "high"]
        self.info.setText(f"{len(flags)} supplier(s) to look at · " + (
            f"<span style='color:#C62828'><b>{len(high)} with ITC at stake ₹{fmt_inr(sum(f.itc for f in high))}"
            "</b></span>" if high else "no ITC at stake") +
            f" · {sum(1 for f in flags if f.severity == 'info')} not checked recently")

    def import_list(self, path: str | None = None):
        path = path or QFileDialog.getOpenFileName(self, "GSTIN status list", "",
                                                   "Excel / CSV / JSON (*.xlsx *.xls *.csv *.json)")[0]
        if not path:
            return None
        try:
            saved, problems = self.svc.import_file(path, self.state.user)
        except (ServiceError, UnsupportedFileError) as exc:
            QMessageBox.warning(self, "GSTIN status", str(exc))
            return None
        QMessageBox.information(self, "GSTIN status", f"{saved} GSTIN(s) updated." + (
            "\n\nNot saved:\n" + "\n".join(problems[:10]) if problems else ""))
        self.refresh()
        return saved

    def set_status(self, values: dict | None = None):
        if values is None:
            rows = self.table.selectionModel().selectedRows()
            current = self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None
            dlg = QDialog(self)
            dlg.setWindowTitle("GSTIN status")
            form = QFormLayout(dlg)
            g = QLineEdit(current.gstin if current else "")
            st = QComboBox()
            st.addItems(["Active", "Cancelled", "Suspended", "Inactive"])
            cancelled = QLineEdit()
            cancelled.setPlaceholderText("dd-mm-yyyy (if cancelled)")
            ttype = QComboBox()
            ttype.addItems(["Regular", "Composition", "SEZ unit", "Casual", "Non-resident"])
            for label, w in (("GSTIN", g), ("Status", st), ("Cancelled on", cancelled), ("Taxpayer type", ttype)):
                form.addRow(label, w)
            b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            b.accepted.connect(dlg.accept)
            b.rejected.connect(dlg.reject)
            form.addRow(b)
            if dlg.exec() != QDialog.Accepted:
                return None
            from ...importers.parsing import parse_date

            try:
                cd = parse_date(cancelled.text()) if cancelled.text().strip() else None
            except ValueError:
                QMessageBox.warning(self, "GSTIN status", f"'{cancelled.text()}' is not a date")
                return None
            values = {"gstin": g.text(), "status": st.currentText(), "cancelled_on": cd,
                      "taxpayer_type": ttype.currentText()}
        try:
            row = self.svc.save(values["gstin"], values["status"], self.state.user, values.get("cancelled_on"),
                                taxpayer_type=values.get("taxpayer_type", ""), checked_on=date.today())
        except ServiceError as exc:
            QMessageBox.warning(self, "GSTIN status", str(exc))
            return None
        self.refresh()
        return row

    def verify_list(self, path: str | None = None):
        if self.state.client is None:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Suppliers to verify",
                                                   f"GSTINs_to_verify_{self.state.client.gstin}.csv", "CSV (*.csv)")[0]
        if not path:
            return None
        out, n = self.svc.to_verify_csv(self.state.client.id, path)
        self.info.setText(f"{n} GSTIN(s) saved in {out} – fill in the status columns and import the file back.")
        return out
