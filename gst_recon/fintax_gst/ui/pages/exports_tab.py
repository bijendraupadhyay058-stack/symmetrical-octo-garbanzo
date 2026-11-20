"""GSTR-3B & annual → Exports & refund: export / SEZ invoices vs shipping bills, LUT, and the RFD-01 working."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from ...core.money import fmt_inr
from ...importers.readers import UnsupportedFileError
from ...outward.exports import ACTION, CHECK, RefundInputs
from ...services.common import ServiceError
from ...services.exports import ExportService
from ..widgets import RowsModel, Table, primary, section, sortable

FIELDS = [("turnover_zero_rated", "Turnover of zero-rated supply"), ("turnover_inverted", "Turnover of inverted "
                                                                                          "rated supply"),
          ("adjusted_total_turnover", "Adjusted total turnover"), ("net_itc", "Net ITC"),
          ("itc_inputs_and_services", "ITC on inputs and input services"),
          ("tax_payable_inverted", "Tax payable on inverted rated supply"),
          ("credit_ledger_balance", "Credit ledger balance (limit)")]


class ExportsTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state, self.lines, self.inputs, self.result = state, [], None, None
        self.svc = ExportService(state.db)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.p_from, self.p_to = QLineEdit(f"{date.today():%Y-%m}"), QLineEdit(f"{date.today():%Y-%m}")
        for w in (self.p_from, self.p_to):
            w.setMaximumWidth(90)
        show = primary("Check exports")
        show.clicked.connect(lambda: self.refresh())
        imp = QPushButton("Import shipping bills…")
        imp.setToolTip("ICEGATE / customs broker list: shipping bill no., date, port, invoice no., IGST")
        imp.clicked.connect(lambda: self.import_bills())
        self.lut = QLineEdit()
        self.lut.setPlaceholderText("LUT ARN for the year")
        self.lut.setMaximumWidth(200)
        save_lut = QPushButton("Save LUT")
        save_lut.clicked.connect(lambda: self.save_lut())
        exp = QPushButton("Export to Excel…")
        exp.clicked.connect(lambda: self.export())
        for w in (QLabel("From"), self.p_from, QLabel("to"), self.p_to, show, imp, self.lut, save_lut):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(exp)
        lay.addLayout(bar)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.model = RowsModel(["Status", "Invoice", "Date", "Customer", "Type", "Taxable", "IGST", "Shipping bill",
                                "SB date", "Note"],
                               kinds=["text", "text", "date", "text", "text", "money", "money", "text", "date", "text"],
                               colors=lambda r, _c: QColor({ACTION: "#FFCDD2", CHECK: "#FFF3C4"}.get(
                                   self.model.rows[r][0], "#FFFFFF")))
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 2)
        lay.addWidget(section("Refund of accumulated ITC (RFD-01) – working"))
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem("Export / SEZ without payment – rule 89(4)", "zero_rated")
        self.kind.addItem("Inverted duty structure – rule 89(5)", "inverted")
        fill = QPushButton("Fill from the registers")
        fill.clicked.connect(lambda: self.fill_refund())
        calc = primary("Work out refund")
        calc.clicked.connect(lambda: self.work_out())
        row.addWidget(self.kind)
        row.addWidget(fill)
        row.addWidget(calc)
        row.addStretch()
        lay.addLayout(row)
        form = QFormLayout()
        self.fields = {}
        for key, label in FIELDS:
            e = QLineEdit()
            self.fields[key] = e
            form.addRow(label, e)
        holder = QWidget()
        holder.setLayout(form)
        h = QHBoxLayout()
        h.addWidget(holder, 1)
        self.result_lbl = QLabel()
        self.result_lbl.setWordWrap(True)
        h.addWidget(self.result_lbl, 1)
        lay.addLayout(h)

    def _range(self):
        return self.p_from.text().strip(), self.p_to.text().strip()

    def refresh(self) -> None:
        if self.state.client is None:
            self.info.setText("Select a client.")
            return
        try:
            self.lines = self.svc.check(self.state.client.id, *self._range())
        except ServiceError as exc:
            self.info.setText(str(exc))
            return
        self.model.set_rows([[ln.status, ln.doc.number, ln.doc.date, ln.doc.name, ln.kind, ln.doc.taxable, ln.doc.igst,
                              ln.sb.sb_no if ln.sb else "", ln.sb.sb_date if ln.sb else None, ln.note]
                             for ln in self.lines])
        self.table.fit(420)
        act = sum(1 for ln in self.lines if ln.status == ACTION)
        self.info.setText(f"{len(self.lines)} export / SEZ invoice(s)" + (
            f" · <span style='color:#C62828'><b>{act} need action</b></span>" if act else "") +
            f" · {sum(1 for ln in self.lines if ln.status == CHECK)} to check")
        fy = self.state.fy
        self.lut.setText(self.svc.lut(self.state.client.id, fy).get("arn", ""))

    def import_bills(self, path: str | None = None):
        if self.state.client is None:
            return None
        path = path or QFileDialog.getOpenFileName(self, "Shipping bills", "", "Excel / CSV (*.xlsx *.xls *.csv)")[0]
        if not path:
            return None
        try:
            saved, problems = self.svc.import_shipping_bills(self.state.client.id, path, self.state.user)
        except (ServiceError, UnsupportedFileError) as exc:
            QMessageBox.warning(self, "Shipping bills", str(exc))
            return None
        QMessageBox.information(self, "Shipping bills", f"{saved} shipping bill(s) saved." + (
            "\n\n" + "\n".join(problems[:10]) if problems else ""))
        self.refresh()
        return saved

    def save_lut(self) -> None:
        if self.state.client is not None:
            self.svc.save_lut(self.state.client.id, self.state.fy, self.lut.text(), None, self.state.user)

    def fill_refund(self) -> RefundInputs | None:
        if self.state.client is None:
            return None
        try:
            self.inputs = i = self.svc.refund_defaults(self.state.client.id, self.kind.currentData(), *self._range())
        except ServiceError as exc:
            self.result_lbl.setText(str(exc))
            return None
        for key, _label in FIELDS:
            v = getattr(i, key)
            self.fields[key].setText("" if v is None else str(v))
        self.result_lbl.setText("<br>".join(f"• {n}" for n in i.notes))
        return i

    def work_out(self):
        if self.inputs is None and self.fill_refund() is None:
            return None
        i = self.inputs
        i.kind = self.kind.currentData()
        try:
            for key, label in FIELDS:
                text = self.fields[key].text().replace(",", "").strip()
                if key == "credit_ledger_balance":
                    i.credit_ledger_balance = Decimal(text) if text else None
                else:
                    setattr(i, key, Decimal(text or "0"))
        except InvalidOperation:
            QMessageBox.warning(self, "Refund", f"'{label}' is not a number")
            return None
        try:
            self.result = r = self.svc.refund(i)
        except ServiceError as exc:
            QMessageBox.warning(self, "Refund", str(exc))
            return None
        self.result_lbl.setText(f"<b>{r.formula}: refund admissible ₹{fmt_inr(r.admissible)}</b><br>" + "<br>".join(
            f"{label}: ₹{fmt_inr(v)}" for label, v in r.steps))
        return r

    def export(self, path: str | None = None):
        if self.state.client is None:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Export", f"Exports_{self.state.client.gstin}.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        refund = (self.inputs, self.result) if self.result is not None else None
        return self.svc.export_xlsx(self.state.client.id, self.lines, refund, path)
