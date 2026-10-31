"""Reconciliation history and the cross-period open-items register."""
from __future__ import annotations

import json
from decimal import Decimal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ...core.models import ReconSettings
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, section, sortable
from ..workers import run_task


class HistoryPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Reconciliation history",
                                  "Every run is kept with its settings and input fingerprint. Open a run to review it, "
                                  "or re-run a period – review work and manual decisions are carried forward."))
        self.model = RowsModel(["Run", "Period", "FY", "Comparison", "Lines", "Fully Matched", "Pending",
                                "Books ITC", "GSTR-2B ITC", "ITC at Risk", "Run at", "By"],
                               kinds=["int", "text", "text", "text", "int", "int", "int", "money", "money", "money",
                                      "text", "text"])
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        lay.addWidget(self.table, 2)
        row = QHBoxLayout()
        open_btn = primary("Open run")
        open_btn.clicked.connect(self.open_selected)
        rerun_btn = QPushButton("Re-run same period")
        rerun_btn.clicked.connect(self.rerun_selected)
        self.delete_btn = QPushButton("Delete reconciliation…")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.setToolTip("Delete the selected run and its review work. Imported files are kept.")
        self.delete_btn.clicked.connect(self.delete_selected)
        row.addWidget(open_btn)
        row.addWidget(rerun_btn)
        row.addStretch()
        row.addWidget(self.delete_btn)
        lay.addLayout(row)
        lay.addWidget(section("Manual match decisions (applied to every later run)"))
        self.dec_model = RowsModel(["Decision", "Books document", "GSTR-2B document", "Remarks", "By", "On", "Run"],
                                   kinds=["text", "int", "int", "text", "text", "text", "int"])
        self.dec_table = Table()
        self.dec_table.setModel(sortable(self.dec_model))
        lay.addWidget(self.dec_table, 1)
        for sig in (state.clientChanged, state.dataChanged, state.runChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()  # loads when first shown

    def reload(self) -> None:
        st = self.state
        self.delete_btn.setEnabled(st.client is not None and st.can("delete_data"))
        if st.client is None:
            self.model.set_rows([])
            self.dec_model.set_rows([])
            return
        rows, payload = [], []
        for r in st.recon.list_runs(st.client.id):
            s = json.loads(r.summary_json or "{}")
            mark = " ◀ current" if r.id == st.run_id else ""
            rows.append([r.id, f"{r.period_from}..{r.period_to}{mark}", r.financial_year,
                         r.comparison.replace("_", " "), s.get("total_lines"), s.get("fully_matched"),
                         s.get("pending_cases"), Decimal(str(s.get("itc_as_per_books", 0))),
                         Decimal(str(s.get("itc_as_per_gstr2b", 0))), Decimal(str(s.get("itc_at_risk", 0))),
                         f"{r.started_at:%d-%m-%Y %H:%M}", r.created_by])
            payload.append(r)
        self.model.set_rows(rows, payload)
        self.table.fit()
        self.dec_model.set_rows([[d.decision, d.books_invoice_id, d.gstr2b_invoice_id, d.remarks, d.user,
                                  f"{d.created_at:%d-%m-%Y}", d.run_id]
                                 for d in st.recon.decisions(st.client.id)])
        self.dec_table.fit()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def open_selected(self) -> None:
        run = self._selected()
        if run is not None:
            self.state.set_run(run.id)
            self.navigate.emit("exceptions")

    def delete_selected(self) -> bool:
        run = self._selected()
        if run is None:
            QMessageBox.information(self, "Delete reconciliation", "Select a reconciliation in the list first.")
            return False
        if QMessageBox.question(
                self, "Delete reconciliation",
                f"Delete reconciliation #{run.id} ({run.period_from}..{run.period_to}, "
                f"{run.comparison.replace('_', ' ')})?\n\nThe statuses, remarks and matches entered on this run are "
                "deleted with it. The imported files, manual match decisions and ITC records are kept, so you can "
                "remove a wrong file on the Imports page and reconcile again.\n\nThe deletion is recorded in the "
                "audit log. It cannot be undone.") != QMessageBox.Yes:
            return False
        try:
            self.state.recon.delete_run(run.client_id, run.id, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Delete reconciliation", str(exc))
            return False
        if self.state.run_id == run.id:
            self.state.set_run(None)
        self.state.notify()
        return True

    def rerun_selected(self) -> None:
        run = self._selected()
        if run is None:
            return
        from ...core.models import Source

        settings = ReconSettings.from_dict(json.loads(run.settings_json))
        compare = Source(run.comparison.split("_VS_")[-1])
        task = run_task(self, f"Re-running {run.period_from}..{run.period_to}", self.state.recon.run,
                        run.client_id, run.period_from, run.period_to, settings, compare_with=compare,
                        user=self.state.user)
        if not task.ok:
            QMessageBox.information(self, "Re-run", task.message)
            return
        self.state.set_run(task.result_value, data_changed=True)


class OpenItemsPage(LazyPage):
    """Unresolved documents across all periods – each document listed once."""

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header(
            "Open items across periods",
            "Documents without a confirmed counterpart, judged by the latest run that contained them – "
            "each listed once. When a later GSTR-2B brings an invoice in (previous-period match) it "
            "closes here automatically. Double-click a row for its history across runs."))
        bar = QHBoxLayout()
        self.source_cb = QComboBox()
        self.source_cb.addItems(["All sources", "BOOKS", "GSTR2B", "GSTR2A"])
        self.unrec = QCheckBox("Include documents not yet reconciled")
        self.unrec.setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.total_lbl = QLabel()
        for w in (self.source_cb, self.unrec, self.search):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.total_lbl)
        lay.addLayout(bar)
        self.model = RowsModel(["Source", "Supplier GSTIN", "Supplier", "Type", "Invoice No", "Invoice Date",
                                "Period", "ITC", "Age (days)", "Last run", "Line", "Last category", "Status",
                                "Remarks", "Runs seen"],
                               kinds=["text", "text", "text", "text", "text", "date", "text", "money", "int", "int",
                                      "int", "text", "text", "text", "int"])
        self.proxy = sortable(self.model)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = Table()
        self.table.setModel(self.proxy)
        self.table.doubleClicked.connect(self._history)
        lay.addWidget(self.table, 1)
        self.source_cb.currentIndexChanged.connect(self.reload)
        self.unrec.toggled.connect(self.reload)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()  # loads when first shown

    def reload(self) -> None:
        st = self.state
        if st.client is None:
            self.model.set_rows([])
            return
        src = self.source_cb.currentText()
        items = [i for i in st.tracking.open_items(st.client.id, self.unrec.isChecked())
                 if src == "All sources" or i.source == src]
        self.model.set_rows([[i.source, i.supplier_gstin, i.supplier_name, i.doc_type, i.invoice_no, i.invoice_date,
                              i.period, i.itc, i.age_days, i.last_run_id, i.last_line_no, i.last_category,
                              i.status, i.remarks, i.runs_seen] for i in items], items)
        self.table.fit(240)
        books_itc = sum((i.itc for i in items if i.source == "BOOKS"), Decimal(0))
        from ..theme import money

        self.total_lbl.setText(f"{len(items)} open document(s) · books ITC {money(books_itc, True)}")

    def _history(self, index) -> None:
        item = self.proxy.index(index.row(), 0).data(OBJECT_ROLE)
        hist = self.state.tracking.document_history(item.invoice_id)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"History – {item.invoice_no}")
        dlg.resize(760, 320)
        lay = QVBoxLayout(dlg)
        t = Table()
        t.setModel(sortable(RowsModel(["Run", "Period", "Line", "Category", "Status", "Remarks", "Run at"],
                                      [[h["run_id"], h["period"], h["line_no"], h["category"], h["status"],
                                        h["remarks"], f"{h['run_at']:%d-%m-%Y %H:%M}"] for h in hist],
                                      ["int", "text", "int", "text", "text", "text", "text"])))
        t.fit()
        lay.addWidget(t)
        dlg.exec()
