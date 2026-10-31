"""Firm work dashboard: every client's stage for a month, deadlines across clients and staff workload."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...services.common import ServiceError
from ...services.firm import STAGES, UNASSIGNED
from ..state import AppState
from ..widgets import OBJECT_ROLE, KpiCard, LazyPage, RowsModel, Table, page_header, primary, section, sortable

STAGE_COLORS = {"Awaiting data": "#ECEFF1", "Data incomplete": "#FFE0B2", "Ready to reconcile": "#FFF3C4",
                "Under review": "#BBDEFB", "Reviewed – file returns": "#D1C4E9", "Done": "#C8E6C9"}
STATE_COLORS = {"overdue": "#FFCDD2", "due soon": "#FFF3C4", "filed late": "#FFE0B2", "filed": "#C8E6C9"}
ALL = "All staff"


def previous_month(today: date | None = None) -> str:
    today = today or date.today()
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return f"{y:04d}-{m:02d}"


class FilingDialog(QDialog):
    """Record the filing date of one of the client's returns for the month."""

    def __init__(self, parent, client: str, period: str, return_types: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Record filing")
        form = QFormLayout(self)
        form.addRow("Client", QLabel(client))
        form.addRow("Period", QLabel(period))
        self.rtype = QComboBox()
        self.rtype.addItems(return_types)
        self.filed = QDateEdit(QDate.currentDate())
        self.filed.setCalendarPopup(True)
        self.filed.setDisplayFormat("dd-MM-yyyy")
        self.arn = QLineEdit()
        self.arn.setPlaceholderText("ARN (optional)")
        form.addRow("Return", self.rtype)
        form.addRow("Filed on", self.filed)
        form.addRow("ARN", self.arn)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, date, str]:
        d = self.filed.date()
        return self.rtype.currentText(), date(d.year(), d.month(), d.day()), self.arn.text().strip()


class FirmPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.work = None
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Firm work dashboard", "Where every client stands for the month, what falls due "
                                                         "and who has what to do."))
        bar = QHBoxLayout()
        self.period = QLineEdit(previous_month())
        self.period.setMaximumWidth(90)
        self.period.setPlaceholderText("YYYY-MM")
        self.period.returnPressed.connect(self.reload)
        self.staff_cb = QComboBox()
        self.staff_cb.setMinimumWidth(150)
        self.staff_cb.activated.connect(lambda _i: self.reload())
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        export = QPushButton("Export to Excel…")
        export.clicked.connect(self.export)
        for w in (QLabel("Month"), self.period, QLabel("Staff"), self.staff_cb, refresh):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(export)
        lay.addLayout(bar)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards: dict[str, KpiCard] = {}
        for i, stage in enumerate(STAGES):
            self.cards[stage] = KpiCard(stage, "#90A4AE" if i == 0 else "#00897B" if stage == "Done" else "#1F5FA8")
            grid.addWidget(self.cards[stage], 0, i)
        self.cards["overdue"] = KpiCard("Overdue deadlines", "#C62828")
        grid.addWidget(self.cards["overdue"], 0, len(STAGES))
        lay.addLayout(grid)
        actions = QHBoxLayout()
        self.open_btn = primary("Open client")
        self.open_btn.clicked.connect(self.open_client)
        self.filing_btn = QPushButton("Record filing…")
        self.filing_btn.clicked.connect(self.record_filing)
        self.staff_btn = QPushButton("Set responsible staff…")
        self.staff_btn.clicked.connect(self.set_staff)
        self.report_btn = QPushButton("Client report (PDF)…")
        self.report_btn.setToolTip("One-page GST summary of the month for the selected client – or, with no client "
                                   "selected, for every client in the list")
        self.report_btn.clicked.connect(lambda: self.client_reports())
        self.info = QLabel()
        self.info.setObjectName("Muted")
        for w in (self.open_btn, self.filing_btn, self.staff_btn, self.report_btn):
            actions.addWidget(w)
        actions.addWidget(self.info, 1)
        lay.addLayout(actions)
        self.model = RowsModel(["Client", "GSTIN", "Staff", "Stage", "Next step", "Open lines", "ITC at risk",
                                "Return 1", "Return 2", "Notices", "Last activity"],
                               kinds=["text", "text", "text", "text", "text", "int", "money", "text", "text",
                                      "int", "text"], colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.doubleClicked.connect(lambda _i: self.open_client())
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        lower = QWidget()
        ll = QHBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(section("Deadlines (overdue and next 15 days)"))
        self.dl_model = RowsModel(["Date", "Client", "Staff", "Item", "State"],
                                  kinds=["date", "text", "text", "text", "text"], colors=self._dl_color)
        self.dl_table = Table()
        self.dl_table.setModel(sortable(self.dl_model))
        left.addWidget(self.dl_table)
        right.addWidget(section("Staff workload"))
        self.staff_model = RowsModel(["Staff", "Clients", "Not done", "Open lines assigned", "Past action date"],
                                     kinds=["text", "int", "int", "int", "int"])
        self.staff_table = Table()
        self.staff_table.setModel(sortable(self.staff_model))
        right.addWidget(self.staff_table)
        ll.addLayout(left, 3)
        ll.addLayout(right, 2)
        split.addWidget(lower)
        split.setSizes([420, 260])
        lay.addWidget(split, 1)
        self.staff_btn.setEnabled(state.can("manage_clients"))
        self.filing_btn.setEnabled(state.can("review"))
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # ------------------------------------------------------------------ data
    def _svc(self):
        from ...services.firm import FirmService

        return FirmService(self.state.db)

    def _fill_staff(self) -> None:
        current = self.staff_cb.currentText() or ALL
        self.staff_cb.blockSignals(True)
        self.staff_cb.clear()
        self.staff_cb.addItems([ALL, *self._svc().staff_names(), UNASSIGNED])
        self.staff_cb.setCurrentText(current if self.staff_cb.findText(current) >= 0 else ALL)
        self.staff_cb.blockSignals(False)

    def reload(self) -> None:
        self._fill_staff()
        staff = None if self.staff_cb.currentText() == ALL else self.staff_cb.currentText()
        try:
            self.work = w = self._svc().work(self.period.text().strip(), staff=staff)
        except ServiceError as exc:
            self.info.setText(str(exc))
            return
        self.period.setText(w.period)
        for stage in STAGES:
            self.cards[stage].set(str(w.count(stage)), "client(s)")
        overdue = [d for d in w.deadlines if d.state == "overdue"]
        self.cards["overdue"].set(str(len(overdue)), f"{len(w.deadlines)} in the next 15 days" if w.deadlines else "")
        rows = []
        for c in w.clients:
            rets = [f"{r.return_type}: {r.state(w.today)}" + (f" {r.filed_on:%d-%m}" if r.filed_on
                                                              else f" (due {r.due:%d-%m})") for r in c.returns]
            rets += ["", ""]
            notices = c.notices_open
            rows.append([c.name, c.gstin, c.staff, c.stage, c.next_step, c.pending, c.itc_at_risk, rets[0], rets[1],
                         notices, f"{c.last_activity:%d-%m-%Y}" if c.last_activity else ""])
        self.model.set_rows(rows, w.clients)
        self.table.fit(380)
        self.dl_model.set_rows([[d.on, d.client, d.staff, d.item, d.state] for d in w.deadlines])
        self.dl_table.fit(260)
        self.staff_model.set_rows([[s.person, s.clients, s.clients_open, s.pending_lines, s.overdue_actions]
                                   for s in w.staff])
        self.staff_table.fit(200)
        self.info.setText(f"{len(w.clients)} client(s) · {w.period}" if w.clients else
                          "No active clients" + (" for this staff member." if staff else "."))

    def _color(self, row, col):
        if col == 3:
            return QColor(STAGE_COLORS.get(self.model.rows[row][3], "#FFFFFF"))
        if col in (7, 8):
            text = self.model.rows[row][col]
            state = next((s for s in ("filed late", "overdue", "due soon", "filed") if f": {s}" in text), None)
            return QColor(STATE_COLORS[state]) if state else None
        return None

    def _dl_color(self, row, col):
        return QColor(STATE_COLORS.get(self.dl_model.rows[row][4], "#FFFFFF")) if col == 4 else None

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    # --------------------------------------------------------------- actions
    def open_client(self) -> None:
        c = self._selected()
        if c is None:
            QMessageBox.information(self, "Firm work", "Select a client in the list first.")
            return
        self.state.set_client(self.state.clients.get(c.client_id))
        self.navigate.emit("workflow")

    def record_filing(self, values: tuple[str, date, str] | None = None) -> bool:
        c = self._selected()
        if c is None or self.work is None:
            QMessageBox.information(self, "Firm work", "Select a client in the list first.")
            return False
        if values is None:
            dlg = FilingDialog(self, c.name, self.work.period, [r.return_type for r in c.returns])
            if dlg.exec() != QDialog.Accepted:
                return False
            values = dlg.values()
        from ...services.interest import InterestService

        rtype, filed_on, arn = values
        try:
            InterestService(self.state.db).set_filing(c.client_id, rtype, self.work.period, filed_on,
                                                      self.state.session, arn)
        except ServiceError as exc:
            QMessageBox.warning(self, "Record filing", str(exc))
            return False
        self.state.notify()
        self.reload()
        return True

    def set_staff(self, name: str | None = None) -> bool:
        c = self._selected()
        if c is None:
            QMessageBox.information(self, "Firm work", "Select a client in the list first.")
            return False
        if name is None:
            from ...services.auth import AuthService

            names = ["", *sorted({u.username for u in AuthService(self.state.db).users() if u.active}
                                 | set(self._svc().staff_names()))]
            name, ok = QInputDialog.getItem(self, "Responsible staff", f"Staff member responsible for {c.name}:",
                                            names, names.index(c.staff) if c.staff in names else 0, True)
            if not ok:
                return False
        try:
            self.state.clients.update(c.client_id, self.state.user, staff=name.strip()[:80])
        except ServiceError as exc:
            QMessageBox.warning(self, "Responsible staff", str(exc))
            return False
        self.state.notify()
        self.reload()
        return True

    def client_reports(self, out_dir: str | None = None, all_clients: bool | None = None):
        """One-page PDF per client: the selected one, or all listed clients."""
        if self.work is None or not self.work.clients:
            return None
        c = self._selected()
        if all_clients is None:
            all_clients = c is None
        out_dir = out_dir or QFileDialog.getExistingDirectory(self, "Folder for the client report(s)")
        if not out_dir:
            return None
        from ...reports.client_report import build_reports
        from ..workers import run_task

        ids = [x.client_id for x in self.work.clients] if all_clients else [c.client_id]
        firm = str(self.state.qsettings.value("reminder_signature", "")).strip()
        task = run_task(self, "Preparing client reports", build_reports, self.state.db, self.work.period, out_dir,
                        ids, firm)
        if not task.ok:
            QMessageBox.warning(self, "Client report", task.message)
            return None
        paths = task.result_value
        self.info.setText(f"{len(paths)} client report(s) saved in {out_dir}")
        if len(paths) == 1:  # a single report opens straight away
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0])))
        return paths

    def export(self, path: str | None = None):
        if self.work is None:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Export firm work", f"firm_work_{self.work.period}.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        from ...services.firm import export_xlsx

        out = export_xlsx(self.work, path)
        self.info.setText(f"Saved {out}")
        return out
