"""Split / classify one trial-balance ledger: any number of parts, each with its accounting and GST classification;
amounts by value or percentage; GST from purchase-register invoices, entered from invoices, or apportioned with the
user's explicit approval. The parts must add up to the ledger's amount before they are approved."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...core.money import fmt_inr
from ...gstr9.expenses import TABLE14
from ...ledgers.classify import ACCT_CLASSES, ELIGIBILITY, GST_BASIS, GST_CLASSES, GST_SOURCES
from ...services.bifurcation import SplitIn
from ...services.common import ServiceError

COLS = ["Accounting classification", "GST classification", "Source", "GSTR-9C head", "ITC eligibility", "Amount",
        "%", "Taxable value", "IGST", "CGST", "SGST", "Cess", "GST basis", "Basis note", "Remarks"]
C_ACCT, C_GST, C_SRC, C_HEAD, C_ELIG, C_AMT, C_PCT, C_TXB, C_IGST, C_CGST, C_SGST, C_CESS, C_BASIS, C_NOTE, C_REM = \
    range(len(COLS))
TAX_COLS = (C_IGST, C_CGST, C_SGST, C_CESS)


def _dec(text) -> Decimal | None:
    text = str(text or "").replace(",", "").replace("₹", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ServiceError(f"'{text}' is not an amount") from None


def _combo(items: dict | list, current: str = "", editable: bool = False) -> QComboBox:
    cb = QComboBox()
    cb.setEditable(editable)
    for k, v in (items.items() if isinstance(items, dict) else ((x, x) for x in items)):
        cb.addItem(v, k)
    i = cb.findData(current)
    if i >= 0:
        cb.setCurrentIndex(i)
    elif editable and current:
        cb.setEditText(current)
    return cb


class InvoicePicker(QDialog):
    """Choose purchase-register documents whose taxable value and GST make one part."""

    def __init__(self, parent, rows: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("GST from purchase-register invoices")
        self.resize(900, 520)
        self.rows = rows
        lay = QVBoxLayout(self)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search supplier, GSTIN, invoice no, description…")
        self.find.textChanged.connect(self._filter)
        lay.addWidget(self.find)
        self.table = QTableWidget(len(rows), 7)
        self.table.setHorizontalHeaderLabels(["Supplier", "GSTIN", "Invoice no", "Date", "Taxable", "GST",
                                              "Description"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, d in enumerate(rows):
            gst = d["igst"] + d["cgst"] + d["sgst"] + d["cess"]
            for c, v in enumerate([d["supplier"], d["gstin"], d["no"], d["date"].strftime("%d-%m-%Y"),
                                   fmt_inr(d["taxable"]), fmt_inr(gst), d["description"]]):
                item = QTableWidgetItem(str(v))
                if c in (4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table, 1)
        self.info = QLabel("Select the invoices of this part (Ctrl / Shift for several). Invoices already used for "
                           "another ledger are not listed.")
        lay.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _filter(self, text: str) -> None:
        t = text.lower()
        for r, d in enumerate(self.rows):
            hay = f"{d['supplier']} {d['gstin']} {d['no']} {d['description']}".lower()
            self.table.setRowHidden(r, bool(t) and t not in hay)

    def selected(self) -> list[int]:
        return [self.rows[i.row()]["id"] for i in self.table.selectionModel().selectedRows()]


class LedgerSplitDialog(QDialog):
    def __init__(self, parent, svc, view, client_id: int, fy: str, user: str):
        super().__init__(parent)
        self.svc, self.view, self.client_id, self.fy, self.user = svc, view, client_id, fy, user
        lg = view.ledger
        self.base = lg.base
        self.setWindowTitle(f"Classify / split – {lg.name}")
        self.resize(1400, 520)
        self.invoice_ids: dict[int, list[int]] = {}  # row -> invoice ids
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{lg.name}</b> · {lg.parent or lg.primary_group} · amount to classify "
                      f"<b>₹{fmt_inr(lg.base)}</b>" + (f" ({lg.base_note})" if lg.base_note else "") +
                      f" · trial balance closing ₹{fmt_inr(lg.closing)}")
        head.setTextFormat(Qt.RichText)
        lay.addWidget(head)
        bar = QHBoxLayout()
        for text, fn in (("Add part", lambda: self.add_row()), ("Remove part", self.remove_row),
                         ("Part from purchase register…", self.from_invoices), ("Split by percentage…", self.by_percent),
                         ("Apportion GST…", self.apportion), ("Remaining to last part", self.fill_last)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.itemChanged.connect(lambda _i: self._totals())
        lay.addWidget(self.table, 1)
        self.total = QLabel()
        self.total.setTextFormat(Qt.RichText)
        lay.addWidget(self.total)
        lay.addWidget(QLabel("GST is taken only from invoices (purchase register), figures you enter from invoices, or "
                             "an apportionment you approve. A part without GST adds nothing to the ITC workings."))
        bb = QDialogButtonBox()
        self.save_btn = bb.addButton("Save and approve", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for sp in view.splits:
            self.add_row(SplitIn(sp.amount, sp.acct_class, sp.gst_class, sp.gst_source, sp.head_9c, sp.eligibility,
                                 sp.taxable, sp.igst, sp.cgst, sp.sgst, sp.cess, sp.gst_basis, sp.basis_note,
                                 __import__("json").loads(sp.invoice_ids or "[]"), sp.percent,
                                 "" if sp.remarks.startswith("Suggested") and not sp.approved else sp.remarks))
        if not view.splits:
            self.add_row(SplitIn(lg.base, "", "inputs" if lg.nature == "purchase" else
                                 "capital" if lg.nature == "asset" else "services"))
        self._totals()

    # ------------------------------------------------------------ rows
    def add_row(self, p: SplitIn | None = None) -> int:
        p = p or SplitIn(Decimal(0), "", "services")
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        self.table.setCellWidget(r, C_ACCT, _combo(list(ACCT_CLASSES), p.acct_class, editable=True))
        self.table.setCellWidget(r, C_GST, _combo(GST_CLASSES, p.gst_class))
        self.table.setCellWidget(r, C_SRC, _combo(GST_SOURCES, p.gst_source))
        self.table.setCellWidget(r, C_HEAD, _combo({"": "–", **{c: f"{c} {lbl[:28]}" for c, lbl in TABLE14}},
                                                   p.head_9c))
        self.table.setCellWidget(r, C_ELIG, _combo({"": "(decide)", **ELIGIBILITY}, p.eligibility))
        self.table.setCellWidget(r, C_BASIS, _combo(GST_BASIS, p.gst_basis))
        vals = {C_AMT: p.amount, C_PCT: p.percent, C_TXB: p.taxable, C_IGST: p.igst, C_CGST: p.cgst, C_SGST: p.sgst,
                C_CESS: p.cess}
        for c in range(len(COLS)):
            if self.table.cellWidget(r, c) is not None:
                continue
            v = vals.get(c)
            text = p.basis_note if c == C_NOTE else p.remarks if c == C_REM else ("" if v is None else str(v))
            item = QTableWidgetItem(text)
            if c in vals:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, c, item)
        self.invoice_ids[r] = list(p.invoice_ids)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(C_ACCT, 230)
        self._totals()
        return r

    def remove_row(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        self.table.removeRow(r)
        self.invoice_ids = {(k if k < r else k - 1): v for k, v in self.invoice_ids.items() if k != r}
        self._totals()

    def _text(self, r: int, c: int) -> str:
        w = self.table.cellWidget(r, c)
        if isinstance(w, QComboBox):
            return w.currentText() if w.isEditable() else (w.currentData() or "")
        item = self.table.item(r, c)
        return item.text() if item else ""

    def _set(self, r: int, c: int, value) -> None:
        w = self.table.cellWidget(r, c)
        if isinstance(w, QComboBox):
            i = w.findData(value)
            if i >= 0:
                w.setCurrentIndex(i)
            else:
                w.setEditText(str(value))
            return
        self.table.item(r, c).setText("" if value is None else str(value))

    def parts(self) -> list[SplitIn]:
        out = []
        for r in range(self.table.rowCount()):
            out.append(SplitIn(_dec(self._text(r, C_AMT)) or Decimal(0), self._text(r, C_ACCT).strip(),
                               self._text(r, C_GST), self._text(r, C_SRC), self._text(r, C_HEAD),
                               self._text(r, C_ELIG), *(_dec(self._text(r, c)) for c in (C_TXB, *TAX_COLS)),
                               self._text(r, C_BASIS), self._text(r, C_NOTE).strip(), self.invoice_ids.get(r, []),
                               _dec(self._text(r, C_PCT)), self._text(r, C_REM).strip()))
        return out

    def _totals(self) -> None:
        try:
            total = sum((p.amount for p in self.parts()), Decimal(0))
        except ServiceError:
            self.total.setText("<span style='color:#B71C1C'>An amount is not a number</span>")
            return
        left = self.base - total
        colour = "#1B5E20" if abs(left) <= Decimal("0.50") else "#B71C1C"
        self.total.setText(f"Parts: {self.table.rowCount()} · classified <b>₹{fmt_inr(total)}</b> · unallocated "
                           f"<b style='color:{colour}'>₹{fmt_inr(left)}</b>")

    # --------------------------------------------------------- helpers
    def from_invoices(self, ids: list[int] | None = None, acct_class: str = "", gst_class: str = "inputs") -> int | None:
        if ids is None:
            rows = self.svc.invoices(self.client_id, self.fy)
            mine = {i for v in self.invoice_ids.values() for i in v}
            rows = [d for d in rows if d["id"] not in mine]
            if not rows:
                QMessageBox.information(self, "Purchase register", "No purchase-register invoices of this year are "
                                        "free to use (import the purchase register first).")
                return None
            dlg = InvoicePicker(self, rows)
            if dlg.exec() != QDialog.Accepted or not dlg.selected():
                return None
            ids = dlg.selected()
        try:
            p = self.svc.part_from_invoices(self.client_id, ids, acct_class or "Trading goods", gst_class,
                                            eligibility="eligible")
        except ServiceError as exc:
            QMessageBox.warning(self, "Purchase register", str(exc))
            return None
        return self.add_row(p)

    def by_percent(self, percents: list[Decimal] | None = None) -> None:
        if percents is None:
            text, ok = QInputDialog.getText(self, "Split by percentage", "Percentages of the parts, in order "
                                            "(e.g. 50, 25, 25) – for analysis; GST is not apportioned by this:")
            if not ok or not text.strip():
                return
            try:
                percents = [_dec(x) for x in text.replace(";", ",").split(",") if x.strip()]
            except ServiceError as exc:
                QMessageBox.warning(self, "Split by percentage", str(exc))
                return
        if sum(percents, Decimal(0)) != 100:
            QMessageBox.warning(self, "Split by percentage", "The percentages must add up to 100")
            return
        while self.table.rowCount() < len(percents):
            self.add_row()
        done = Decimal(0)
        for r, pct in enumerate(percents):
            amt = (self.base * pct / 100).quantize(Decimal("0.01")) if r < len(percents) - 1 else self.base - done
            done += amt
            self._set(r, C_PCT, pct)
            self._set(r, C_AMT, amt)
        self._totals()

    def apportion(self, total_gst: dict[str, Decimal] | None = None, approved: bool | None = None) -> bool:
        """Spread the ledger's GST over the parts in proportion to their amounts – only with the user's approval,
        recorded in the basis note of every part."""
        if total_gst is None:
            text, ok = QInputDialog.getText(self, "Apportion GST", "GST of the whole ledger as IGST, CGST, SGST, Cess "
                                            "(e.g. 0, 18000, 18000, 0):")
            if not ok:
                return False
            try:
                vals = [_dec(x) or Decimal(0) for x in text.split(",")]
            except ServiceError as exc:
                QMessageBox.warning(self, "Apportion GST", str(exc))
                return False
            vals += [Decimal(0)] * (4 - len(vals))
            total_gst = dict(zip(("igst", "cgst", "sgst", "cess"), vals[:4]))
        if approved is None:
            box = QMessageBox(QMessageBox.Question, "Apportion GST", "GST will be divided among the parts in the ratio "
                              "of their amounts. This is an estimate, not invoice data: it is recorded as apportioned "
                              "and approved by you.", QMessageBox.Yes | QMessageBox.No, self)
            cb = QCheckBox("I approve apportioning the GST this way")
            box.setCheckBox(cb)
            approved = box.exec() == QMessageBox.Yes and cb.isChecked()
        if not approved:
            return False
        parts = self.parts()
        total = sum((p.amount for p in parts), Decimal(0))
        if not total:
            return False
        note = (f"Apportioned by amount from ledger GST {', '.join(f'{k.upper()} {fmt_inr(v)}' for k, v in total_gst.items() if v)}"
                f" – approved by {self.user} on {date.today():%d-%m-%Y}")
        given = {k: Decimal(0) for k in total_gst}
        for r, p in enumerate(parts):
            last = r == len(parts) - 1
            for k, c in zip(("igst", "cgst", "sgst", "cess"), TAX_COLS):
                share = total_gst[k] - given[k] if last else (total_gst[k] * p.amount / total).quantize(Decimal("0.01"))
                given[k] += share
                self._set(r, c, share if total_gst[k] else "")
            self._set(r, C_BASIS, "apportioned")
            self._set(r, C_NOTE, note)
        return True

    def fill_last(self) -> None:
        n = self.table.rowCount()
        if not n:
            return
        others = sum((p.amount for p in self.parts()[:-1]), Decimal(0))
        self._set(n - 1, C_AMT, self.base - others)
        self._totals()

    def save(self) -> bool:
        try:
            parts = self.parts()
            for p in parts:
                if not p.acct_class:
                    raise ServiceError("Choose the accounting classification of each part")
            self.result_view = self.svc.save_splits(self.view.ledger.id, parts, self.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Classify / split", str(exc))
            return False
        self.accept()
        return True
