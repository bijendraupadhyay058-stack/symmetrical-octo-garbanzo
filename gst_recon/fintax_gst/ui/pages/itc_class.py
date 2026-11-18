"""ITC classification & manual mapping: the year's inward supplies from the purchase register and the input tax
ledgers, each with its nature, GST treatment and ITC status; bulk / rule-based mapping, splits, undo; GSTR-9 Table 6
against GSTR-3B, the controls, finalisation and the workbook."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.models import Source
from ...core.money import fmt_inr
from ...ledgers.itc_classes import AVAILED, CLAIMS, NATURES, RCM, SCOPES, STATUSES, TREATMENTS
from ...services.common import ServiceError
from ...services.itc_register import HEADS, ItcRegisterService, PartIn
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary, section, sortable

VIEWS = {"all": "All transactions", "review": "To review (unclassified / low confidence)",
         "unclassified": "Unclassified", "pending": "Eligibility to verify", "unverified": "Claim not verified",
         "inelig_claimed": "Ineligible but claimed", "rcm": "RCM / import of services",
         "taxledger": "In tax ledger only", "differs": "Tax ledger ≠ purchase register", "adjust": "Set-off / adjustments",
         "manual": "Classified by hand", "reviewed": "Marked reviewed"}
CONF_COLOURS = {"high": "#C8E6C9", "medium": "#FFF3C4", "low": "#FFE0B2", "manual": "#FFCDD2"}
TL_FILTER = "Tax ledger (*.xlsx *.xls *.csv);;All files (*)"


def _combo(items: dict, blank: str | None = None, current: str = "") -> QComboBox:
    cb = QComboBox()
    if blank is not None:
        cb.addItem(blank, "")
    for k, v in items.items():
        cb.addItem(v, k)
    i = cb.findData(current)
    if i >= 0:
        cb.setCurrentIndex(i)
    return cb


class ClassifyDialog(QDialog):
    """Nature / GST treatment / ITC status for the selected transactions, or as a saved rule."""

    def __init__(self, parent, first):
        super().__init__(parent)
        self.setWindowTitle("Classify")
        form = QFormLayout(self)
        self.nature = _combo(NATURES, "(leave as is)")
        self.treatment = _combo(TREATMENTS, "(leave as is)")
        self.status = _combo(STATUSES, "(leave as is)")
        self.scope = QComboBox()
        self.scope.addItem("The selected transaction(s) only", "")
        t = first.txn if first else None
        if t is not None:
            if t.ledger:
                self.scope.addItem(f"Rule: every transaction of ledger '{t.ledger[:40]}'", "ledger")
            if t.gstin:
                self.scope.addItem(f"Rule: supplier {t.gstin}", "gstin")
                if t.ledger:
                    self.scope.addItem(f"Rule: supplier {t.gstin} + ledger '{t.ledger[:30]}'", "gstin_ledger")
            if t.hsn:
                self.scope.addItem(f"Rule: HSN/SAC {t.hsn.split(',')[0]}", "hsn")
        self.scope.addItem("Rule: transactions containing a word…", "keyword")
        self.word = QLineEdit()
        self.this_year = QCheckBox("Current financial year only")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason (kept in the history)")
        for label, w in (("Nature", self.nature), ("GST treatment", self.treatment), ("ITC eligibility", self.status),
                         ("Apply to", self.scope), ("Word (for a word rule)", self.word), ("", self.this_year),
                         ("Reason", self.reason)):
            form.addRow(label, w)
        form.addRow(QLabel("A rule applies to matching transactions now and in future imports; a transaction you "
                           "classify by hand keeps its classification."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class SplitDialog(QDialog):
    COLS = ["Taxable value", "IGST", "CGST", "SGST", "Cess", "Nature", "GST treatment", "ITC eligibility"]

    def __init__(self, parent, svc: ItcRegisterService, view, user: str):
        super().__init__(parent)
        self.svc, self.view, self.user = svc, view, user
        t = view.txn
        self.setWindowTitle(f"Split – {t.party} {t.invoice_no or t.voucher_no}")
        self.resize(1000, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{t.party}</b> {t.invoice_no or t.voucher_no} · taxable "
                             f"₹{fmt_inr(t.taxable) if t.taxable is not None else '–'} · IGST ₹{fmt_inr(t.igst)} · "
                             f"CGST ₹{fmt_inr(t.cgst)} · SGST ₹{fmt_inr(t.sgst)} · cess ₹{fmt_inr(t.cess)}"))
        bar = QHBoxLayout()
        for text, fn in (("Add part", lambda: self.add_row()), ("Remove part", self.remove_row),
                         ("Divide tax by taxable value (one GST rate)…", self.proportional)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        lay.addWidget(self.table, 1)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason for the split (kept in the history)")
        lay.addWidget(self.reason)
        lay.addWidget(QLabel("The parts must add up exactly to the invoice – taxable value and each tax head."))
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for p in view.parts or []:
            self.add_row(PartIn(p.igst, p.cgst, p.sgst, p.cess, p.taxable, p.nature, p.treatment, p.status,
                                p.claim, p.claim_period))

    def add_row(self, p: PartIn | None = None) -> int:
        p = p or PartIn(treatment=self.view.parts[0].treatment if self.view.parts else "fcm")
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate((p.taxable, p.igst, p.cgst, p.sgst, p.cess)):
            self.table.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
        self.table.setCellWidget(r, 5, _combo(NATURES, current=p.nature))
        self.table.setCellWidget(r, 6, _combo(TREATMENTS, current=p.treatment))
        self.table.setCellWidget(r, 7, _combo(STATUSES, current=p.status))
        return r

    def remove_row(self) -> None:
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def _dec(self, r, c) -> Decimal | None:
        item = self.table.item(r, c)
        text = (item.text() if item else "").replace(",", "").strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            raise ServiceError(f"'{text}' is not an amount") from None

    def parts(self) -> list[PartIn]:
        """The parts keep the transaction's ITC claim (a split changes the classification, not what was claimed)."""
        first = self.view.parts[0] if self.view.parts else None
        out = []
        for r in range(self.table.rowCount()):
            out.append(PartIn(*(self._dec(r, c) or Decimal(0) for c in (1, 2, 3, 4)), self._dec(r, 0),
                              self.table.cellWidget(r, 5).currentData(), self.table.cellWidget(r, 6).currentData(),
                              self.table.cellWidget(r, 7).currentData(), first.claim if first else "unknown",
                              first.claim_period if first else ""))
        return out

    def set_cell(self, r: int, c: int, value) -> None:
        if c >= 5:
            w = self.table.cellWidget(r, c)
            w.setCurrentIndex(w.findData(value))
        else:
            self.table.item(r, c).setText("" if value is None else str(value))

    def proportional(self) -> bool:
        try:
            parts = self.parts()
            new = self.svc.proportional(self.view.txn, [p.taxable or Decimal(0) for p in parts])
        except ServiceError as exc:
            QMessageBox.warning(self, "Split", str(exc))
            return False
        for r, p in enumerate(new):
            for c, h in zip((1, 2, 3, 4), HEADS):
                self.set_cell(r, c, getattr(p, h))
        return True

    def save(self) -> bool:
        try:
            self.result_view = self.svc.split(self.view.txn.id, self.parts(), self.user, self.reason.text().strip())
        except ServiceError as exc:
            QMessageBox.warning(self, "Split", str(exc))
            return False
        self.accept()
        return True


class ItcClassPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.work = state, None
        self.svc = ItcRegisterService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("ITC classification", "Every inward supply of the year – from the purchase register "
                                                        "and the input tax ledgers – classified by nature, GST treatment "
                                                        "and ITC eligibility – and, kept apart, what was claimed in "
                                                        "GSTR-3B – for GSTR-9 and GSTR-9C."))
        self.steps = QLabel()
        self.steps.setTextFormat(Qt.RichText)
        self.steps.setWordWrap(True)
        lay.addWidget(self.steps)
        bar = QHBoxLayout()
        self.tl_btn = QPushButton("Import tax ledgers…")
        self.tl_btn.setToolTip("Input CGST / SGST / IGST / Cess ledger vouchers exported from TallyPrime (Excel / CSV)")
        self.tl_btn.clicked.connect(lambda: self.import_tax_dialog())
        self.pr_btn = QPushButton("Import purchase register…")
        self.pr_btn.clicked.connect(lambda: self.import_register_dialog())
        self.build_btn = primary("Build / refresh register")
        self.build_btn.clicked.connect(lambda: self.build())
        self.class_btn = QPushButton("Classify selected…")
        self.class_btn.clicked.connect(lambda: self.classify())
        self.split_btn = QPushButton("Split…")
        self.split_btn.clicked.connect(lambda: self.split())
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(lambda: self.undo())
        self.hist_btn = QPushButton("History")
        self.hist_btn.clicked.connect(lambda: self.history())
        self.claim_btn = QPushButton("Record claim…")
        self.claim_btn.setToolTip("What was done with the ITC in GSTR-3B (claimed in which month, not claimed, reversed "
                                  "…) – separate from the classification")
        self.claim_btn.clicked.connect(lambda: self.record_claim())
        self.rules_btn = QPushButton("Rules…")
        self.rules_btn.clicked.connect(lambda: self.rules())
        self.rev_btn = QPushButton("Mark reviewed")
        self.rev_btn.clicked.connect(lambda: self.mark_reviewed())
        for b in (self.tl_btn, self.pr_btn, self.build_btn, self.class_btn, self.claim_btn, self.split_btn,
                  self.undo_btn, self.hist_btn, self.rules_btn, self.rev_btn):
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        fbar = QHBoxLayout()
        self.view_cb = _combo(VIEWS)
        self.month = QComboBox()
        self.nature_f = _combo(NATURES, "Any nature")
        self.treat_f = _combo(TREATMENTS, "Any treatment")
        self.status_f = _combo(STATUSES, "Any eligibility")
        self.claim_f = _combo(CLAIMS, "Any claim")
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search supplier, GSTIN, invoice / voucher no, ledger…")
        for w in (self.view_cb, self.month, self.nature_f, self.treat_f, self.status_f, self.claim_f):
            w.currentIndexChanged.connect(lambda _i: self.show_rows())
        self.find.textChanged.connect(lambda _t: self.show_rows())
        for w in (self.view_cb, self.month, self.nature_f, self.treat_f, self.status_f, self.claim_f, self.find):
            fbar.addWidget(w)
        lay.addLayout(fbar)
        split = QSplitter(Qt.Horizontal)
        self.model = RowsModel(["Date", "Vch / invoice no", "Supplier", "GSTIN", "Ledger", "Taxable value", "CGST",
                                "SGST", "IGST", "Cess", "Nature", "GST treatment", "ITC eligibility", "ITC claim (GSTR-3B)",
                                "Confidence", "Basis", "Source", "Reason"],
                               kinds=["text"] * 5 + ["money"] * 5 + ["text"] * 8, colors=self._colour)
        self.proxy = sortable(self.model)
        self.table = Table()
        self.table.setModel(self.proxy)
        self.table.setSelectionMode(Table.ExtendedSelection)
        self.table.doubleClicked.connect(lambda _i: self.classify())
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(section("Overview (click a line to see it)"))
        self.o_model = RowsModel(["", "Count", "Tax"], kinds=["text", "text", "money"])
        ot = Table()
        ot.setModel(self.o_model)
        ot.setSortingEnabled(False)
        ot.clicked.connect(lambda i: self.drill(i.row()))
        rl.addWidget(ot, 2)
        rl.addWidget(section("GSTR-9 Table 6 against GSTR-3B"))
        self.t6_model = RowsModel(["Row", "Register", "GSTR-3B", "Difference"], kinds=["text", "money", "money", "money"],
                                  colors=lambda r, c: QColor("#FFCDD2") if c == 3 and self.t6_model.rows[r][3] and abs(
                                      self.t6_model.rows[r][3]) > 1 else None)
        t6 = Table()
        t6.setModel(self.t6_model)
        t6.setSortingEnabled(False)
        rl.addWidget(t6, 1)
        rl.addWidget(section("Controls"))
        self.c_model = RowsModel(["Control", "Detail"], colors=lambda r, c: QColor(
            {"pass": "#C8E6C9", "warn": "#FFF3C4", "fail": "#FFCDD2"}[self.c_model.payload[r].status]) if c == 0 else None)
        ct = Table()
        ct.setModel(self.c_model)
        ct.setSortingEnabled(False)
        rl.addWidget(ct, 2)
        ob = QHBoxLayout()
        self.final_btn = QPushButton("Finalise…")
        self.final_btn.clicked.connect(lambda: self.finalise())
        self.xlsx_btn = QPushButton("Workbook (Excel)…")
        self.xlsx_btn.clicked.connect(lambda: self.export("xlsx"))
        self.pdf_btn = QPushButton("Review PDF…")
        self.pdf_btn.clicked.connect(lambda: self.export("pdf"))
        self.note_btn = QPushButton("Year's reporting note…")
        self.note_btn.setToolTip("Record the notification that governs this year's GSTR-9 / 9C reporting relaxations "
                                 "(e.g. Table 14 optional) – shown on the workings; Table 14 is prepared either way")
        self.note_btn.clicked.connect(lambda: self.reporting_note())
        for b in (self.note_btn, self.final_btn, self.xlsx_btn, self.pdf_btn):
            ob.addWidget(b)
        rl.addLayout(ob)
        split.addWidget(right)
        split.setSizes([1050, 430])
        lay.addWidget(split, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # ------------------------------------------------------------ display
    def _colour(self, row, col):
        if not self.model.payload or col not in (13, 14):
            return None
        v = self.model.payload[row]
        if col == 13:
            bad = any(p.status == "blocked" and p.claim in AVAILED for p in v.parts)
            unknown = any(p.claim == "unknown" for p in v.parts)
            return QColor("#FFCDD2") if bad else QColor("#ECEFF1") if unknown else QColor("#C8E6C9")
        conf = {p.confidence for p in v.parts}
        worst = next((c for c in ("manual", "low", "medium", "high") if c in conf), None)
        return QColor(CONF_COLOURS[worst]) if worst else None

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy = st.client.id, st.fy
        return lambda: self.svc.working(cid, fy)

    def reload(self) -> None:
        st = self.state
        on = st.client is not None
        for b in (self.tl_btn, self.pr_btn, self.build_btn, self.class_btn, self.claim_btn, self.split_btn,
                  self.undo_btn, self.hist_btn, self.rules_btn, self.rev_btn, self.final_btn, self.xlsx_btn,
                  self.pdf_btn):
            b.setEnabled(on)
        if not on:
            self.work = None
            self.model.set_rows([], [])
            self.steps.setText("Select a client.")
            return
        try:
            self.work = w = self.svc.working(st.client.id, st.fy)
        except ServiceError as exc:
            self.steps.setText(str(exc))
            return
        months = sorted({v.txn.period for v in w.views if v.txn.period})
        cur = self.month.currentData()
        self.month.blockSignals(True)
        self.month.clear()
        self.month.addItem("Every month", "")
        for m in months:
            self.month.addItem(m, m)
        self.month.setCurrentIndex(max(self.month.findData(cur), 0))
        self.month.blockSignals(False)
        has_tl = bool(w.postings_total and any(w.postings_total.values()))
        has_reg = bool(w.views)
        has_3b = any(x is not None for x in w.table6_3b.values())
        steps = [("1 Client & year", True), ("2 Import Tally data", has_reg or has_tl), ("3 Consolidate", has_reg),
                 ("4 Classify", has_reg and not w.unclassified), ("5 Review", has_reg and not w.to_review),
                 ("6 GSTR-2B / 3B", has_3b), ("7 GSTR-9 working", has_reg and has_3b),
                 ("8 GSTR-9C working", has_reg), ("9 Exceptions", not any(c.status == "fail" for c in w.controls)),
                 ("10 Finalise", bool(w.final))]
        self.steps.setText(f"<b>{st.client.name} · {st.fy}</b> &nbsp; " + " → ".join(
            f"<span style='color:{'#1B5E20' if ok else '#9E9E9E'}'>{'✔' if ok else '○'} {s}</span>" for s, ok in steps))
        rows, pay = [], []
        for k, b in w.by_nature.items():
            if b.count:
                rows.append([f"Nature: {NATURES[k]}", str(b.count), b.tax])
                pay.append(("nature", k))
        for k in STATUSES:
            b = w.by_status[k]
            if b.count:
                rows.append([f"Eligibility: {STATUSES[k]}", str(b.count), b.tax])
                pay.append(("status", k))
        for k in CLAIMS:
            b = w.by_claim.get(k)
            if b and b.count:
                rows.append([f"Claim: {CLAIMS[k]}", str(b.count), b.tax])
                pay.append(("claim", k))
        if w.inelig_claimed:
            rows.append(["Ineligible ITC that was claimed", "", w.inelig_claimed])
            pay.append(("view", "inelig_claimed"))
        rcm = w.total("treatment", list(RCM))
        rows.append(["RCM (overlay)", str(rcm.count), rcm.tax])
        pay.append(("view", "rcm"))
        rows.append([f"To review: {w.to_review}", "", None])
        pay.append(("view", "review"))
        self.o_model.set_rows(rows, pay)
        t6 = []
        from ...services.itc_register import T6_ROWS

        for row, label in T6_ROWS.items():
            ours = sum((x.tax for x in w.table6[row].values()), Decimal(0))
            b3 = w.table6_3b.get(row)
            theirs = sum(b3.values(), Decimal(0)) if b3 else None
            if not ours and not theirs:
                continue
            t6.append([label, ours, theirs, None if theirs is None else ours - theirs])
        self.t6_model.set_rows(t6)
        self.c_model.set_rows([[f"{c.code} {c.title}", c.detail] for c in w.controls], w.controls)
        self.final_btn.setText("Reopen" if w.final else "Finalise…")
        self.show_rows()

    def show_rows(self) -> None:
        w = self.work
        if w is None:
            return
        view, month = self.view_cb.currentData(), self.month.currentData()
        nat, tr, stt = self.nature_f.currentData(), self.treat_f.currentData(), self.status_f.currentData()
        clm = self.claim_f.currentData()
        text = self.find.text().strip().lower()
        out = []
        for v in w.views:
            t = v.txn
            if view != "adjust" and v.is_adjustment:
                continue
            if view == "adjust" and not v.is_adjustment:
                continue
            if view == "review" and not any(p.nature == "unclassified" or (p.basis == "auto" and p.confidence in (
                    "low", "manual")) for p in v.parts):
                continue
            if view == "unclassified" and not any(p.nature == "unclassified" for p in v.parts):
                continue
            if view == "pending" and not any(p.status == "pending" for p in v.parts):
                continue
            if view == "unverified" and not any(p.claim == "unknown" for p in v.parts):
                continue
            if view == "inelig_claimed" and not any(p.status == "blocked" and p.claim in AVAILED for p in v.parts):
                continue
            if clm and not any(p.claim == clm for p in v.parts):
                continue
            if view == "rcm" and not any(p.treatment in RCM or p.treatment == "import_s" for p in v.parts):
                continue
            if view in ("taxledger", "differs") and t.match != view:
                continue
            if view == "manual" and not any(p.basis == "manual" for p in v.parts):
                continue
            if view == "reviewed" and not t.reviewed:
                continue
            if month and t.period != month:
                continue
            if nat and not any(p.nature == nat for p in v.parts):
                continue
            if tr and not any(p.treatment == tr for p in v.parts):
                continue
            if stt and not any(p.status == stt for p in v.parts):
                continue
            if text and text not in f"{t.party} {t.gstin} {t.invoice_no} {t.voucher_no} {t.ledger}".lower():
                continue
            out.append(v)
        rows = []
        for v in out:
            t = v.txn
            rows.append([t.voucher_date.strftime("%d-%m-%Y") if t.voucher_date else "", t.invoice_no or t.voucher_no,
                         t.party, t.gstin, t.ledger, t.taxable, t.cgst, t.sgst, t.igst, t.cess, v.label("nature"),
                         v.label("treatment"), v.label("status"),
                         v.label("claim") + (f" {v.parts[0].claim_period}" if len({p.claim_period for p in v.parts}) == 1
                                             and v.parts and v.parts[0].claim_period else ""),
                         v.label("confidence"), v.label("basis"),
                         {"both": "register + tax ledger", "register": "purchase register", "taxledger": "tax ledger only",
                          "differs": "tax differs", "adjust": "set-off / adjustment"}.get(t.match, t.match),
                         "; ".join(dict.fromkeys(p.reason for p in v.parts if p.reason))])
        self.model.set_rows(rows, out)
        self.table.fit(240)

    def drill(self, row: int) -> None:
        if not self.o_model.payload or row >= len(self.o_model.payload):
            return
        kind, key = self.o_model.payload[row]
        for cb in (self.nature_f, self.treat_f, self.status_f, self.claim_f):
            cb.blockSignals(True)
            cb.setCurrentIndex(0)
            cb.blockSignals(False)
        self.view_cb.blockSignals(True)
        self.view_cb.setCurrentIndex(self.view_cb.findData(key if kind == "view" else "all"))
        self.view_cb.blockSignals(False)
        if kind == "nature":
            self.nature_f.setCurrentIndex(self.nature_f.findData(key))
        elif kind == "status":
            self.status_f.setCurrentIndex(self.status_f.findData(key))
        elif kind == "claim":
            self.claim_f.setCurrentIndex(self.claim_f.findData(key))
        else:
            self.show_rows()

    def selected(self) -> list:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.payload[r] for r in rows]

    def select(self, pred) -> int:
        from PySide6.QtCore import QItemSelectionModel

        sel = self.table.selectionModel()
        sel.clearSelection()
        n = 0
        for r, v in enumerate(self.model.payload or []):
            if pred(v):
                sel.select(self.proxy.mapFromSource(self.model.index(r, 0)),
                           QItemSelectionModel.Select | QItemSelectionModel.Rows)
                n += 1
        return n

    def _changed(self) -> None:
        self.state.notify()

    # ------------------------------------------------------------ actions
    def import_tax_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Input tax ledgers exported from TallyPrime", "", TL_FILTER)
        for p in paths:
            self.import_tax_path(p)

    def import_tax_path(self, path) -> bool:
        st = self.state
        try:
            _sf, tl, repeated = self.svc.import_tax_ledgers(st.client.id, st.fy, path, st.user)
        except (ServiceError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Tax ledgers", str(exc))
            return False
        self._changed()
        QMessageBox.information(self, "Tax ledgers", f"{len(tl.postings)} line(s) of {', '.join(tl.ledgers)} read"
                                + (f" ({repeated} already imported)" if repeated else "") +
                                ". Click 'Build / refresh register' to consolidate them with the purchase register.")
        return True

    def import_register_dialog(self) -> None:
        from ..import_flow import import_interactive
        from .workflow import FILE_FILTER

        path, _ = QFileDialog.getOpenFileName(self, "Purchase register", "", FILE_FILTER)
        if path and import_interactive(self, self.state, path, Source.BOOKS) is not None:
            self._changed()

    def build(self) -> dict | None:
        st = self.state
        try:
            stats = self.svc.build(st.client.id, st.fy, st.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Build register", str(exc))
            return None
        self._changed()
        QMessageBox.information(self, "Build register", f"{stats['documents']} purchase-register document(s); "
                                f"{stats['vouchers']} tax-ledger voucher(s): {stats['matched']} matched, "
                                f"{stats['differs']} with different tax, {stats['tax_ledger_only']} in the tax ledger "
                                f"only, {stats['adjustments']} set-off / adjustment(s) kept apart.")
        return stats

    def classify(self, values: dict | None = None) -> int:
        sel = [v for v in self.selected() if not v.is_adjustment]
        if not sel:
            QMessageBox.information(self, "Classify", "Select the transactions first.")
            return 0
        if values is None:
            dlg = ClassifyDialog(self, sel[0])
            if dlg.exec() != QDialog.Accepted:
                return 0
            values = {"nature": dlg.nature.currentData(), "treatment": dlg.treatment.currentData(),
                      "status": dlg.status.currentData(), "scope": dlg.scope.currentData(),
                      "word": dlg.word.text().strip(), "this_year": dlg.this_year.isChecked(),
                      "reason": dlg.reason.text().strip()}
        st = self.state
        dims = {k: values.get(k) or None for k in ("nature", "treatment", "status")}
        try:
            scope = values.get("scope") or ""
            if not scope:
                n = self.svc.set_class([v.txn.id for v in sel], st.user, values.get("reason", ""), **dims)
            else:
                t = sel[0].txn
                value, value2 = {"ledger": (t.ledger, ""), "gstin": (t.gstin, ""), "gstin_ledger": (t.gstin, t.ledger),
                                 "hsn": (t.hsn.split(",")[0], ""), "keyword": (values.get("word", ""), "")}[scope]
                self.svc.add_rule(st.client.id, scope, value, st.user, value2, dims["nature"] or "",
                                  dims["treatment"] or "", dims["status"] or "",
                                  st.fy if values.get("this_year") else "", values.get("reason", ""))
                n = sum(1 for v in self.svc.views(st.client.id, st.fy) if any(p.basis == "rule" for p in v.parts))
        except ServiceError as exc:
            QMessageBox.warning(self, "Classify", str(exc))
            return 0
        self._changed()
        return n

    def record_claim(self, claim: str | None = None, period: str = "", reason: str = "") -> int:
        """Record what was done with the ITC in GSTR-3B – classification and eligibility stay as they are."""
        sel = [v for v in self.selected() if not v.is_adjustment]
        if not sel:
            QMessageBox.information(self, "Record claim", "Select the transactions first.")
            return 0
        if claim is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Record ITC claim")
            form = QFormLayout(dlg)
            cb = _combo(CLAIMS)
            per = QLineEdit(sel[0].txn.period)
            per.setPlaceholderText("YYYY-MM")
            why = QLineEdit()
            form.addRow("ITC in GSTR-3B", cb)
            form.addRow("GSTR-3B period", per)
            form.addRow("Reason / evidence", why)
            form.addRow(QLabel("This does not change the nature, treatment or eligibility. Table 6 of GSTR-9 counts "
                               "only ITC claimed in the year's GSTR-3B."))
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            form.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return 0
            claim, period, reason = cb.currentData(), per.text().strip(), why.text().strip()
        try:
            n = self.svc.set_claim([v.txn.id for v in sel], claim, self.state.user, period, reason)
        except ServiceError as exc:
            QMessageBox.warning(self, "Record claim", str(exc))
            return 0
        self._changed()
        return n

    def split(self, run: bool = True):
        sel = self.selected()
        if len(sel) != 1 or sel[0].is_adjustment:
            QMessageBox.information(self, "Split", "Select one transaction.")
            return None
        dlg = SplitDialog(self, self.svc, self.svc.view(sel[0].txn.id), self.state.user)
        if not run:
            return dlg
        if dlg.exec() == QDialog.Accepted:
            self._changed()
        return dlg

    def undo(self) -> bool:
        sel = self.selected()
        if len(sel) != 1:
            QMessageBox.information(self, "Undo", "Select one transaction.")
            return False
        ok = self.svc.undo(sel[0].txn.id, self.state.user)
        if not ok:
            QMessageBox.information(self, "Undo", "No manual change to undo for this transaction.")
        self._changed()
        return ok

    def history(self, show: bool = True) -> list:
        import json

        sel = self.selected()
        if len(sel) != 1:
            QMessageBox.information(self, "History", "Select one transaction.")
            return []
        items = self.svc.history(sel[0].txn.id)
        lines = []
        for a in items:
            d = json.loads(a.details_json or "{}")
            after = d.get("after") or []
            what = ", ".join(f"{NATURES.get(p.get('nature'), '')} / {TREATMENTS.get(p.get('treatment'), '')} / "
                             f"{STATUSES.get(p.get('status'), '')}" for p in after) if isinstance(after, list) else ""
            lines.append(f"{a.at:%d-%m-%Y %H:%M} {a.user}: {a.action} {what} {('– ' + d['reason']) if d.get('reason') else ''}")
        if show:
            QMessageBox.information(self, "History", "\n".join(lines) or "No manual changes yet – the classification is "
                                    "the program's suggestion.")
        return lines

    def rules(self, delete_id: int | None = None) -> list:
        st = self.state
        rules = [r for r in self.svc.rules(st.client.id) if r.active]
        if delete_id is not None:
            self.svc.delete_rule(delete_id, st.user)
            self._changed()
            return [r for r in self.svc.rules(st.client.id) if r.active]
        dlg = QDialog(self)
        dlg.setWindowTitle("Mapping rules")
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        for r in rules:
            lst.addItem(f"#{r.id} {SCOPES.get(r.scope)} '{r.value}'{(' + ' + r.value2) if r.value2 else ''} → "
                        f"{NATURES.get(r.nature, '–')} / {TREATMENTS.get(r.treatment, '–')} / "
                        f"{STATUSES.get(r.status, '–')} ({r.financial_year or 'every year'})")
        lay.addWidget(lst)
        rm = QPushButton("Switch off selected rule")
        rm.clicked.connect(lambda: lst.currentRow() >= 0 and (self.svc.delete_rule(rules[lst.currentRow()].id, st.user),
                                                              lst.takeItem(lst.currentRow()), self._changed()))
        lay.addWidget(rm)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()
        return rules

    def mark_reviewed(self) -> int:
        sel = self.selected()
        if not sel:
            return 0
        n = self.svc.mark_reviewed([v.txn.id for v in sel], self.state.user)
        self._changed()
        return n

    def finalise(self, note: str | None = None, override: str | None = None) -> bool:
        st, w = self.state, self.work
        if w is None:
            return False
        if w.final:
            self.svc.reopen(st.client.id, st.fy, st.user)
            self._changed()
            return True
        ok, bad = w.can_finalise
        if note is None:
            note, okd = QInputDialog.getText(self, "Finalise", "Note for the file (who reviewed, what was checked):")
            if not okd:
                return False
        if not ok and override is None:
            override, okd = QInputDialog.getText(self, "Finalise despite failed controls",
                                                 "These controls fail:\n" + "\n".join(bad) + "\n\nWhy is it final anyway?")
            if not okd:
                return False
        try:
            self.svc.finalise(st.client.id, st.fy, st.user, note or "", override or "")
        except ServiceError as exc:
            QMessageBox.warning(self, "Finalise", str(exc))
            return False
        self._changed()
        return True

    def reporting_note(self, text: str | None = None) -> str:
        from ...services.annual_rules import set_note, table14_status

        st = self.state
        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, f"Reporting note – FY {st.fy}",
                                                     "What the year's notification says about GSTR-9 / 9C reporting "
                                                     "(leave empty to go back to the default):",
                                                     table14_status(st.db, st.fy))
            if not ok:
                return table14_status(st.db, st.fy)
        set_note(st.db, st.fy, text, st.user)
        self._changed()
        return table14_status(st.db, st.fy)

    def export(self, kind: str, path: str | None = None, open_file: bool = True):
        st = self.state
        if st.client is None:
            return None
        name = f"ITC_classification_{st.client.gstin}_{st.fy}.{kind}"
        path = path or QFileDialog.getSaveFileName(self, "Save", name, "Excel (*.xlsx)" if kind == "xlsx"
                                                   else "PDF (*.pdf)")[0]
        if not path:
            return None
        try:
            out = (self.svc.export_xlsx(st.client.id, st.fy, path) if kind == "xlsx" else
                   self.svc.export_pdf(st.client.id, st.fy, path,
                                       str(st.qsettings.value("reminder_signature", "")).strip()))
        except OSError as exc:
            QMessageBox.warning(self, "Save", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out))))
        return out


__all__ = ["ItcClassPage", "date"]
