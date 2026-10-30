"""Phase 4 pages: outward supplies (sales register vs GSTR-1 vs GSTR-3B), compliance
dashboard, supplier letters and working papers, client-authorised sync and the web interface."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ...compliance.summary import RAG_LABEL
from ...core.models import Source
from ...itc.annual import fy_months
from ...services.common import ServiceError
from ..import_flow import import_interactive
from ..state import AppState
from ..theme import AMBER, NAVY, RED, TEAL, money
from ..widgets import (
    OBJECT_ROLE, KpiCard, LazyPage, RowsModel, Table, page_header, primary, section, sortable,
)
from ..workers import run_task
from .workflow import FILE_FILTER

RAG_COLORS = {"red": "#FFCDD2", "amber": "#FFF3C4", "green": "#C8E6C9", "grey": "#ECEFF1"}
SEV_COLORS = {"high": "#FFCDD2", "medium": "#FFF3C4", "info": "#E3F2FD"}
LABEL_RAG = {v: k for k, v in RAG_LABEL.items()}
COMPARE = {"GSTR-1": Source.GSTR1, "e-Invoice (IRP)": Source.EINV, "e-Way bill": Source.EWB}


def _selected(table: Table):
    rows = table.selectionModel().selectedRows() if table.selectionModel() else []
    return table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None


def _page(widget: QWidget, title: str, subtitle: str) -> QVBoxLayout:
    widget.setObjectName("Page")
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(22, 18, 22, 12)
    lay.addWidget(page_header(title, subtitle))
    return lay


def _rag_color(model_getter, col: int):
    def color(row, c):
        if c != col:
            return None
        rag = LABEL_RAG.get(model_getter().rows[row][col])
        return QColor(RAG_COLORS[rag]) if rag else None
    return color


# ===================================================================== outward
class OutwardPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        lay = _page(self, "Sales & GSTR-1", "Sales register vs GSTR-1, e-invoices (IRP) or e-way bills (same "
                                            "matching engine), and GSTR-1 / sales register vs GSTR-3B Table 3.1 "
                                            "output tax liability.")
        top = QHBoxLayout()
        self.sales_btn = primary("Import sales register…")
        self.sales_btn.clicked.connect(lambda: self.import_dialog(Source.SALES))
        self.g1_btn = primary("Import GSTR-1…")
        self.g1_btn.clicked.connect(lambda: self.import_dialog(Source.GSTR1))
        b3 = QPushButton("Import GSTR-3B…")
        b3.clicked.connect(lambda: self.navigate.emit("returns"))
        self.from_cb, self.to_cb = QComboBox(), QComboBox()
        self.compare_cb = QComboBox()
        self.compare_cb.addItems(list(COMPARE))
        self.compare_cb.setToolTip("Compare the sales register with GSTR-1, the e-invoices reported to the IRP or "
                                   "the e-way bills generated")
        self.run_btn = primary("Reconcile")
        self.run_btn.clicked.connect(self.reconcile)
        self.open_btn = QPushButton("Open exceptions")
        self.open_btn.clicked.connect(self.open_exceptions)
        self.einv_btn = QPushButton("Import e-invoice report…")
        self.einv_btn.setToolTip("IRN-wise report downloaded from the e-invoice portal (Excel or CSV)")
        self.einv_btn.clicked.connect(lambda: self.import_dialog(Source.EINV))
        self.ewb_btn = QPushButton("Import e-way bill report…")
        self.ewb_btn.setToolTip("Report of e-way bills generated, downloaded from the e-way bill portal")
        self.ewb_btn.clicked.connect(lambda: self.import_dialog(Source.EWB))
        self.tally_btn = QPushButton("Sales from Tally…")
        self.tally_btn.setToolTip("Fetch the sales vouchers straight from TallyPrime (XML interface, port 9000)")
        self.tally_btn.clicked.connect(self.tally_dialog)
        for w in (self.sales_btn, self.tally_btn, self.g1_btn, self.einv_btn, self.ewb_btn, b3):
            top.addWidget(w)
        top.addStretch()
        lay.addLayout(top)
        run_row = QHBoxLayout()
        for w in (QLabel("From"), self.from_cb, QLabel("To"), self.to_cb, QLabel("Sales register vs"),
                  self.compare_cb, self.run_btn, self.open_btn):
            run_row.addWidget(w)
        run_row.addStretch()
        lay.addLayout(run_row)
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("Muted")
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)
        grid = QGridLayout()
        self.cards = {k: KpiCard(t, c) for k, t, c in (
            ("g1", "Output tax in GSTR-1 (3.1 a+b)", NAVY), ("sales", "Output tax in sales register", TEAL),
            ("filed", "Output tax in GSTR-3B (3.1 a+b)", NAVY), ("gap", "GSTR-1 − GSTR-3B", RED))}
        for i, c in enumerate(self.cards.values()):
            grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        split = QSplitter(Qt.Vertical)
        self.rows_model = RowsModel(["Period", "GSTR-3B Table 3.1", "GSTR-1 taxable", "GSTR-1 tax", "Sales taxable",
                                     "Sales tax", "3B taxable", "3B tax", "3B − GSTR-1", "Sales − GSTR-1"],
                                    kinds=["text", "text"] + ["money"] * 8)
        self.rows_tbl = Table()
        self.rows_tbl.setModel(self.rows_model)
        self.rows_tbl.setSortingEnabled(False)
        split.addWidget(self.rows_tbl)
        self.seg_model = RowsModel(["Period", "Segment", "Sales taxable", "Sales tax", "GSTR-1 taxable", "GSTR-1 tax",
                                    "Difference"], kinds=["text", "text"] + ["money"] * 5)
        self.seg_tbl = Table()
        self.seg_tbl.setModel(self.seg_model)
        self.seg_tbl.setSortingEnabled(False)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Segments – sales register vs GSTR-1"))
        bl.addWidget(self.seg_tbl)
        split.addWidget(box)
        self.find_model = RowsModel(["Period", "Type", "Severity", "Finding", "Amount"],
                                    kinds=["text", "text", "text", "text", "money"], colors=self._find_color)
        self.find_tbl = Table()
        self.find_tbl.setModel(sortable(self.find_model))
        box2 = QWidget()
        b2 = QVBoxLayout(box2)
        b2.setContentsMargins(0, 0, 0, 0)
        b2.addWidget(section("Classified differences"))
        b2.addWidget(self.find_tbl)
        split.addWidget(box2)
        lay.addWidget(split, 1)
        self.from_cb.currentIndexChanged.connect(self._from_changed)
        self.compare_cb.currentIndexChanged.connect(lambda _i: self.reload())
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _find_color(self, row, col):
        if col != 2:
            return None
        return QColor(SEV_COLORS.get(self.find_model.rows[row][2].lower(), "#FFFFFF"))

    def _from_changed(self, _i=None) -> None:
        if self.from_cb.currentText() and self.to_cb.currentText() < self.from_cb.currentText():
            self.to_cb.setCurrentText(self.from_cb.currentText())

    def periods(self) -> list[str]:
        p_from, p_to = self.from_cb.currentText(), self.to_cb.currentText() or self.from_cb.currentText()
        return [m for m in fy_months(self.state.fy) if p_from <= m <= p_to]

    def reload(self) -> None:
        st = self.state
        months = fy_months(st.fy)
        if [self.from_cb.itemText(i) for i in range(self.from_cb.count())] != months:
            for cb in (self.from_cb, self.to_cb):
                cb.blockSignals(True)
                cb.clear()
                cb.addItems(months)
                cb.blockSignals(False)
        enabled = st.client is not None
        for b in (self.sales_btn, self.tally_btn, self.g1_btn, self.einv_btn, self.ewb_btn):
            b.setEnabled(enabled and st.can("import"))
        self.run_btn.setEnabled(enabled and st.can("reconcile"))
        if st.client is None:
            for m in (self.rows_model, self.seg_model, self.find_model):
                m.set_rows([])
            self.status_lbl.setText("Select a client.")
            return
        periods = self.periods()
        scope = st.tracking.scope(st.client.id, periods[0], periods[-1]) if periods else {}
        comparison = f"SALES_VS_{COMPARE[self.compare_cb.currentText()].value}"
        runs = [r for r in st.recon.list_runs(st.client.id) if r.comparison == comparison
                and r.period_from == periods[0] and r.period_to == periods[-1]] if periods else []
        self.latest_run = runs[0].id if runs else None
        self.open_btn.setEnabled(self.latest_run is not None)
        self.status_lbl.setText(
            f"{scope.get('sales', 0)} sales register document(s), {scope.get('gstr1', 0)} GSTR-1 B2B/CDNR "
            f"document(s), {scope.get('einv', 0)} e-invoice(s) and {scope.get('ewb', 0)} e-way bill(s) in "
            f"{periods[0]}..{periods[-1]}. "
            + (f"Latest sales vs {self.compare_cb.currentText()} reconciliation: run #{self.latest_run}."
               if self.latest_run else
               "Not yet reconciled.") + {
                "SALES_VS_GSTR1": " B2C, exports and nil/exempt supplies are compared as section totals.",
                "SALES_VS_EINV": " B2C, nil/exempt and non-GST supplies are not e-invoiced and are left out.",
                "SALES_VS_EWB": " Documents below the e-way bill threshold (setting ewb_threshold), credit notes "
                                "and services need no e-way bill: marked No Action with the reason.",
            }[comparison]
            if periods else "")
        from ...services.outward import OutwardService

        workings = OutwardService(st.db).liability(st.client.id, periods) if periods else []
        rows, segs, finds = [], [], []
        tot = {"g1": 0, "sales": 0, "filed": 0, "has_filed": False}
        for w in workings:
            for r in w.rows:
                f = r.filed
                rows.append([w.period, r.label, r.gstr1.taxable, r.gstr1.total, r.sales.taxable, r.sales.total,
                             f.taxable if f else None, f.total if f else None, r.diff_filed_gstr1,
                             r.diff_sales_gstr1])
                if r.code in ("31A", "31B"):
                    tot["g1"] += r.gstr1.total
                    tot["sales"] += r.sales.total
                    if f is not None:
                        tot["filed"] += f.total
                        tot["has_filed"] = True
            segs += [[w.period, s.segment, s.sales.taxable, s.sales.total, s.gstr1.taxable, s.gstr1.total, s.diff]
                     for s in w.segments]
            finds += [[w.period, f.kind.title(), f.severity.upper(), f.text, f.amount] for f in w.findings]
        self.rows_model.set_rows(rows)
        self.seg_model.set_rows(segs)
        self.find_model.set_rows(finds)
        for t in (self.rows_tbl, self.seg_tbl, self.find_tbl):
            t.fit(420)
        self.cards["g1"].set(money(tot["g1"]))
        self.cards["sales"].set(money(tot["sales"]))
        self.cards["filed"].set(money(tot["filed"]) if tot["has_filed"] else "–",
                                "" if tot["has_filed"] else "GSTR-3B not imported")
        self.cards["gap"].set(money(tot["g1"] - tot["filed"]) if tot["has_filed"] else "–",
                              "positive = possible short payment" if tot["has_filed"] else "")

    def import_dialog(self, source: Source) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Select {source.value} file", "", FILE_FILTER)
        if path:
            period = None if Path(path).suffix.lower() in (".json", ".zip") \
                or source in (Source.SALES, Source.EINV, Source.EWB) else self.from_cb.currentText()
            import_interactive(self, self.state, path, source, period)
            self.reload()

    def tally_dialog(self) -> None:
        from ..tally_import import tally_import

        periods = self.periods()
        if periods and tally_import(self, self.state, Source.SALES, periods[0], periods[-1]):
            self.reload()

    def reconcile(self) -> None:
        st = self.state
        periods = self.periods()
        if st.client is None or not periods:
            return
        label = self.compare_cb.currentText()
        task = run_task(self, f"Reconciling sales register vs {label}", st.recon.run, st.client.id, periods[0],
                        periods[-1], st.recon_settings(), compare_with=COMPARE[label], user=st.user)
        if not task.ok:
            QMessageBox.information(self, "Reconciliation", task.message)
            return
        st.set_run(task.result_value)
        st.notify()

    def open_exceptions(self) -> None:
        if self.latest_run:
            self.state.set_run(self.latest_run)
            self.navigate.emit("exceptions")


# ================================================================== compliance
class CompliancePage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.summaries = []
        lay = _page(self, "Compliance dashboard", "Annual GST reconciliation status of every client, month by "
                                                  "month – derived from imported data only (no portal access).")
        top = QHBoxLayout()
        self.refresh_btn = primary("Refresh")
        self.refresh_btn.clicked.connect(self.reload)
        self.xlsx_btn = QPushButton("Export dashboard (Excel)…")
        self.xlsx_btn.clicked.connect(self.export_excel)
        self.pdf_btn = QPushButton("Client compliance PDF…")
        self.pdf_btn.clicked.connect(self.export_pdf)
        self.fy_lbl = QLabel()
        for w in (self.fy_lbl, self.refresh_btn, self.xlsx_btn, self.pdf_btn):
            top.addWidget(w)
        top.addStretch()
        lay.addLayout(top)
        grid = QGridLayout()
        self.cards = {k: KpiCard(t, c) for k, t, c in (
            ("red", "Clients – action required", RED), ("amber", "Clients – attention", AMBER),
            ("green", "Clients – reconciled", TEAL), ("pending", "Exceptions pending", NAVY))}
        for i, c in enumerate(self.cards.values()):
            grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        split = QSplitter(Qt.Vertical)
        self.c_model = RowsModel(["Client", "GSTIN", "Status", "Months with data", "Months clear", "Pending",
                                  "ITC at risk", "3B ITC above 2B", "Possible short payment", "Follow-ups due"],
                                 kinds=["text", "text", "text", "int", "int", "int", "money", "money", "money", "int"],
                                 colors=_rag_color(lambda: self.c_model, 2))
        self.c_tbl = Table()
        self.c_tbl.setModel(sortable(self.c_model))
        self.c_tbl.selectionModel().selectionChanged.connect(lambda *_: self.show_months())
        self.c_tbl.doubleClicked.connect(lambda _i: self.open_client())
        split.addWidget(self.c_tbl)
        self.m_model = RowsModel(["Month", "Status", "Issues", "Purchase docs", "2B docs", "Sales docs",
                                  "GSTR-1 docs", "3B imported", "ITC 2B", "ITC 3B", "Output GSTR-1", "Output 3B",
                                  "Pending"],
                                 kinds=["text", "text", "text", "int", "int", "int", "int", "text", "money", "money",
                                        "money", "money", "int"], colors=_rag_color(lambda: self.m_model, 1))
        self.m_tbl = Table()
        self.m_tbl.setModel(self.m_model)
        self.m_tbl.setSortingEnabled(False)
        self.m_tbl.setWordWrap(True)
        self.m_tbl.horizontalHeader().setStretchLastSection(False)
        split.addWidget(self.m_tbl)
        split.setSizes([160, 520])
        tabs = QTabWidget()
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 6, 0, 0)
        bl.addWidget(split, 1)
        hint = QLabel("Double-click a client to make it the current client.")
        hint.setObjectName("Muted")
        bl.addWidget(hint)
        tabs.addTab(box, "Clients")
        tabs.addTab(self._calendar_tab(), "Returns calendar")
        lay.addWidget(tabs, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _calendar_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        self.days = QSpinBox()
        self.days.setRange(7, 120)
        self.days.setValue(30)
        self.days.setSuffix(" days ahead")
        self.days.valueChanged.connect(lambda _v: self.show_calendar())
        row.addWidget(QLabel("Returns due (with up to 60 days overdue) –"))
        row.addWidget(self.days)
        row.addStretch()
        lay.addLayout(row)
        self.u_model = RowsModel(["Due", "Return", "Period", "Client", "GSTIN", "Data", "Basis"],
                                 kinds=["text", "text", "text", "text", "text", "text", "text"],
                                 colors=self._due_color)
        self.u_tbl = Table()
        self.u_tbl.setModel(self.u_model)
        self.u_tbl.setSortingEnabled(False)
        lay.addWidget(self.u_tbl, 2)
        lay.addWidget(section("Due-date extensions (recorded from CBIC notifications)"))
        form = QHBoxLayout()
        self.x_type = QComboBox()
        from ...compliance.calendar import RETURN_TYPES

        self.x_type.addItems(list(RETURN_TYPES))
        self.x_period = QLineEdit()
        self.x_period.setPlaceholderText("YYYY-MM or 2025-26")
        self.x_due = QDateEdit(QDate.currentDate())
        self.x_due.setCalendarPopup(True)
        self.x_due.setDisplayFormat("dd-MM-yyyy")
        self.x_ref = QLineEdit()
        self.x_ref.setPlaceholderText("Notification / circular")
        self.x_states = QLineEdit()
        self.x_states.setPlaceholderText("State codes, e.g. 27,29 (blank = all)")
        self.x_add = primary("Record extension")
        self.x_add.clicked.connect(self.add_extension)
        self.x_del = QPushButton("Delete selected")
        self.x_del.clicked.connect(self.delete_extension)
        for x in (self.x_type, self.x_period, self.x_due, self.x_ref, self.x_states, self.x_add, self.x_del):
            form.addWidget(x)
        lay.addLayout(form)
        self.x_model = RowsModel(["#", "Return", "Period", "Due", "Reference", "States", "Recorded by"],
                                 kinds=["int", "text", "text", "text", "text", "text", "text"])
        self.x_tbl = Table()
        self.x_tbl.setModel(self.x_model)
        lay.addWidget(self.x_tbl, 1)
        return w

    def _due_color(self, row, col):
        if col != 5:
            return None
        u = self.u_model.payload[row] if self.u_model.payload else None
        if u is None:
            return None
        if u.overdue:
            return QColor(RAG_COLORS["red"])
        return QColor(RAG_COLORS["green"] if u.status == "imported" else RAG_COLORS["grey"])

    def show_calendar(self) -> None:
        from ...services.calendar import CalendarService

        cal = CalendarService(self.state.db)
        ups = cal.upcoming(days=self.days.value())
        self.u_model.set_rows([[f"{u.item.due:%d-%m-%Y}", u.item.return_type + (" (optional)" if u.item.optional
                                                                                 else ""),
                                u.item.period, u.client, u.gstin,
                                "OVERDUE – not imported" if u.overdue else u.status,
                                u.item.basis] for u in ups], ups)
        self.u_tbl.fit(320)
        rows = cal.override_rows()
        self.x_model.set_rows([[o.id, o.return_type, o.period, f"{o.due_date:%d-%m-%Y}", o.reference,
                                o.state_codes or "all", o.recorded_by] for o in rows], rows)
        self.x_tbl.fit(320)
        for b in (self.x_add, self.x_del):
            b.setEnabled(self.state.can("settings"))

    def add_extension(self) -> None:
        from ...services.calendar import CalendarService

        try:
            CalendarService(self.state.db).add_override(
                self.x_type.currentText(), self.x_period.text().strip(), self.x_due.date().toPython(),
                self.x_ref.text(), self.state.session, self.x_states.text().split(","))
        except ServiceError as exc:
            QMessageBox.warning(self, "Extension", str(exc))
            return
        self.x_period.clear()
        self.x_ref.clear()
        self.x_states.clear()
        self.reload()

    def delete_extension(self) -> None:
        from ...services.calendar import CalendarService

        o = _selected(self.x_tbl)
        if o is not None:
            CalendarService(self.state.db).delete_override(o.id, self.state.session)
            self.reload()

    def reload(self) -> None:
        from ...services.compliance import ComplianceService

        st = self.state
        self.fy_lbl.setText(f"<b>FY {st.fy}</b>")
        self.summaries = ComplianceService(st.db).annual_dashboard(st.fy)
        rows = [[c.name, c.gstin, RAG_LABEL[c.rag], c.months_with_data, c.months_reconciled, c.pending,
                 c.total("itc_at_risk"), c.total("itc_excess"), c.total("short_payment"), c.followups_due]
                for c in self.summaries]
        self.c_model.set_rows(rows, self.summaries)
        self.c_tbl.fit(320)
        for k in ("red", "amber", "green"):
            self.cards[k].set(str(sum(1 for c in self.summaries if c.rag == k)))
        self.cards["pending"].set(str(sum(c.pending for c in self.summaries)))
        current = next((i for i, c in enumerate(self.summaries) if st.client and c.client_id == st.client.id), None)
        if current is not None:
            src = self.c_tbl.model().mapFromSource(self.c_model.index(current, 0))
            self.c_tbl.selectRow(src.row())
        self.show_months()
        self.show_calendar()

    def _current(self):
        return _selected(self.c_tbl)

    def show_months(self) -> None:
        c = self._current()
        self.m_model.set_rows([] if c is None else [
            [m.period, RAG_LABEL[m.rag], "\n".join(t for _r, t in m.issues), m.purchase_docs, m.gstr2b_docs,
             m.sales_docs, m.gstr1_docs, "Yes" if m.gstr3b_imported else "No", m.itc_2b if m.inward else None,
             m.itc_3b, m.output_gstr1, m.output_3b, m.pending] for m in c.months])
        self.m_tbl.fit(200)
        self.m_tbl.setColumnWidth(2, 460)
        self.m_tbl.resizeRowsToContents()
        self.pdf_btn.setEnabled(c is not None and self.state.can("export"))

    def open_client(self) -> None:
        c = self._current()
        if c is not None:
            self.state.set_client(self.state.clients.get(c.client_id))
            self.navigate.emit("dashboard")

    def export_excel(self) -> None:
        from ...reports.compliance_report import export_compliance_excel

        path, _ = QFileDialog.getSaveFileName(self, "Save dashboard", f"GST_Dashboard_{self.state.fy}.xlsx",
                                              "Excel (*.xlsx)")
        if path:
            export_compliance_excel(self.summaries, self.state.fy, path)
            QMessageBox.information(self, "Dashboard", f"Saved {path}")

    def export_pdf(self) -> None:
        from ...reports.compliance_report import export_client_pdf

        c = self._current()
        if c is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save compliance summary", f"Compliance_{c.gstin}_{c.fy}.pdf",
                                              "PDF (*.pdf)")
        if path:
            export_client_pdf(c, path)
            QMessageBox.information(self, "Compliance summary", f"Saved {path}")


# ====================================================== letters & working papers
class LettersPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        lay = _page(self, "Letters & working papers", "Supplier discrepancy letters from the current purchase "
                                                      "reconciliation, and period-wise audit working papers.")
        self.run_lbl = QLabel()
        self.run_lbl.setObjectName("Muted")
        lay.addWidget(self.run_lbl)
        lay.addWidget(section("Supplier discrepancy letters"))
        row = QHBoxLayout()
        self.reply = QSpinBox()
        self.reply.setRange(3, 90)
        self.reply.setValue(15)
        self.reply.setSuffix(" days to reply")
        self.signatory = QLineEdit()
        self.signatory.setPlaceholderText("Signatory name (optional)")
        self.fmt_docx, self.fmt_pdf, self.fmt_eml = (QCheckBox("Word"), QCheckBox("PDF"),
                                                     QCheckBox("E-mail draft (.eml)"))
        for b in (self.fmt_docx, self.fmt_pdf, self.fmt_eml):
            b.setChecked(True)
        self.gen_btn = primary("Generate letters…")
        self.gen_btn.clicked.connect(self.generate)
        for w in (self.reply, self.signatory, self.fmt_docx, self.fmt_pdf, self.fmt_eml, self.gen_btn):
            row.addWidget(w)
        row.addStretch()
        lay.addLayout(row)
        split = QSplitter(Qt.Vertical)
        self.l_model = RowsModel(["Supplier GSTIN", "Supplier", "Items", "Tax not in GSTR-2B", "Issues"],
                                 kinds=["text", "text", "int", "money", "text"])
        self.l_tbl = Table()
        self.l_tbl.setModel(sortable(self.l_model))
        split.addWidget(self.l_tbl)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Audit working papers"))
        r2 = QHBoxLayout()
        self.prep_btn = primary("Prepare working papers…")
        self.prep_btn.clicked.connect(self.prepare)
        self.src_cb = QCheckBox("Include imported source files")
        self.review_btn = QPushButton("Review && sign off…")
        self.review_btn.clicked.connect(self.review)
        self.verify_btn = QPushButton("Verify integrity")
        self.verify_btn.clicked.connect(self.verify)
        for w in (self.prep_btn, self.src_cb, self.review_btn, self.verify_btn):
            r2.addWidget(w)
        r2.addStretch()
        bl.addLayout(r2)
        self.w_model = RowsModel(["#", "Run", "Period", "Prepared by", "Prepared on", "Reviewed by", "Reviewed on",
                                  "Review notes", "Package"],
                                 kinds=["int", "int", "text", "text", "text", "text", "text", "text", "text"])
        self.w_tbl = Table()
        self.w_tbl.setModel(sortable(self.w_model))
        bl.addWidget(self.w_tbl)
        split.addWidget(box)
        lay.addWidget(split, 1)
        for sig in (state.clientChanged, state.runChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _inward_run(self):
        ctx = self.state.run_context()
        return ctx if ctx is not None and ctx.run.comparison.startswith("BOOKS") else None

    def reload(self) -> None:
        from ...services.letters import LetterService
        from ...services.papers import WorkingPaperService

        st = self.state
        ctx = self._inward_run()
        if ctx is None:
            self.run_lbl.setText("Open a purchase (books vs GSTR-2B/2A) reconciliation run to prepare letters and "
                                 "working papers.")
            self.l_model.set_rows([])
        else:
            self.run_lbl.setText(f"Run #{ctx.run.id} · {ctx.run.period_from}..{ctx.run.period_to} · "
                                 f"{ctx.client.name}")
            letters = LetterService(st.db).preview(ctx.run.id)
            self.l_model.set_rows([[lt.gstin, lt.name, len(lt.items), lt.amount,
                                    "; ".join(sorted({i.issue for i in lt.items}))] for lt in letters], letters)
            self.l_tbl.fit(380)
        self.gen_btn.setEnabled(ctx is not None and st.can("letters"))
        self.prep_btn.setEnabled(ctx is not None and st.can("prepare_papers"))
        self.review_btn.setEnabled(st.can("review_papers"))
        papers = WorkingPaperService(st.db).list(st.client.id) if st.client else []
        self.w_model.set_rows([[w.id, w.run_id, f"{w.period_from}..{w.period_to}", w.prepared_by,
                                f"{w.prepared_at:%d-%m-%Y %H:%M}", w.reviewed_by,
                                f"{w.reviewed_at:%d-%m-%Y %H:%M}" if w.reviewed_at else "", w.review_notes,
                                w.package_path] for w in papers], papers)
        self.w_tbl.fit(360)

    def generate(self) -> None:
        from ...services.letters import LetterService

        ctx = self._inward_run()
        formats = tuple(f for f, b in (("docx", self.fmt_docx), ("pdf", self.fmt_pdf), ("eml", self.fmt_eml))
                        if b.isChecked())
        if ctx is None or not formats:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the letters")
        if not folder:
            return
        task = run_task(self, "Writing letters", LetterService(self.state.db).generate, ctx.run.id, folder,
                        None, formats, self.reply.value(), self.signatory.text().strip(), user=self.state.user,
                        cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "Letters", task.message)
            return
        QMessageBox.information(self, "Letters", f"{len(task.result_value)} letter(s) written to {folder}.\n"
                                                 "E-mail drafts are not sent – open them in your mail program.")
        self.state.notify(keep_cache=True)

    def prepare(self) -> None:
        from ...services.papers import WorkingPaperService

        ctx = self._inward_run()
        if ctx is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the working papers")
        if not folder:
            return
        task = run_task(self, "Preparing working papers", WorkingPaperService(self.state.db).prepare, ctx.run.id,
                        folder, self.state.session, include_sources=self.src_cb.isChecked(), cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "Working papers", task.message)
            return
        QMessageBox.information(self, "Working papers", f"Saved {task.result_value.package_path}")
        self.reload()

    def review(self) -> None:
        from ...services.papers import WorkingPaperService

        wp = _selected(self.w_tbl)
        if wp is None:
            return
        notes, ok = QInputDialog.getMultiLineText(self, "Review working papers", f"Review notes for #{wp.id}:")
        if not ok:
            return
        try:
            WorkingPaperService(self.state.db).review(wp.id, self.state.session, notes)
        except ServiceError as exc:
            QMessageBox.warning(self, "Review", str(exc))
            return
        self.reload()

    def verify(self) -> None:
        from ...services.papers import WorkingPaperService

        wp = _selected(self.w_tbl)
        if wp is None:
            return
        ok, problem = WorkingPaperService(self.state.db).verify(wp.id)
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "Integrity", "The package matches its recorded SHA-256 and manifest." if ok else problem)


# ================================================================ sync & web
class SyncPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.server = None
        lay = _page(self, "Sync & web access", "Encrypted, client-authorised sync packages for a cloud folder, and "
                                               "a read-only web view for phones on the office network.")
        lay.addWidget(section("Client authorisation"))
        row = QHBoxLayout()
        self.granted_by = QLineEdit()
        self.granted_by.setPlaceholderText("Client's authorised signatory")
        self.evidence = QLineEdit()
        self.evidence.setPlaceholderText("Reference of the signed consent")
        self.until = QDateEdit(QDate.currentDate().addYears(1))
        self.until.setCalendarPopup(True)
        self.until.setDisplayFormat("dd-MM-yyyy")
        self.auth_btn = primary("Record authorisation")
        self.auth_btn.clicked.connect(self.authorise)
        self.revoke_btn = QPushButton("Revoke selected")
        self.revoke_btn.clicked.connect(self.revoke)
        for w in (self.granted_by, self.evidence, QLabel("Valid until"), self.until, self.auth_btn, self.revoke_btn):
            row.addWidget(w)
        lay.addLayout(row)
        self.a_model = RowsModel(["#", "Status", "Granted by", "From", "Until", "Consent reference", "Recorded by"],
                                 kinds=["int", "text", "text", "text", "text", "text", "text"])
        self.a_tbl = Table()
        self.a_tbl.setModel(sortable(self.a_model))
        self.a_tbl.setMaximumHeight(160)
        lay.addWidget(self.a_tbl)
        lay.addWidget(section("Encrypted sync packages"))
        r2 = QHBoxLayout()
        self.export_btn = primary("Export package…")
        self.export_btn.clicked.connect(self.export)
        self.import_btn = QPushButton("Import package…")
        self.import_btn.clicked.connect(self.import_package)
        self.sync_lbl = QLabel()
        self.sync_lbl.setObjectName("Muted")
        self.sync_lbl.setWordWrap(True)
        for w in (self.export_btn, self.import_btn):
            r2.addWidget(w)
        r2.addWidget(self.sync_lbl, 1)
        lay.addLayout(r2)
        lay.addWidget(section("Web interface (read-only)"))
        r3 = QHBoxLayout()
        self.host = QComboBox()
        self.host.addItems(["127.0.0.1 (this computer only)", "0.0.0.0 (office network)"])
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(8765)
        self.cert = QLineEdit()
        self.cert.setPlaceholderText("TLS certificate (.pem) – required for the network")
        self.key = QLineEdit()
        self.key.setPlaceholderText("TLS key (.pem)")
        self.web_btn = primary("Start web server")
        self.web_btn.clicked.connect(self.toggle_web)
        for w in (self.host, QLabel("Port"), self.port, self.cert, self.key, self.web_btn):
            r3.addWidget(w)
        lay.addLayout(r3)
        self.uploads_cb = QCheckBox("Allow file uploads from the web view (users with the import permission; each "
                                    "upload is previewed and saved only on confirmation)")
        self.uploads_cb.toggled.connect(self.toggle_uploads)
        lay.addWidget(self.uploads_cb)
        self.web_lbl = QLabel("Stopped.")
        self.web_lbl.setObjectName("Muted")
        self.web_lbl.setWordWrap(True)
        self.web_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.web_lbl)
        lay.addStretch()
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    @property
    def svc(self):
        from ...services.sync import SyncService

        return SyncService(self.state.db)

    def toggle_uploads(self, on: bool) -> None:
        try:
            self.state.security.set_setting("web_uploads", bool(on), self.state.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "Web", str(exc))

    def reload(self) -> None:
        st = self.state
        self.uploads_cb.blockSignals(True)
        self.uploads_cb.setChecked(bool(st.security.setting("web_uploads")))
        self.uploads_cb.setEnabled(st.can("settings"))
        self.uploads_cb.blockSignals(False)
        can = st.can("sync")
        for b in (self.auth_btn, self.revoke_btn, self.export_btn, self.import_btn):
            b.setEnabled(can and (b is self.import_btn or st.client is not None))
        if st.client is None:
            self.a_model.set_rows([])
            self.sync_lbl.setText("Select a client to export; any package can be imported.")
            return
        today = date.today()
        auths = self.svc.authorisations(st.client.id)
        self.a_model.set_rows([[a.id, "Revoked" if a.revoked_at else ("Active" if a.granted_on <= today <=
                                                                          a.expires_on else "Expired"),
                                a.granted_by, f"{a.granted_on:%d-%m-%Y}", f"{a.expires_on:%d-%m-%Y}", a.evidence,
                                a.recorded_by] for a in auths], auths)
        self.a_tbl.fit(300)
        active = self.svc.active_authorisation(st.client.id)
        self.sync_lbl.setText(
            (f"Authorised by {active.granted_by} until {active.expires_on:%d-%m-%Y}. " if active else
             "No active authorisation – packages cannot be exported for this client. ")
            + f"{self.svc.local_changes(st.client.gstin)} local change(s) since the last sync.")

    def authorise(self) -> None:
        st = self.state
        try:
            self.svc.authorise(st.client.id, self.granted_by.text(), self.until.date().toPython(),
                               self.evidence.text(), st.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "Authorisation", str(exc))
            return
        self.granted_by.clear()
        self.evidence.clear()
        self.reload()

    def revoke(self) -> None:
        a = _selected(self.a_tbl)
        if a is not None:
            self.svc.revoke(a.id, self.state.session)
            self.reload()

    def _password(self, confirm: bool) -> str | None:
        from PySide6.QtWidgets import QLineEdit as LE

        pw, ok = QInputDialog.getText(self, "Sync password", "Package password (min. 10 characters):", LE.Password)
        if not ok:
            return None
        if confirm:
            again, ok = QInputDialog.getText(self, "Sync password", "Repeat the password:", LE.Password)
            if not ok or again != pw:
                QMessageBox.warning(self, "Sync", "The passwords do not match.")
                return None
        return pw

    def export(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Sync folder (e.g. inside your cloud drive)")
        pw = self._password(True) if folder else None
        if not pw:
            return
        task = run_task(self, "Writing encrypted package", self.svc.export_package, self.state.client.id, folder, pw,
                        self.state.session, cancellable=False)
        if task.ok:
            QMessageBox.information(self, "Sync", f"Saved {task.result_value}")
        else:
            QMessageBox.warning(self, "Sync", task.message)
        self.reload()

    def import_package(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Sync package", "", "FIN TAX PRO sync (*.ftpsync)")
        pw = self._password(False) if path else None
        if not pw:
            return
        try:
            info = self.svc.inspect(path, pw)
        except ServiceError as exc:
            QMessageBox.warning(self, "Sync", str(exc))
            return
        replace = False
        text = (f"{info['client']['name']} ({info['client']['gstin']})\nPackage {info['seq']} created "
                f"{info['created_at']} by {info['created_by']}\nAuthorised by {info['authorisation']['granted_by']} "
                f"until {info['authorisation']['expires_on']}\n\nThe client's data on this computer will be replaced "
                "by the package.")
        if info["local_changes"]:
            text += (f"\n\n{info['local_changes']} change(s) were made here since the last sync and will be "
                     "replaced (a backup is taken first).")
            replace = True
        if QMessageBox.question(self, "Import sync package", text + "\n\nContinue?") != QMessageBox.Yes:
            return
        task = run_task(self, "Importing package", self.svc.import_package, path, pw, self.state.session,
                        replace_local=replace, cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "Sync", task.message)
            return
        self.state.notify()
        QMessageBox.information(self, "Sync", "Package imported.")

    def toggle_web(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            self.server = None
            self.web_btn.setText("Start web server")
            self.web_lbl.setText("Stopped.")
            return
        import threading

        try:
            import uvicorn

            from ...services.auth import AuthService
            from ...web.app import LOCAL_HOSTS, create_app
        except ImportError:
            QMessageBox.warning(self, "Web", "The web components (fastapi, uvicorn) are not installed.")
            return
        host = self.host.currentText().split()[0]
        cert, key = self.cert.text().strip() or None, self.key.text().strip() or None
        if host not in LOCAL_HOSTS:
            if not AuthService(self.state.db).has_users():
                QMessageBox.warning(self, "Web", "Create users (Security page) before opening the web view to "
                                                 "other devices.")
                return
            if not (cert and key):
                QMessageBox.warning(self, "Web", "Serving to other devices needs a TLS certificate and key.")
                return
        config = uvicorn.Config(create_app(self.state.db, https=bool(cert)), host=host, port=self.port.value(),
                                ssl_certfile=cert, ssl_keyfile=key, log_level="warning", server_header=False)
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None
        threading.Thread(target=self.server.run, daemon=True, name="fintax-web").start()
        scheme = "https" if cert else "http"
        self.web_btn.setText("Stop web server")
        self.web_lbl.setText(f"Running at {scheme}://{host if host != '0.0.0.0' else '<this computer IP>'}:"
                             f"{self.port.value()}/ – log in with your FIN TAX PRO user. On Android, open it in "
                             "Chrome and choose 'Add to Home screen'.")
