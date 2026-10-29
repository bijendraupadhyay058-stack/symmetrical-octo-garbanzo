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
from PySide6.QtCore import Qt

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
        for x in (QLabel("GSTR-2B up to"), self.cutoff_cb, QLabel("Portal 8A"), self.portal_8a, self.annual_btn,
                  self.export_annual_btn):
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
        notes = []
        if t.portal_8a is not None:
            notes.append(f"Computed 8A differs from the portal figure by {money(t.a.total - t.portal_8a, True)}.")
        if t.b_periods_missing:
            notes.append(f"GSTR-3B not imported for {len(t.b_periods_missing)} month(s) – 8B incomplete.")
        notes.append(f"{len(t.docs_8a_not_in_books)} GSTR-2B document(s) of the year are not in books; "
                     f"{len(t.books_not_in_8a)} books document(s) are not in 8A.")
        self.t8_note.setText(" ".join(notes))
        self.month_model.set_rows([[m.month, m.books_itc, m.gstr2b_itc, m.filed_4a5, m.filed_4b, m.filed_4c,
                                    m.claimed_register] for m in t.months])

    # ------------------------------------------------------------- actions
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

