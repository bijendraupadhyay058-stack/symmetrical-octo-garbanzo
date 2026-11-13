"""Advanced Ledger Classification & Bifurcation: the TallyPrime trial balance, every purchase / expense / fixed-asset
ledger classified or split, the summaries for GSTR-9 Table 6 and GSTR-9C Table 14, and the workbook / review PDF."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...core.money import fmt_inr
from ...gstr9.expenses import TABLE14
from ...ledgers.classify import ACCT_CLASSES, ELIGIBILITY, GST_CLASSES, GST_SOURCES
from ...services.bifurcation import BifurcationService
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary, section, sortable

FILTERS = {"scope": "Purchases, expenses & fixed assets", "pending": "Pending", "suggested": "Suggested – to approve",
           "partial": "Partly classified", "approved": "Approved", "warnings": "With warnings",
           "purchase": "Purchase ledgers", "expense": "Expense ledgers", "asset": "Fixed-asset ledgers",
           "all": "All ledgers of the trial balance"}
STATE_COLOURS = {"Pending": "#FFCDD2", "Suggested": "#FFF3C4", "Partly classified": "#FFCDD2", "Approved": "#C8E6C9"}
TB_FILTER = "Trial balance (*.xlsx *.xls *.csv *.xml);;All files (*)"


class BulkDialog(QDialog):
    """One classification for every selected ledger (whole ledger)."""

    def __init__(self, parent, nature: str = "expense"):
        super().__init__(parent)
        self.setWindowTitle("Classify selected ledgers (whole ledger)")
        form = QFormLayout(self)
        self.acct = QComboBox()
        self.acct.setEditable(True)
        self.acct.addItems(list(ACCT_CLASSES))
        self.gst = QComboBox()
        for k, v in GST_CLASSES.items():
            self.gst.addItem(v, k)
        self.src = QComboBox()
        for k, v in GST_SOURCES.items():
            self.src.addItem(v, k)
        self.head = QComboBox()
        self.head.addItem("–", "")
        for c, label in TABLE14:
            self.head.addItem(f"{c} {label[:40]}", c)
        self.elig = QComboBox()
        self.elig.addItem("(decide later)", "")
        for k, v in ELIGIBILITY.items():
            self.elig.addItem(v, k)
        for label, w in (("Accounting classification", self.acct), ("GST classification", self.gst),
                         ("Source of supply", self.src), ("GSTR-9C Table 14 head", self.head),
                         ("ITC eligibility", self.elig)):
            form.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class BifurcationPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.summary = state, None
        self.svc = BifurcationService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Ledger classification", "Advanced ledger classification & bifurcation: the "
                                                           "TallyPrime trial balance, each purchase, expense and fixed-asset "
                                                           "ledger classified or split, feeding GSTR-9 Table 6 and GSTR-9C "
                                                           "Table 14."))
        bar = QHBoxLayout()
        self.import_btn = primary("Import trial balance…")
        self.import_btn.clicked.connect(lambda: self.import_dialog())
        self.tally_btn = QPushButton("From TallyPrime…")
        self.tally_btn.setToolTip("Reads the ledgers and groups directly from TallyPrime (it must be open, with the "
                                  "XML server on port 9000)")
        self.tally_btn.clicked.connect(lambda: self.from_tally())
        self.suggest_btn = QPushButton("Suggest classifications")
        self.suggest_btn.clicked.connect(lambda: self.suggest())
        self.approve_btn = QPushButton("Approve selected")
        self.approve_btn.clicked.connect(lambda: self.approve())
        self.bulk_btn = QPushButton("Classify selected…")
        self.bulk_btn.clicked.connect(lambda: self.bulk())
        self.split_btn = QPushButton("Split / edit…")
        self.split_btn.clicked.connect(lambda: self.split())
        self.clear_btn = QPushButton("Reverse")
        self.clear_btn.setToolTip("Remove the classification of the selected ledgers (kept in the audit log)")
        self.clear_btn.clicked.connect(lambda: self.clear())
        self.base_btn = QPushButton("Amount to classify…")
        self.base_btn.setToolTip("For a fixed asset: the additions of the year instead of the closing balance")
        self.base_btn.clicked.connect(lambda: self.set_base())
        for b in (self.import_btn, self.tally_btn, self.suggest_btn, self.approve_btn, self.bulk_btn, self.split_btn,
                  self.clear_btn, self.base_btn):
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        fbar = QHBoxLayout()
        self.filter = QComboBox()
        for k, v in FILTERS.items():
            self.filter.addItem(v, k)
        self.filter.currentIndexChanged.connect(lambda _i: self.show_ledgers())
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search ledger or group…")
        self.find.textChanged.connect(lambda _t: self.show_ledgers())
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        for w in (QLabel("Show"), self.filter, self.find):
            fbar.addWidget(w)
        fbar.addWidget(self.status, 1)
        lay.addLayout(fbar)
        split = QSplitter(Qt.Horizontal)
        self.model = RowsModel(["Ledger", "Parent group", "Ledger amount", "Accounting classification",
                                "GST ITC classification", "9C head", "Taxable value", "IGST", "CGST", "SGST/UTGST",
                                "Cess", "ITC eligibility", "Classified", "Unallocated", "Status", "Remarks"],
                               kinds=["text", "text", "money", "text", "text", "text"] + ["money"] * 5 +
                               ["text", "money", "money", "text", "text"],
                               colors=self._colour)
        self.proxy = sortable(self.model)
        self.table = Table()
        self.table.setModel(self.proxy)
        self.table.setSelectionMode(Table.ExtendedSelection)
        self.table.doubleClicked.connect(lambda _i: self.split())
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.ready = QLabel()
        self.ready.setWordWrap(True)
        self.ready.setTextFormat(Qt.RichText)
        rl.addWidget(self.ready)
        rl.addWidget(section("Summary (click a line to see its ledgers)"))
        self.s_model = RowsModel(["", "Amount", "GST"], kinds=["text", "money", "money"])
        self.s_table = Table()
        self.s_table.setModel(self.s_model)
        self.s_table.setSortingEnabled(False)
        self.s_table.clicked.connect(lambda i: self.drill(i.row()))
        rl.addWidget(self.s_table, 1)
        rl.addWidget(section("GSTR-9 Table 6 – ITC availed by category"))
        self.t6_model = RowsModel(["Row / category", "Taxable", "ITC"], kinds=["text", "money", "money"])
        t6 = Table()
        t6.setModel(self.t6_model)
        t6.setSortingEnabled(False)
        rl.addWidget(t6, 1)
        ob = QHBoxLayout()
        self.xlsx_btn = QPushButton("Workbook (Excel)…")
        self.xlsx_btn.clicked.connect(lambda: self.export("xlsx"))
        self.pdf_btn = QPushButton("Review PDF…")
        self.pdf_btn.clicked.connect(lambda: self.export("pdf"))
        self.t14_btn = QPushButton("Send to GSTR-9C Table 14")
        self.t14_btn.clicked.connect(lambda: self.push_table14())
        for b in (self.xlsx_btn, self.pdf_btn, self.t14_btn):
            ob.addWidget(b)
        rl.addLayout(ob)
        split.addWidget(right)
        split.setSizes([1000, 420])
        lay.addWidget(split, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # ------------------------------------------------------------ display
    def _colour(self, row: int, col: int):
        v = self.model.payload[row] if self.model.payload else None
        if v is None:
            return None
        if col == 14:
            return QColor(next((c for k, c in STATE_COLOURS.items() if v.state.startswith(k)), "#FFFFFF"))
        if col == 13 and abs(v.unallocated) > 0.5 and v.in_scope:
            return QColor("#FFCDD2")
        return None

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy = st.client.id, st.fy
        return lambda: self.svc.summary(cid, fy)

    def reload(self) -> None:
        st = self.state
        enabled = st.client is not None
        for b in (self.import_btn, self.tally_btn, self.suggest_btn, self.approve_btn, self.bulk_btn, self.split_btn,
                  self.clear_btn, self.base_btn, self.xlsx_btn, self.pdf_btn, self.t14_btn):
            b.setEnabled(enabled)
        if not enabled:
            self.summary = None
            self.model.set_rows([], [])
            self.status.setText("Select a client.")
            return
        try:
            self.summary = sm = self.svc.summary(st.client.id, st.fy)
        except ServiceError as exc:
            self.status.setText(str(exc))
            return
        ok, reasons = sm.ready
        self.ready.setText(("<b style='color:#1B5E20'>Ready for the GSTR-9 / 9C working</b>" if ok else
                            "<b style='color:#B71C1C'>Not ready</b> – " + "; ".join(reasons)) +
                           f"<br>Trial balance {st.fy}: debit ₹{fmt_inr(sm.tb_debit)} · credit ₹{fmt_inr(sm.tb_credit)}")
        rows, payload = [], []
        for grp, t in sorted(sm.by_group.items()):
            rows.append([f"Accounting: {grp}", t.value, t.tax])
            payload.append(("group", grp))
        for k, t in sm.by_gst.items():
            if t.value:
                rows.append([f"GST: {t.label}", t.value, t.tax])
                payload.append(("gst", k))
        for label, key, n in (("Ledgers pending", "pending", sm.count("Pending")),
                              ("Suggested – to approve", "suggested", sm.count("Suggested")),
                              ("Partly classified", "partial", sm.count("Partly")),
                              ("Ledgers with warnings", "warnings", sum(1 for v in sm.in_scope if v.warnings))):
            rows.append([f"{label}: {n}", None, None])
            payload.append(("filter", key))
        rows.append(["Unallocated amount", sm.unallocated, None])
        payload.append(("filter", "warnings"))
        self.s_model.set_rows(rows, payload)
        self.s_table.resizeColumnsToContents()
        t6 = []
        for (row, g), t in sorted(sm.table6.items()):
            t6.append([f"{row} {GST_CLASSES[g]}", t.taxable, t.tax])
        d = sm.difference_6b
        if d is not None:
            t6.append(["6B less GSTR-3B 4(A)(5)", None, sum(d.values())])
        self.t6_model.set_rows(t6)
        self.show_ledgers()

    def show_ledgers(self, gst: str | None = None, group: str | None = None) -> None:
        sm = self.summary
        if sm is None:
            return
        f = self.filter.currentData()
        text = self.find.text().strip().lower()
        out = []
        for v in sm.views:
            lg = v.ledger
            if f == "all":
                pass
            elif not v.in_scope:
                continue
            elif f in ("purchase", "expense", "asset") and lg.nature != f:
                continue
            elif f == "pending" and v.state != "Pending":
                continue
            elif f == "suggested" and not v.state.startswith("Suggested"):
                continue
            elif f == "partial" and v.state != "Partly classified":
                continue
            elif f == "approved" and v.state != "Approved":
                continue
            elif f == "warnings" and not v.warnings:
                continue
            if gst and not any(s.gst_class == gst for s in v.splits):
                continue
            if group and not any(ACCT_CLASSES.get(s.acct_class, "Other") == group for s in v.splits):
                continue
            if text and text not in f"{lg.name} {lg.parent} {lg.primary_group}".lower():
                continue
            out.append(v)
        rows = []
        for v in out:
            lg, g = v.ledger, v.gst
            rows.append([lg.name, lg.parent or lg.primary_group, lg.base, v.label("acct_class"), v.label("gst_class"),
                         v.label("head_9c"), g["taxable"], g["igst"], g["cgst"], g["sgst"], g["cess"],
                         v.label("eligibility"), v.classified if v.splits else None,
                         v.unallocated if v.in_scope else None, v.state,
                         "; ".join(([lg.base_note] if lg.base_note else []) + v.warnings + ([lg.remarks] if lg.remarks
                                                                                            else []))])
        self.model.set_rows(rows, out)
        self.table.fit(260)
        n = len(sm.in_scope)
        self.status.setText(f"{len(sm.views)} ledgers · {n} to classify · <b>{sm.count('Approved')}</b> approved · "
                            f"{sm.count('Suggested')} suggested · {sm.count('Pending')} pending · showing {len(out)}")

    def drill(self, row: int) -> None:
        if not self.s_model.payload or row >= len(self.s_model.payload):
            return
        kind, key = self.s_model.payload[row]
        if kind == "filter":
            self.filter.setCurrentIndex(self.filter.findData(key))
            return
        self.filter.blockSignals(True)
        self.filter.setCurrentIndex(self.filter.findData("scope"))
        self.filter.blockSignals(False)
        self.show_ledgers(gst=key if kind == "gst" else None, group=key if kind == "group" else None)

    def selected(self) -> list:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.payload[r] for r in rows]

    def select_ledgers(self, names: list[str]) -> None:
        from PySide6.QtCore import QItemSelectionModel

        sel = self.table.selectionModel()
        sel.clearSelection()
        for r, v in enumerate(self.model.payload or []):
            if v.ledger.name in names:
                idx = self.proxy.mapFromSource(self.model.index(r, 0))
                sel.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _changed(self) -> None:
        self.state.notify()

    # ------------------------------------------------------------ actions
    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Trial balance exported from TallyPrime", "", TB_FILTER)
        if path:
            self.import_path(path)

    def import_path(self, path) -> bool:
        st = self.state
        try:
            _sf, tb, stats = self.svc.import_tb(st.client.id, st.fy, path, st.user)
        except (ServiceError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Trial balance", str(exc))
            return False
        self._changed()
        msg = (f"{len(tb.rows)} ledger(s) read ({tb.layout}). New {stats['new']}, already there {stats['updated']}"
               f" (amount changed {stats['changed']}), removed {stats['removed']}.\nDebit ₹{fmt_inr(tb.total_debit)} · "
               f"credit ₹{fmt_inr(tb.total_credit)}")
        if tb.warnings:
            msg += "\n\n" + "\n".join(tb.warnings[:8])
        msg += "\n\nNext: click 'Suggest classifications', check the suggestions and approve them."
        QMessageBox.information(self, "Trial balance", msg)
        return True

    def from_tally(self, company: str | None = None) -> bool:
        from ...importers.tally_xml import TallyClient

        st = self.state
        url = str(st.qsettings.value("tally_url", "")) or ""
        try:
            if company is None:
                names = TallyClient(url or "http://localhost:9000").companies()
                company, ok = QInputDialog.getItem(self, "From TallyPrime", "Company:", names, 0, False)
                if not ok:
                    return False
            folder = Path(st.db.data_dir) / "tally"
            _sf, tb, stats = self.svc.fetch_from_tally(st.client.id, st.fy, company, folder, url, st.user)
        except (ConnectionError, ValueError, ServiceError) as exc:
            QMessageBox.warning(self, "From TallyPrime", str(exc))
            return False
        self._changed()
        QMessageBox.information(self, "From TallyPrime", f"{len(tb.rows)} ledger(s) read from {company}. New "
                                f"{stats['new']}, updated {stats['updated']}, removed {stats['removed']}.")
        return True

    def suggest(self) -> int:
        st = self.state
        n = self.svc.suggest_all(st.client.id, st.fy, st.user)
        self._changed()
        QMessageBox.information(self, "Suggest classifications", f"{n} ledger(s) given a suggestion (yellow). Check "
                                "each – the confidence shows how sure it is – then select and 'Approve selected', or "
                                "change it with 'Split / edit'. Nothing counts until you approve it.")
        return n

    def approve(self) -> int:
        sel = self.selected()
        if not sel:
            QMessageBox.information(self, "Approve", "Select the ledgers to approve.")
            return 0
        n = self.svc.approve([v.ledger.id for v in sel], self.state.user)
        self._changed()
        return n

    def bulk(self, values: tuple | None = None) -> int:
        sel = [v for v in self.selected() if v.in_scope]
        if not sel:
            QMessageBox.information(self, "Classify", "Select the purchase / expense / fixed-asset ledgers first.")
            return 0
        if values is None:
            dlg = BulkDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return 0
            values = (dlg.acct.currentText(), dlg.gst.currentData(), dlg.src.currentData(), dlg.head.currentData(),
                      dlg.elig.currentData())
        acct, gst, src, head, elig = values
        try:
            n = self.svc.classify_whole([v.ledger.id for v in sel], acct, gst, self.state.user, src, head, elig)
        except ServiceError as exc:
            QMessageBox.warning(self, "Classify", str(exc))
            return 0
        self._changed()
        return n

    def split(self, view=None, run: bool = True):
        from ..dialogs.ledger_split import LedgerSplitDialog

        if view is None:
            sel = self.selected()
            if len(sel) != 1:
                QMessageBox.information(self, "Split / edit", "Select one ledger.")
                return None
            view = sel[0]
        if not view.in_scope:
            QMessageBox.information(self, "Split / edit", "This ledger is not a purchase, expense or fixed-asset "
                                    "ledger. Change its nature with the 'All ledgers' view if it should be classified.")
            return None
        st = self.state
        dlg = LedgerSplitDialog(self, self.svc, self.svc.view(view.ledger.id), st.client.id, st.fy, st.user)
        if not run:
            return dlg
        if dlg.exec() == QDialog.Accepted:
            self._changed()
        return dlg

    def clear(self) -> int:
        sel = self.selected()
        if not sel or QMessageBox.question(self, "Reverse", f"Remove the classification of {len(sel)} ledger(s)? "
                                           "It stays in the audit log.") != QMessageBox.Yes:
            return 0
        n = self.svc.clear([v.ledger.id for v in sel], self.state.user)
        self._changed()
        return n

    def set_base(self, amount=None, note: str | None = None) -> bool:
        sel = self.selected()
        if len(sel) != 1:
            QMessageBox.information(self, "Amount to classify", "Select one ledger.")
            return False
        v = sel[0]
        if amount is None:
            amount, ok = QInputDialog.getText(self, "Amount to classify", f"{v.ledger.name}: amount to classify "
                                              "(e.g. additions of the year per the fixed asset register):",
                                              text=str(v.ledger.debit or v.ledger.base))
            if not ok:
                return False
            note, ok = QInputDialog.getText(self, "Amount to classify", "What is this amount?",
                                            text="Additions per fixed asset register")
            if not ok:
                return False
        try:
            self.svc.set_base(v.ledger.id, amount, note or "", self.state.user)
        except (ServiceError, ArithmeticError) as exc:
            QMessageBox.warning(self, "Amount to classify", str(exc))
            return False
        self._changed()
        return True

    def export(self, kind: str, path: str | None = None, open_file: bool = True):
        st = self.state
        if st.client is None:
            return None
        name = f"Ledger_bifurcation_{st.client.gstin}_{st.fy}.{kind}"
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
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out

    def push_table14(self) -> int:
        st = self.state
        try:
            n = self.svc.push_table14(st.client.id, st.fy, st.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "GSTR-9C Table 14", str(exc))
            return 0
        self._changed()
        QMessageBox.information(self, "GSTR-9C Table 14", f"{n} Table 14 figure(s) updated from the classification "
                                "(GSTR-3B & annual → GSTR-9C). Each change is in the audit log.")
        return n
