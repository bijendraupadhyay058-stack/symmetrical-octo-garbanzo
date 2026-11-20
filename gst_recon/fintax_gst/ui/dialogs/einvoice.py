"""e-Invoice / e-way bill bulk files of a month, with the seller details and the party address book."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from ...importers.readers import UnsupportedFileError
from ...outward.einvoice_ewb import Transport
from ...services.common import ServiceError
from ...services.einvoice_files import EInvoiceFileService
from ..widgets import OBJECT_ROLE, RowsModel, Table, section, sortable

KINDS = {"einv": "e-Invoice – bulk upload file for the IRP", "ewb": "e-Way bill – bulk upload file"}
MODES = {1: "Road", 2: "Rail", 3: "Air", 4: "Ship"}


class PartyForm(QDialog):
    def __init__(self, parent, row=None):
        super().__init__(parent)
        self.setWindowTitle("Party address")
        form = QFormLayout(self)
        self.name = QLineEdit(row.name if row else "")
        self.gstin = QLineEdit(row.gstin if row else "")
        self.address = QLineEdit(row.address if row else "")
        self.place = QLineEdit(row.place if row else "")
        self.pin = QLineEdit(row.pin if row else "")
        self.distance = QSpinBox()
        self.distance.setRange(0, 4000)
        self.distance.setValue(row.distance_km if row else 0)
        self.distance.setSuffix(" km (0: the portal works it out)")
        for label, w in (("Name", self.name), ("GSTIN (blank if unregistered)", self.gstin), ("Address", self.address),
                         ("Place / city", self.place), ("PIN code", self.pin), ("Distance for e-way bills", self.distance)):
            form.addRow(label, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {"name": self.name.text(), "gstin": self.gstin.text(), "address": self.address.text(),
                "place": self.place.text(), "pin": self.pin.text(), "distance_km": self.distance.value()}


class PartyBookDialog(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state, self.svc = state, EInvoiceFileService(state.db)
        self.setWindowTitle(f"Party addresses – {state.client.name}")
        self.resize(950, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Customer addresses for e-invoices and e-way bills. Import a party list (e.g. Tally: "
                             "List of Ledgers → Sundry Debtors, exported to Excel with address, PIN code and GSTIN), or "
                             "add parties one by one."))
        row = QHBoxLayout()
        imp = QPushButton("Import party list…")
        imp.clicked.connect(lambda: self.import_list())
        add = QPushButton("Add / change party…")
        add.clicked.connect(lambda: self.edit())
        row.addWidget(imp)
        row.addWidget(add)
        row.addStretch()
        lay.addLayout(row)
        self.model = RowsModel(["Name", "GSTIN", "Address", "Place", "PIN", "State", "Km"])
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.edit(selected=True))
        lay.addWidget(self.table, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self.reload()

    def reload(self) -> None:
        rows = self.svc.party_rows(self.state.client.id)
        self.model.set_rows([[r.name, r.gstin, r.address, r.place, r.pin, r.state_code, r.distance_km] for r in rows],
                            rows)
        self.table.fit(260)

    def import_list(self, path: str | None = None):
        path = path or QFileDialog.getOpenFileName(self, "Party list", "", "Excel / CSV (*.xlsx *.xls *.csv)")[0]
        if not path:
            return None
        try:
            saved, problems = self.svc.import_parties(self.state.client.id, path, self.state.user)
        except (ServiceError, UnsupportedFileError) as exc:
            QMessageBox.warning(self, "Party list", str(exc))
            return None
        QMessageBox.information(self, "Party list", f"{saved} part(ies) saved." + (
            "\n\nNot saved:\n" + "\n".join(problems[:10]) if problems else ""))
        self.reload()
        return saved

    def edit(self, values: dict | None = None, selected: bool = False) -> bool:
        if values is None:
            current = None
            if selected:
                rows = self.table.selectionModel().selectedRows()
                current = self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None
            dlg = PartyForm(self, current)
            if dlg.exec() != QDialog.Accepted:
                return False
            values = dlg.values()
        try:
            self.svc.save_party(self.state.client.id, user=self.state.user, **values)
        except ServiceError as exc:
            QMessageBox.warning(self, "Party address", str(exc))
            return False
        self.reload()
        return True


class EInvoiceDialog(QDialog):
    def __init__(self, parent, state, period: str, kind: str = "einv"):
        super().__init__(parent)
        self.state, self.period, self.bulk = state, period, None
        self.svc = EInvoiceFileService(state.db)
        self.setWindowTitle(f"e-Invoice / e-way bill files – {state.client.name} – {period}")
        self.resize(1050, 680)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.kind = QComboBox()
        for k, label in KINDS.items():
            self.kind.addItem(label, k)
        self.kind.setCurrentIndex(list(KINDS).index(kind))
        self.kind.currentIndexChanged.connect(lambda _i: self.refresh())
        parties = QPushButton("Party addresses…")
        parties.clicked.connect(lambda: self.party_book())
        top.addWidget(self.kind)
        top.addStretch()
        top.addWidget(parties)
        lay.addLayout(top)
        grid = QGridLayout()
        seller = self.svc.seller(state.client.id)
        self.s_addr, self.s_place, self.s_pin = QLineEdit(seller.address), QLineEdit(seller.place), QLineEdit(seller.pin)
        save_seller = QPushButton("Save")
        save_seller.clicked.connect(lambda: self.save_seller())
        grid.addWidget(QLabel("<b>Your client (seller)</b> – address"), 0, 0)
        grid.addWidget(self.s_addr, 0, 1, 1, 3)
        grid.addWidget(QLabel("Place"), 0, 4)
        grid.addWidget(self.s_place, 0, 5)
        grid.addWidget(QLabel("PIN"), 0, 6)
        grid.addWidget(self.s_pin, 0, 7)
        grid.addWidget(save_seller, 0, 8)
        self.t_id, self.t_name, self.t_vehicle = QLineEdit(), QLineEdit(), QLineEdit()
        self.t_id.setPlaceholderText("Transporter ID (GSTIN / TRANSIN)")
        self.t_name.setPlaceholderText("Transporter name")
        self.t_vehicle.setPlaceholderText("Vehicle no, e.g. MH12AB1234")
        self.t_mode = QComboBox()
        for code, label in MODES.items():
            self.t_mode.addItem(label, code)
        for w in (self.t_id, self.t_name, self.t_vehicle):
            w.editingFinished.connect(self.refresh)
        self.transport_lbl = QLabel("<b>Transport</b> (e-way bills)")
        grid.addWidget(self.transport_lbl, 1, 0)
        grid.addWidget(self.t_id, 1, 1)
        grid.addWidget(self.t_name, 1, 2)
        grid.addWidget(self.t_vehicle, 1, 3)
        grid.addWidget(self.t_mode, 1, 4)
        lay.addLayout(grid)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addWidget(section("Left out / to check"))
        self.model = RowsModel(["", "Document", "Party", "Finding"])
        t = Table()
        t.setModel(sortable(self.model))
        lay.addWidget(t, 1)
        self.table = t
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save JSON…")
        self.save_btn.clicked.connect(lambda: self.save())
        row.addWidget(self.save_btn)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def transport(self) -> Transport:
        return Transport(self.t_id.text().strip().upper(), self.t_name.text().strip(),
                         self.t_vehicle.text().replace(" ", "").upper(), self.t_mode.currentData())

    def refresh(self) -> None:
        ewb = self.kind.currentData() == "ewb"
        for w in (self.transport_lbl, self.t_id, self.t_name, self.t_vehicle, self.t_mode):
            w.setVisible(ewb)
        try:
            self.bulk = b = (self.svc.ewaybills(self.state.client.id, self.period, self.transport()) if ewb else
                             self.svc.einvoices(self.state.client.id, self.period))
        except ServiceError as exc:
            self.bulk = None
            self.info.setText(str(exc))
            self.save_btn.setEnabled(False)
            self.model.set_rows([])
            return
        left = sum(1 for i in b.issues if i.severity == "error")
        what = "e-way bill(s)" if ewb else "e-invoice(s)"
        self.info.setText(f"<b>{b.count} {what}</b> in the file" + (
            f" · <span style='color:#C62828'><b>{left} left out</b> – complete the party addresses or the sales "
            "register</span>" if left else "") + ("" if ewb else " · B2C sales need no e-invoice"))
        self.model.set_rows([["Left out" if i.severity == "error" else "Check", i.doc.number if i.doc else "",
                              (i.doc.name or i.doc.gstin) if i.doc else "", i.message] for i in b.issues])
        self.table.fit(520)
        self.save_btn.setEnabled(b.count > 0)

    def save_seller(self) -> None:
        try:
            self.svc.save_seller(self.state.client.id, self.s_addr.text(), self.s_place.text(), self.s_pin.text(),
                                 self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Seller", str(exc))
            return
        self.refresh()

    def party_book(self, show: bool = True):
        dlg = PartyBookDialog(self, self.state)
        if show:
            dlg.exec()
            self.refresh()
        return dlg

    def save(self, path: str | None = None):
        if self.bulk is None or not self.bulk.count:
            return None
        kind = self.kind.currentData()
        default = f"{'EINV' if kind == 'einv' else 'EWB'}_{self.state.client.gstin}_{self.period}.json"
        path = path or QFileDialog.getSaveFileName(self, "Save JSON", default, "JSON (*.json)")[0]
        if not path:
            return None
        out = self.svc.save(self.state.client.id, "einvoice_json" if kind == "einv" else "ewaybill_json", self.bulk,
                            path, self.state.user)
        portal = ("e-invoice portal → Bulk upload (or the IRP offline tool)" if kind == "einv" else
                  "e-way bill portal → e-Waybill → Bulk generation")
        QMessageBox.information(self, "Saved", f"Saved {out}.\n\nUpload it on the {portal}. Nothing was sent from "
                                "this program.")
        return out
