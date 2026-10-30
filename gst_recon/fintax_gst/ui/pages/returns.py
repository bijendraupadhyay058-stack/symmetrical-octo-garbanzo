"""GSTR-3B Table 4 working, GSTR-9 Table 8 and IMS comparison pages."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, Signal

from ...core.models import Source
from ...itc.annual import default_cutoff, fy_months
from ...reports.annual_report import export_annual
from ...services.common import ServiceError
from ...services.reconciliation import months_between
from ..import_flow import import_interactive
from ..state import AppState
from ..theme import AMBER, NAVY, RED, TEAL, money
from ..widgets import KpiCard, LazyPage, RowsModel, Table, page_header, primary, section, sortable
from ..workers import run_task
from .workflow import FILE_FILTER

SEV_COLORS = {"high": "#FFCDD2", "medium": "#FFF3C4", "info": "#E3F2FD"}


class ReturnsPage(LazyPage):
    """GSTR-3B import, Table 4 working with classified differences, and GSTR-9 Table 8."""

    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("GSTR-3B & annual", "Compare GSTR-2B, books / claim register and GSTR-3B; "
                                                      "classify differences; prepare the GSTR-9 Table 8 working."))
        top = QHBoxLayout()
        self.import_btn = primary("Import GSTR-3B…")
        self.import_btn.clicked.connect(self.import_dialog)
        self.imported_lbl = QLabel()
        self.imported_lbl.setObjectName("Muted")
        top.addWidget(self.import_btn)
        top.addWidget(self.imported_lbl, 1)
        lay.addLayout(top)
        tabs = QTabWidget()
        tabs.addTab(self._table4_tab(), "GSTR-3B Table 4 working")
        tabs.addTab(self._annual_tab(), "GSTR-9 Table 8 (8A–8D)")
        tabs.addTab(self._gstr9_tab(), "GSTR-9 Tables 4–7, 9")
        tabs.addTab(self._gstr9c_tab(), "GSTR-9C")
        lay.addWidget(tabs, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _table4_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.from_cb, self.to_cb = QComboBox(), QComboBox()
        for cb in (self.from_cb, self.to_cb):
            cb.setMinimumWidth(110)
        self.show_btn = primary("Show working")
        self.show_btn.clicked.connect(self.show_table4)
        for x in (QLabel("From"), self.from_cb, QLabel("To"), self.to_cb, self.show_btn):
            row.addWidget(x)
        row.addStretch()
        lay.addLayout(row)
        split = QSplitter(Qt.Vertical)
        self.t4_model = RowsModel(["Period", "Table", "Description", "GSTR-2B (auto)", "Books / review", "3B filed",
                                   "3B − 2B", "3B − Books"],
                                  kinds=["text", "text", "text", "money", "money", "money", "money", "money"])
        self.t4 = Table()
        self.t4.setModel(self.t4_model)
        self.t4.setSortingEnabled(False)
        split.addWidget(self.t4)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Classified differences"))
        self.find_model = RowsModel(["Period", "Type", "Severity", "Finding", "Amount"],
                                    kinds=["text", "text", "text", "text", "money"], colors=self._find_color)
        self.find = Table()
        self.find.setModel(sortable(self.find_model))
        bl.addWidget(self.find)
        self.basis_lbl = QLabel()
        self.basis_lbl.setObjectName("Muted")
        self.basis_lbl.setWordWrap(True)
        bl.addWidget(self.basis_lbl)
        split.addWidget(box)
        lay.addWidget(split, 1)
        return w

    def _gstr9_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.g9_btn = primary("Prepare GSTR-9 working")
        self.g9_btn.clicked.connect(self.show_gstr9)
        self.g9_export_btn = QPushButton("Export annual workbook…")
        self.g9_export_btn.clicked.connect(self.export_annual)
        row.addWidget(self.g9_btn)
        row.addWidget(self.g9_export_btn)
        hint = QLabel("Returns = GSTR-1 (Tables 4–5) and GSTR-3B (4G, 6, 7); Books = sales register. "
                      "A working paper for review, not the return as filed.")
        hint.setObjectName("Muted")
        row.addWidget(hint, 1)
        lay.addLayout(row)
        split = QSplitter(Qt.Vertical)
        self.g9_model = RowsModel(["Table", "Description", "Returns taxable", "Returns tax", "Books taxable",
                                   "Books tax", "Books − Returns tax", "Note"],
                                  kinds=["text", "text", "money", "money", "money", "money", "money", "text"],
                                  colors=self._g9_color)
        self.g9_table = Table()
        self.g9_table.setModel(self.g9_model)
        self.g9_table.setSortingEnabled(False)
        split.addWidget(self.g9_table)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Table 9 – tax payable (Table 4N) and declared in GSTR-3B; amendments"))
        self.g9_tax_model = RowsModel(["Tax", "Payable (4N)", "Declared in 3B", "Paid cash", "Paid ITC",
                                       "Payable − Paid"],
                                      kinds=["text", "money", "money", "money", "money", "money"])
        self.g9_t9 = Table()
        self.g9_t9.setModel(self.g9_tax_model)
        self.g9_t9.setSortingEnabled(False)
        self.g9_t9.setMinimumHeight(140)
        bl.addWidget(self.g9_t9)
        self.g9_am_model = RowsModel(["Period", "Section", "Document", "Original", "Change taxable", "Change tax",
                                      "Row", "Status"],
                                     kinds=["text", "text", "text", "text", "money", "money", "text", "text"])
        am = Table()
        am.setModel(self.g9_am_model)
        bl.addWidget(am)
        self.g9_note = QLabel()
        self.g9_note.setObjectName("Muted")
        self.g9_note.setWordWrap(True)
        bl.addWidget(self.g9_note)
        split.addWidget(box)
        split.setSizes([420, 330])
        lay.addWidget(split, 1)
        return w

    def _gstr9c_tab(self) -> QWidget:
        from ...gstr9.entered import ITEM_LABELS
        from ...gstr9.expenses import TABLE14
        from ...gstr9.reconciliation_9c import INPUT_ITEMS, LABELS, REASON_ITEMS

        parts = {"V": "value", "T": "total ITC", "E": "eligible ITC"}
        t14 = {f"{c}-{p}": f"{label} – {name}" for c, label in TABLE14 for p, name in parts.items()}

        w = QWidget()
        lay = QVBoxLayout(w)
        form = QHBoxLayout()
        self.c9_item = QComboBox()
        for code in INPUT_ITEMS:
            label = LABELS.get(code) or ITEM_LABELS.get(code) or t14.get(code) or {
                "9INT": "Interest", "9FEE": "Late fee", "9PEN": "Penalty", "9OTH": "Others (Table 9)"}.get(code, code)
            self.c9_item.addItem(f"{code} – {label}"[:90], code)
        for code, label in REASON_ITEMS.items():
            self.c9_item.addItem(f"{code} – {label}", code)
        self.c9_item.setMinimumWidth(300)
        self.c9_item.setMaximumWidth(360)
        self.c9_amount = QLineEdit()
        self.c9_amount.setPlaceholderText("Amount per audited accounts")
        self.c9_amount.setMinimumWidth(170)
        self.c9_note = QLineEdit()
        self.c9_note.setPlaceholderText("Source / reason")
        self.c9_save = primary("Record")
        self.c9_save.clicked.connect(self.save_9c_input)
        self.c9_clear = QPushButton("Clear (use default)")
        self.c9_clear.clicked.connect(lambda: self.save_9c_input(clear=True))
        self.c9_btn = primary("Prepare GSTR-9C")
        self.c9_btn.clicked.connect(self.show_9c)
        self.c9_exp_btn = QPushButton("Import expense ledger…")
        self.c9_exp_btn.setToolTip("Table 14: ledger heads with amount and ITC (Excel/CSV)")
        self.c9_exp_btn.clicked.connect(self.import_expense_dialog)
        form.addWidget(self.c9_exp_btn)
        for x in (self.c9_btn, self.c9_item, self.c9_amount, self.c9_note, self.c9_save, self.c9_clear):
            form.addWidget(x)
        lay.addLayout(form)
        split = QSplitter(Qt.Vertical)
        self.c9_model = RowsModel(["Table", "Description", "Amount", "Source"],
                                  kinds=["text", "text", "money", "text"], colors=self._c9_color)
        t = Table()
        t.setModel(self.c9_model)
        t.setSortingEnabled(False)
        self.c9_table = t
        split.addWidget(t)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Table 9 – rate-wise tax per books vs paid per GSTR-9"))
        self.c9_rate_model = RowsModel(["Rate / item", "Taxable", "CGST", "SGST", "IGST", "Cess"],
                                       kinds=["text", "money", "money", "money", "money", "money"])
        self.c9_rt = Table()
        self.c9_rt.setModel(self.c9_rate_model)
        self.c9_rt.setSortingEnabled(False)
        bl.addWidget(self.c9_rt)
        self.c9_note_lbl = QLabel()
        self.c9_note_lbl.setObjectName("Muted")
        self.c9_note_lbl.setWordWrap(True)
        bl.addWidget(self.c9_note_lbl)
        split.addWidget(box)
        split.setSizes([430, 300])
        lay.addWidget(split, 1)
        return w

    def _c9_color(self, row, _col):
        r = self.c9_model.rows[row]
        if str(r[3]).startswith("default"):
            return QColor("#FFF3C4")
        return QColor("#E0F2F1") if r[0] in ("5P", "5R", "7E", "7G", "12D", "12F") else None

    def show_9c(self) -> None:
        from ...services.gstr9c import Gstr9cService

        st_ = self.state
        if st_.client is None:
            return
        st = Gstr9cService(st_.db).statement(st_.client.id, st_.fy)
        rows = [[x.code, x.label, x.amount, x.source] for x in st.table5 + st.table7 + st.table12]
        rows += [[x.code, x.label, x.itc_eligible, f"value {money(x.value)}; total ITC {money(x.itc_total)}"]
                 for x in st.table14 if x.value or x.itc_total or x.itc_eligible]
        rows += [["14R", "Total eligible ITC availed on expenses", st.table14_total, "computed"],
                 ["14S", "ITC claimed in GSTR-9", st.table14_claimed, "GSTR-9 7J"],
                 ["14T", "Un-reconciled ITC on expenses (S − R)", st.table14_unreconciled, "computed"]]
        self.c9_model.set_rows(rows)
        self.c9_table.fit(520)
        tot, paid, un = st.table9_total, st.table9_paid, st.table9_unreconciled
        rows = [[r.rate, r.taxable, r.cgst, r.sgst, r.igst, r.cess] for r in st.table9]
        rows.append(["9P Total per books", None, tot["cgst"], tot["sgst"], tot["igst"], tot["cess"]])
        rows.append(["9Q Paid per GSTR-9", None, paid.get("cgst"), paid.get("sgst"), paid.get("igst"),
                     paid.get("cess")])
        rows.append(["9R Un-reconciled", None, un.get("cgst"), un.get("sgst"), un.get("igst"), un.get("cess")])
        self.c9_rate_model.set_rows(rows)
        self.c9_rt.fit(260)
        reasons = [f"{k}: {v}" for k, v in st.reasons.items() if v]
        self.c9_note_lbl.setText(" ".join(reasons + st.notes))

    def import_expense_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Expense ledger (Table 14)", "", "Excel/CSV (*.xlsx *.csv)")
        if path:
            self.import_expense_path(path)

    def import_expense_path(self, path) -> bool:
        from ...services.gstr9c import Gstr9cService

        st = self.state
        if st.client is None:
            return False
        svc = Gstr9cService(st.db)
        try:
            lines = svc.import_expenses(st.client.id, st.fy, path, st.session, apply=False)
        except (ServiceError, ValueError) as exc:
            QMessageBox.warning(self, "Expense ledger", str(exc))
            return False
        summary = "\n".join(f"{x.table_row}  {x.head[:40]:<40} ITC {money(x.itc_eligible)}" for x in lines[:40])
        if QMessageBox.question(self, "Expense ledger", f"{len(lines)} ledger head(s) will replace the Table 14 "
                                f"figures:\n\n{summary}\n\nSave?") != QMessageBox.Yes:
            return False
        svc.import_expenses(st.client.id, st.fy, path, st.session)
        self.show_9c()
        return True

    def save_9c_input(self, clear: bool = False) -> None:
        from ...services.gstr9c import Gstr9cService

        st = self.state
        if st.client is None:
            return
        code = self.c9_item.currentData()
        amount = None if clear or code.startswith("R") or not self.c9_amount.text().strip() \
            else self.c9_amount.text()
        note = "" if clear else self.c9_note.text()
        try:
            Gstr9cService(st.db).set_input(st.client.id, st.fy, code, amount, note, st.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "GSTR-9C", str(exc))
            return
        self.c9_amount.clear()
        self.c9_note.clear()
        self.show_9c()

    SUBTOTALS = {"4H", "4M", "4N", "5G", "5L", "5M", "5N", "6I", "6J", "7I", "7J"}

    def _g9_color(self, row, _col):
        return QColor("#E0F2F1") if self.g9_model.rows[row][0] in self.SUBTOTALS else None

    def show_gstr9(self) -> None:
        from ...services.gstr9 import Gstr9Service

        st = self.state
        if st.client is None:
            return
        w = Gstr9Service(st.db).working(st.client.id, st.fy)
        rows = []
        for r in w.table4 + w.table5 + w.table6 + w.table7 + w.table10_14:
            d = r.diff
            rows.append([r.code, r.label,
                         r.gstr1.taxable if r.gstr1 and r in w.table4 + w.table5 + w.table10_14 else None,
                         r.gstr1.total if r.gstr1 else None, r.books.taxable if r.books else None,
                         r.books.total if r.books else None, d.total if d else None, r.note])
        for x in w.table15 + w.table16:
            tax = sum((x.values.get(k, 0) for k in ("C", "S", "I", "X")), 0)
            if tax or x.values.get("T"):
                rows.append([x.code, x.label, x.values.get("T"), tax, None, None, None, "entered"])
        self.g9_model.set_rows(rows)
        self.g9_table.fit(520)
        self.g9_tax_model.set_rows([[x.head, x.payable, x.declared, x.paid_cash, x.paid_itc, x.unpaid]
                                    for x in w.table9])
        self.g9_t9.fit(260)
        self.g9_am_model.set_rows([[a["period"], a["section"], a["document"], a["original"],
                                    a["delta"].taxable if a["delta"] else None,
                                    a["delta"].total if a["delta"] else None, a["row"], a["status"]]
                                   for a in w.amendments])
        self.g9_note.setText(" ".join(w.notes))

    def _annual_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.cutoff_cb = QComboBox()
        self.portal_8a = QLineEdit()
        self.portal_8a.setPlaceholderText("optional – Table 8A total from the portal")
        self.annual_btn = primary("Compute")
        self.annual_btn.clicked.connect(self.show_annual)
        self.export_annual_btn = QPushButton("Export annual workbook…")
        self.export_annual_btn.clicked.connect(self.export_annual)
        self.import_8a_btn = QPushButton("Import Table 8A…")
        self.import_8a_btn.setToolTip("GSTR-9 Table 8A document details downloaded from the GST portal (Excel/JSON)")
        self.import_8a_btn.clicked.connect(self.import_8a_dialog)
        self.recon_8a_btn = QPushButton("Reconcile books vs 8A")
        self.recon_8a_btn.clicked.connect(self.reconcile_8a)
        for x in (QLabel("GSTR-2B up to"), self.cutoff_cb, QLabel("Portal 8A"), self.portal_8a, self.annual_btn,
                  self.export_annual_btn, self.import_8a_btn, self.recon_8a_btn):
            row.addWidget(x)
        row.addStretch()
        lay.addLayout(row)
        grid = QGridLayout()
        self.t8_cards = {k: KpiCard(label, color) for k, label, color in (
            ("a", "8A ITC as per GSTR-2B", TEAL), ("b", "8B ITC availed in 3B 4(A)(5)", NAVY),
            ("c", "8C availed in next year", NAVY), ("d", "8D = 8A − (8B + 8C)", AMBER))}
        for i, c in enumerate(self.t8_cards.values()):
            grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        self.t8_note = QLabel()
        self.t8_note.setWordWrap(True)
        lay.addWidget(self.t8_note)
        self.month_model = RowsModel(["Month", "Books ITC", "GSTR-2B ITC", "3B 4(A)(5)", "3B 4(B)", "3B 4(C)",
                                      "Claimed (register)"],
                                     kinds=["text", "money", "money", "money", "money", "money", "money"])
        t = Table()
        t.setModel(self.month_model)
        t.setSortingEnabled(False)
        lay.addWidget(t, 1)
        return w

    def _find_color(self, row, col):
        if col != 2:
            return None
        return QColor(SEV_COLORS.get(str(self.find_model.rows[row][2]).lower(), "#FFFFFF"))

    # ---------------------------------------------------------------- data
    def reload(self) -> None:
        st = self.state
        self.import_btn.setEnabled(st.can("import") and st.client is not None)
        self.import_8a_btn.setEnabled(st.can("import") and st.client is not None)
        self.recon_8a_btn.setEnabled(st.can("reconcile") and st.client is not None)
        for b in (self.c9_save, self.c9_clear, self.c9_exp_btn):
            b.setEnabled(st.can("review") and st.client is not None)
        months = fy_months(st.fy)
        for cb in (self.from_cb, self.to_cb):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(months)
            if cur in months:
                cb.setCurrentText(cur)
            cb.blockSignals(False)
        cut = [m for m in months_between(months[0], f"{int(st.fy[:4]) + 1}-12")]
        self.cutoff_cb.clear()
        self.cutoff_cb.addItems(cut)
        self.cutoff_cb.setCurrentText(default_cutoff(st.fy))
        if st.client is None:
            self.imported_lbl.setText("Select a client.")
            return
        periods = sorted(st.gstr3b.values(st.client.id))
        self.imported_lbl.setText("GSTR-3B imported for: " + (", ".join(periods) if periods else "none yet"))
        run = st.run_context()
        if run is not None and run.run.period_from in months:
            self.from_cb.setCurrentText(run.run.period_from)
            self.to_cb.setCurrentText(run.run.period_to if run.run.period_to in months else run.run.period_from)
        self.show_table4()
        self.show_annual()

    def show_table4(self) -> None:
        st = self.state
        if st.client is None:
            return
        periods = months_between(self.from_cb.currentText(), self.to_cb.currentText())
        workings = st.itc.table4(st.client.id, periods, date.today())
        rows, frows, bases = [], [], set()
        for w in workings:
            bases.add(f"{w.period}: {w.books_basis}" + (f"; Rule 36(4) limit {w.provisional_pct}%"
                                                        if w.provisional_pct else ""))
            for r in w.rows:
                rows.append([w.period, r.code, r.label, r.auto_2b.total, r.books.total,
                             r.filed.total if r.filed else None, r.diff_filed_2b, r.diff_filed_books])
            frows += [[w.period, f.kind.title(), f.severity.upper(), f.text, f.amount] for f in w.findings]
        self.t4_model.set_rows(rows)
        self.t4.fit(420)
        self.find_model.set_rows(frows)
        self.find.fit(520)
        self.basis_lbl.setText("Books column basis – " + " · ".join(sorted(bases)) +
                               ". Working paper for review, not the amounts to be filed.")

    def show_annual(self) -> None:
        st = self.state
        if st.client is None:
            return
        try:
            portal = Decimal(self.portal_8a.text().replace(",", "")) if self.portal_8a.text().strip() else None
        except InvalidOperation:
            QMessageBox.warning(self, "Annual", "Portal 8A must be a number")
            return
        t = st.itc.annual(st.client.id, st.fy, self.cutoff_cb.currentText(), portal)
        for k, v in (("a", t.a), ("b", t.b), ("c", t.c), ("d", t.d)):
            self.t8_cards[k].set(money(v.total, True), f"IGST {money(v.igst)} · CGST {money(v.cgst)}")
        notes = t.basis_notes()
        if t.b_periods_missing:
            notes.append(f"GSTR-3B not imported for {len(t.b_periods_missing)} month(s) – 8B incomplete.")
        notes.append(f"{len(t.docs_8a_not_in_books)} 8A document(s) of the year are not in books; "
                     f"{len(t.books_not_in_8a)} books document(s) are not in 8A.")
        self.t8_note.setText(" ".join(notes))
        self.month_model.set_rows([[m.month, m.books_itc, m.gstr2b_itc, m.filed_4a5, m.filed_4b, m.filed_4c,
                                    m.claimed_register] for m in t.months])

    # ------------------------------------------------------------- actions
    def import_8a_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "GSTR-9 Table 8A document details", "", FILE_FILTER)
        if path:
            self.import_8a_path(path)

    def import_8a_path(self, path):
        result = import_interactive(self, self.state, path, Source.GSTR8A, None)
        self.reload()
        if result is not None:
            self.show_annual()
        return result

    def reconcile_8a(self) -> None:
        """Document-level reconciliation of the whole year's books with Table 8A (same engine)."""
        st = self.state
        if st.client is None:
            return
        months = fy_months(st.fy)
        task = run_task(self, "Reconciling books vs Table 8A", st.recon.run, st.client.id, months[0], months[-1],
                        st.recon_settings(), compare_with=Source.GSTR8A, user=st.user)
        if not task.ok:
            QMessageBox.information(self, "Table 8A", task.message)
            return
        st.set_run(task.result_value)
        st.notify()
        self.navigate.emit("exceptions")

    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "GSTR-3B (portal JSON or template)", "",
                                              "GSTR-3B (*.json *.csv *.xlsx);;All files (*)")
        if path:
            self.import_path(path)

    def import_path(self, path, period: str | None = None) -> bool:
        st = self.state
        task = run_task(self, "Importing GSTR-3B", st.gstr3b.import_file, st.client.id, path, period, st.user,
                        cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "GSTR-3B", task.message)
            return False
        _sf, preview = task.result_value
        if preview.warnings:
            QMessageBox.information(self, "GSTR-3B", "\n".join(preview.warnings))
        st.notify(keep_cache=True)
        self.reload()
        return True

    def export_annual(self, out_dir: str | None = None) -> Path | None:
        st = self.state
        if st.client is None:
            return None
        out_dir = out_dir or QFileDialog.getExistingDirectory(self, "Folder for the annual workbook")
        if not out_dir:
            return None
        portal = self.portal_8a.text().replace(",", "").strip() or None
        try:
            path = export_annual(st.db, st.client.id, st.fy, out_dir, self.cutoff_cb.currentText(),
                                 Decimal(portal) if portal else None, st.user)
        except (ServiceError, InvalidOperation) as exc:
            QMessageBox.warning(self, "Annual", str(exc))
            return None
        QMessageBox.information(self, "Annual", f"Saved {path}")
        return path


class ImsPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("IMS review", "Invoice Management System actions compared with books and "
                                                "GSTR-2B. Nothing is changed on the GST portal by this software – "
                                                "observations tell you what to check or do there."))
        row = QHBoxLayout()
        self.period_cb = QComboBox()
        self.period_cb.currentIndexChanged.connect(lambda _i: self.reload())
        self.attention = QCheckBox("Needs attention only")
        self.attention.toggled.connect(lambda _c: self.reload())
        self.import_btn = primary("Import IMS download…")
        self.import_btn.clicked.connect(self.import_dialog)
        for x in (QLabel("Period"), self.period_cb, self.attention, self.import_btn):
            row.addWidget(x)
        row.addStretch()
        self.summary = QLabel()
        row.addWidget(self.summary)
        lay.addLayout(row)
        self.notes = QLabel()
        self.notes.setObjectName("Warn")
        lay.addWidget(self.notes)
        self.model = RowsModel(["Supplier GSTIN", "Supplier", "Document", "Type", "IMS action", "Date", "In books",
                                "In GSTR-2B", "Severity", "Observations"],
                               kinds=["text", "text", "text", "text", "text", "date", "text", "text", "text", "text"],
                               colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)
        for sig in (state.clientChanged, state.dataChanged, state.runChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _color(self, row, col):
        if col != 8:
            return None
        return QColor(SEV_COLORS.get(str(self.model.rows[row][8]).lower(), "#FFFFFF"))

    def reload(self) -> None:
        st = self.state
        self.import_btn.setEnabled(st.can("import") and st.client is not None)
        months = fy_months(st.fy)
        if self.period_cb.count() != len(months) or self.period_cb.itemText(0) != months[0]:
            self.period_cb.blockSignals(True)
            self.period_cb.clear()
            self.period_cb.addItems(months)
            run = st.run_context()
            if run is not None and run.run.period_from in months:
                self.period_cb.setCurrentText(run.run.period_from)
            self.period_cb.blockSignals(False)
        if st.client is None:
            self.model.set_rows([])
            return
        rows, notes = st.itc.ims_compare(st.client.id, [self.period_cb.currentText()])
        self.notes.setText(" ".join(notes))
        shown = [r for r in rows if not self.attention.isChecked() or r.worst in ("high", "medium")]
        self.model.set_rows([[r.ims.supplier_gstin, r.ims.supplier_name, r.ims.invoice_no, r.ims.doc_type.label,
                              r.action_label, r.ims.invoice_date, "Yes" if r.books else "No",
                              "Yes" if r.gstr2b else "No", r.worst.upper(),
                              " | ".join(t for _s, t in r.observations)] for r in shown])
        self.table.fit(520)
        high = sum(1 for r in rows if r.worst == "high")
        self.summary.setText(f"{len(rows)} IMS document(s) · <span style='color:{RED}'>{high} need action</span>")

    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "IMS download", "", FILE_FILTER)
        if path:
            self.import_path(path)

    def import_path(self, path):
        period = None if str(path).lower().endswith((".json", ".zip")) else self.period_cb.currentText()
        result = import_interactive(self, self.state, path, Source.IMS, period)
        self.reload()
        return result

