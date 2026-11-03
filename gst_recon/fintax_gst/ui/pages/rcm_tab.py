"""GSTR-3B & annual → RCM & ISD: the reverse-charge register of a month, and the ISD distribution."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.gstin import STATE_CODES
from ...core.money import fmt_inr
from ...importers.readers import UnsupportedFileError
from ...services.common import ServiceError
from ...services.rcm import RcmService
from ..widgets import OBJECT_ROLE, RowsModel, Table, primary, section, sortable


class RcmEntryDialog(QDialog):
    def __init__(self, parent, client_state: str):
        super().__init__(parent)
        self.setWindowTitle("Reverse-charge purchase from an unregistered person")
        form = QFormLayout(self)
        self.when = QDateEdit(QDate.currentDate())
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("dd-MM-yyyy")
        self.name, self.bill, self.desc = QLineEdit(), QLineEdit(), QLineEdit()
        self.desc.setPlaceholderText("e.g. Office rent April, Freight, Advocate fees")
        self.taxable, self.rate = QLineEdit(), QComboBox()
        self.rate.setEditable(True)
        self.rate.addItems(["18", "5", "12", "28", "0"])
        self.state = QComboBox()
        for code, name in sorted(STATE_CODES.items()):
            self.state.addItem(f"{code} – {name}", code)
        self.state.setCurrentIndex(max(self.state.findData(client_state), 0))
        for label, w in (("Date", self.when), ("Supplier name", self.name), ("Bill no. (if any)", self.bill),
                         ("Nature of service", self.desc), ("Taxable value (₹)", self.taxable), ("GST rate %", self.rate),
                         ("Supplier's state", self.state)):
            form.addRow(label, w)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)


class RcmTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state, self.month = state, None
        self.svc = RcmService(state.db)
        lay = QVBoxLayout(self)
        lay.addWidget(section("Reverse charge register"))
        bar = QHBoxLayout()
        self.period = QLineEdit(f"{date.today():%Y-%m}")
        self.period.setMaximumWidth(90)
        show = primary("Show")
        show.clicked.connect(lambda: self.refresh())
        add = QPushButton("Add unregistered purchase…")
        add.setToolTip("Rent, advocate, freight, director … from a person without GSTIN (not in the purchase register)")
        add.clicked.connect(lambda: self.add_entry())
        imp = QPushButton("Import RCM list…")
        imp.setToolTip("Excel / CSV with date, party, amount (and rate, state, narration if available)")
        imp.clicked.connect(lambda: self.import_list())
        rem = QPushButton("Remove entry")
        rem.clicked.connect(lambda: self.remove_entry())
        si = QPushButton("Self-invoices (PDF)…")
        si.setToolTip("Section 31(3)(f): one self-invoice per purchase from an unregistered person")
        si.clicked.connect(lambda: self.self_invoices())
        for w in (QLabel("Month"), self.period, show, add, imp, rem, si):
            bar.addWidget(w)
        bar.addStretch()
        lay.addLayout(bar)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.model = RowsModel(["Status", "Supplier", "GSTIN", "Bill / invoice", "Date", "Service", "Taxable", "Tax",
                                "To check"],
                               kinds=["text", "text", "text", "text", "date", "text", "money", "money", "text"],
                               colors=lambda r, _c: QColor("#FFF3C4") if self.model.rows[r][8] else None)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 2)
        lay.addWidget(section("ISD – distribution of input service credit (rule 39)"))
        ib = QHBoxLayout()
        self.isd_info = QLabel("Select the ISD registration as the client, then click Work out.")
        self.isd_info.setWordWrap(True)
        calc = QPushButton("Work out distribution")
        calc.clicked.connect(lambda: self.isd(self._edited_turnover()))
        exp = QPushButton("Export ISD invoices (Excel)…")
        exp.clicked.connect(lambda: self.export_isd())
        ib.addWidget(self.isd_info, 1)
        ib.addWidget(calc)
        ib.addWidget(exp)
        lay.addLayout(ib)
        self.isd_grid = QTableWidget(0, 8)
        self.isd_grid.setHorizontalHeaderLabels(["Unit", "GSTIN", "Turnover (₹) – edit if needed", "Ratio %", "IGST",
                                                 "CGST", "SGST", "Total"])
        lay.addWidget(self.isd_grid, 1)
        self._isd = None

    # --------------------------------------------------------------- RCM
    def refresh(self) -> None:
        if self.state.client is None:
            self.info.setText("Select a client.")
            return
        try:
            self.month = m = self.svc.month(self.state.client.id, self.period.text().strip())
        except ServiceError as exc:
            self.info.setText(str(exc))
            return
        self.model.set_rows([[ln.status, ln.doc.supplier_name, ln.doc.supplier_gstin or "unregistered",
                              ln.doc.invoice_no, ln.doc.invoice_date, ln.service, ln.doc.taxable, ln.tax,
                              "; ".join(ln.issues)] for ln in m.lines], m.lines)
        self.table.fit(420)
        reg = m.register_total()
        txt = f"<b>RCM tax payable for {m.period}: ₹{fmt_inr(reg.total)}</b> (pay in cash; ITC after payment)"
        if m.filed_31d is not None:
            d = m.filed_31d.total - reg.total
            txt += f" · GSTR-3B 3.1(d) filed ₹{fmt_inr(m.filed_31d.total)}" + (
                f" – <span style='color:#C62828'>difference ₹{fmt_inr(d)}</span>" if abs(d) >= 1 else " – agrees")
        if m.filed_4a3 is not None:
            txt += f" · 4(A)(3) ITC ₹{fmt_inr(m.filed_4a3.total)}"
        need = sum(1 for ln in m.marked if ln.needs_self_invoice)
        if need:
            txt += f" · {need} self-invoice(s) needed"
        self.info.setText(txt)

    def add_entry(self, values: dict | None = None):
        if self.state.client is None:
            return None
        if values is None:
            dlg = RcmEntryDialog(self, self.state.client.state_code)
            if dlg.exec() != QDialog.Accepted:
                return None
            q = dlg.when.date()
            values = {"entry_date": date(q.year(), q.month(), q.day()), "supplier_name": dlg.name.text(),
                      "taxable": dlg.taxable.text(), "rate": dlg.rate.currentText(), "bill_no": dlg.bill.text(),
                      "description": dlg.desc.text(), "supplier_state": dlg.state.currentData()}
        try:
            e = self.svc.add_entry(self.state.client.id, user=self.state.user, **values)
        except ServiceError as exc:
            QMessageBox.warning(self, "RCM", str(exc))
            return None
        self.period.setText(e.period)
        self.refresh()
        return e

    def import_list(self, path: str | None = None):
        if self.state.client is None:
            return None
        path = path or QFileDialog.getOpenFileName(self, "RCM list", "", "Excel / CSV (*.xlsx *.xls *.csv)")[0]
        if not path:
            return None
        try:
            saved, problems = self.svc.import_entries(self.state.client.id, path, user=self.state.user)
        except (ServiceError, UnsupportedFileError) as exc:
            QMessageBox.warning(self, "RCM list", str(exc))
            return None
        QMessageBox.information(self, "RCM list", f"{saved} reverse-charge purchase(s) saved." + (
            "\n\nNot saved:\n" + "\n".join(problems[:10]) if problems else ""))
        self.state.notify()
        self.refresh()
        return saved

    def remove_entry(self) -> bool:
        rows = self.table.selectionModel().selectedRows()
        lines = [self.table.model().index(r.row(), 0).data(OBJECT_ROLE) for r in rows]
        ids = [int(ln.doc.uid[3:]) for ln in lines if ln.doc.uid.startswith("RCM")]
        if not ids:
            QMessageBox.information(self, "RCM", "Select entries added here (unregistered purchases). Purchase-register "
                                    "documents are changed in the register.")
            return False
        for i in ids:
            self.svc.delete_entry(i, self.state.user)
        self.state.notify()
        self.refresh()
        return True

    def self_invoices(self, path: str | None = None, first: int | None = None):
        if self.state.client is None:
            return None
        period = self.period.text().strip()
        if first is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Self-invoices")
            form = QFormLayout(dlg)
            num = QSpinBox()
            num.setRange(1, 99999)
            prefix = QLineEdit("SI")
            form.addRow("First number (continue your series)", num)
            form.addRow("Prefix", prefix)
            b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            b.accepted.connect(dlg.accept)
            b.rejected.connect(dlg.reject)
            form.addRow(b)
            if dlg.exec() != QDialog.Accepted:
                return None
            first = num.value()
        path = path or QFileDialog.getSaveFileName(self, "Save self-invoices", f"Self_invoices_{period}.pdf",
                                                   "PDF (*.pdf)")[0]
        if not path:
            return None
        try:
            out, n = self.svc.self_invoices_pdf(self.state.client.id, period, path, first, user=self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Self-invoices", str(exc))
            return None
        self.info.setText(f"{n} self-invoice(s) saved in {out}.")
        return out

    # --------------------------------------------------------------- ISD
    def _grid_turnover(self) -> dict[int, Decimal]:
        out = {}
        if self._isd is None:
            return out
        for r, s in enumerate(self._isd[1]):
            item = self.isd_grid.item(r, 2)
            unit_id = item.data(256) if item else None
            try:
                out[unit_id] = Decimal(item.text().replace(",", ""))
            except Exception:  # noqa: BLE001 - a cell that is not a number keeps the computed turnover
                pass
        return out

    def _edited_turnover(self) -> dict[int, Decimal] | None:
        """The grid's turnover when the user changed any of it; None keeps the computed basis."""
        grid = self._grid_turnover()
        if self._isd is None or not grid:
            return None
        computed = {s.gstin: s.turnover for s in self._isd[1]}
        units = {u.id: u.gstin for u in self.svc.isd_units(self.state.client.id)}
        changed = any(computed.get(units.get(i)) != v for i, v in grid.items())
        return grid if changed else None

    def isd(self, turnover: dict[int, Decimal] | None = None):
        if self.state.client is None:
            return None
        period = self.period.text().strip()
        try:
            itc, shares, basis = self.svc.isd_distribution(self.state.client.id, period, turnover)
        except ServiceError as exc:
            self.isd_info.setText(str(exc))
            self._isd = None
            self.isd_grid.setRowCount(0)
            return None
        units = {u.gstin: u.id for u in self.svc.isd_units(self.state.client.id)}
        self._isd = (itc, shares, basis)
        self.isd_grid.setRowCount(len(shares))
        for r, s in enumerate(shares):
            for c, v in enumerate([s.name, s.gstin, f"{s.turnover}", f"{s.ratio}", fmt_inr(s.igst), fmt_inr(s.cgst),
                                   fmt_inr(s.sgst), fmt_inr(s.total)]):
                item = QTableWidgetItem(v)
                if c == 2:
                    item.setData(256, units.get(s.gstin))
                self.isd_grid.setItem(r, c, item)
        self.isd_grid.resizeColumnsToContents()
        self.isd_info.setText(f"ITC to distribute in {period}: <b>₹{fmt_inr(itc.total)}</b> · ratio by turnover "
                              f"({basis}). Edit a unit's turnover and click Work out again to change the basis.")
        return shares

    def export_isd(self, path: str | None = None):
        if self._isd is None:
            QMessageBox.information(self, "ISD", "Work out the distribution first.")
            return None
        itc, shares, basis = self._isd
        period = self.period.text().strip()
        path = path or QFileDialog.getSaveFileName(self, "ISD invoices", f"ISD_{period}.xlsx", "Excel (*.xlsx)")[0]
        if not path:
            return None
        return self.svc.export_isd(self.state.client.id, period, shares, itc, basis, path, user=self.state.user)
