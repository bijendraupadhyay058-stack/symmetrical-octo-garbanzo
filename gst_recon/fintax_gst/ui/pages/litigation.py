"""Litigation: GST cases from notice to order, appeal and tribunal – time limits, pre-deposit, hearings, history."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...compliance.litigation import STAGES, STATUSES
from ...core.money import fmt_inr
from ...services.common import ServiceError
from ...services.litigation import LitigationService
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, section, sortable


def _date(d: date | None) -> QDateEdit:
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd-MM-yyyy")
    w.setSpecialValueText("—")
    w.setMinimumDate(QDate(2017, 7, 1))
    w.setDate(QDate(d.year, d.month, d.day) if d else w.minimumDate())
    return w


def _py(w: QDateEdit) -> date | None:
    if w.date() == w.minimumDate():
        return None
    q = w.date()
    return date(q.year(), q.month(), q.day())


class CaseDialog(QDialog):
    def __init__(self, parent, case=None):
        super().__init__(parent)
        self.setWindowTitle("GST case" if case is None else f"Case – {case.title}")
        form = QFormLayout(self)
        self.title = QLineEdit(case.title if case else "")
        self.stage = QComboBox()
        for k, v in STAGES.items():
            self.stage.addItem(v, k)
        self.status = QComboBox()
        self.status.addItems(list(STATUSES))
        self.form, self.ref = QLineEdit(case.form if case else ""), QLineEdit(case.reference if case else "")
        self.form.setPlaceholderText("DRC-01 / DRC-07 / APL-01 / APL-05 …")
        self.order_date = _date(case.order_date if case else None)
        self.p_from, self.p_to = QLineEdit(case.period_from if case else ""), QLineEdit(case.period_to if case else "")
        self.money = {k: QLineEdit(str(getattr(case, k)) if case else "0") for k in
                      ("tax", "interest", "penalty", "tax_admitted", "pre_deposit_paid")}
        self.dep_ref, self.app_ref = QLineEdit(case.pre_deposit_ref if case else ""), QLineEdit(
            case.appeal_ref if case else "")
        self.filed = _date(case.appeal_filed_on if case else None)
        self.hearing = _date(case.hearing_date if case else None)
        self.remarks = QLineEdit(case.remarks if case else "")
        if case:
            self.stage.setCurrentIndex(list(STAGES).index(case.stage))
            self.status.setCurrentText(case.status)
        for label, w in (("Title", self.title), ("Stage", self.stage), ("Status", self.status), ("Form", self.form),
                         ("Reference / DIN", self.ref), ("Order communicated on", self.order_date),
                         ("Period from (YYYY-MM)", self.p_from), ("Period to", self.p_to),
                         ("Tax", self.money["tax"]), ("Interest", self.money["interest"]),
                         ("Penalty", self.money["penalty"]), ("Tax admitted", self.money["tax_admitted"]),
                         ("Pre-deposit paid", self.money["pre_deposit_paid"]), ("DRC-03 reference", self.dep_ref),
                         ("Appeal filed on", self.filed), ("Appeal ARN", self.app_ref), ("Next hearing", self.hearing),
                         ("Remarks", self.remarks)):
            form.addRow(label, w)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def values(self) -> dict:
        v = {"title": self.title.text(), "stage": self.stage.currentData(), "status": self.status.currentText(),
             "form": self.form.text(), "reference": self.ref.text(), "order_date": _py(self.order_date),
             "period_from": self.p_from.text(), "period_to": self.p_to.text(), "pre_deposit_ref": self.dep_ref.text(),
             "appeal_filed_on": _py(self.filed), "appeal_ref": self.app_ref.text(), "hearing_date": _py(self.hearing),
             "remarks": self.remarks.text()}
        v.update({k: w.text() for k, w in self.money.items()})
        return v


class LitigationPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.svc = LitigationService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Litigation", "GST cases from show-cause notice to order, appeal and tribunal: the "
                                                "demand, the last date to appeal, the pre-deposit, hearings and the "
                                                "history of each case."))
        bar = QHBoxLayout()
        self.all_clients = QCheckBox("All clients")
        self.all_clients.toggled.connect(lambda _on: self.reload())
        self.open_only = QCheckBox("Open cases only")
        self.open_only.setChecked(True)
        self.open_only.toggled.connect(lambda _on: self.reload())
        bar.addWidget(self.all_clients)
        bar.addWidget(self.open_only)
        bar.addStretch()
        for text, fn in (("New case…", self.new_case), ("From a notice…", self.from_notice),
                         ("Change…", self.change), ("Add to history…", self.add_event),
                         ("Make staff tasks", self.make_tasks), ("Export to Excel…", self.export),
                         ("Delete", self.delete)):
            b = primary(text) if text == "New case…" else QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            bar.addWidget(b)
        lay.addLayout(bar)
        self.alerts_lbl = QLabel()
        self.alerts_lbl.setWordWrap(True)
        lay.addWidget(self.alerts_lbl)
        split = QSplitter(Qt.Vertical)
        self.model = RowsModel(["Client", "Case", "Stage", "Form", "Reference", "Demand", "Next step by",
                                "Pre-deposit due", "Hearing", "Status"],
                               kinds=["text", "text", "text", "text", "text", "money", "date", "money", "date", "text"],
                               colors=self._colour)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.selectionModel().selectionChanged.connect(lambda *_a: self.show_events())
        split.addWidget(self.table)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("History of the selected case"))
        self.info = QLabel()
        self.info.setWordWrap(True)
        bl.addWidget(self.info)
        self.e_model = RowsModel(["Date", "Kind", "What happened", "By"], kinds=["date", "text", "text", "text"])
        et = Table()
        et.setModel(self.e_model)
        bl.addWidget(et)
        self.e_table = et
        split.addWidget(box)
        lay.addWidget(split, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _colour(self, row, _col):
        r = self.model.rows[row]
        if r[6] and r[6] < date.today():
            return QColor("#FFCDD2")
        if r[6] and (r[6] - date.today()).days <= 15 or (r[8] and 0 <= (r[8] - date.today()).days <= 7):
            return QColor("#FFF3C4")
        return None

    def _client_id(self):
        return None if self.all_clients.isChecked() or self.state.client is None else self.state.client.id

    def reload(self) -> None:
        keep = self._selected()
        keep_id = keep.id if keep is not None else None
        names = {c.id: c.name for c in self.state.clients.list()}
        cases = self.svc.cases(self._client_id(), self.open_only.isChecked())
        rows = []
        for c in cases:
            w = self.svc.working(c)
            rows.append([names.get(c.client_id, ""), c.title, STAGES.get(c.stage, c.stage), c.form, c.reference,
                         w["demand"], w["limitation"].last_date if w["limitation"] else None, w["pre_deposit_due"],
                         c.hearing_date, c.status])
        self.model.set_rows(rows, cases)
        self.table.fit(300)
        if keep_id is not None:  # the case being worked on stays selected
            for r, c in enumerate(cases):
                if c.id == keep_id:
                    self.table.selectRow(self.table.model().mapFromSource(self.model.index(r, 0)).row())
                    break
        alerts = self.svc.alerts(self._client_id())
        self.alerts_lbl.setText("<br>".join(f"<b>{a.on:%d-%m-%Y}</b> · {a.client} · {a.case.title}: {a.text}"
                                            for a in alerts[:8]) if alerts else "No time limit or hearing in the next "
                                                                                "15 days.")
        self.show_events()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def show_events(self) -> None:
        c = self._selected()
        if c is None:
            self.e_model.set_rows([])
            self.info.setText("Select a case.")
            return
        w = self.svc.working(c)
        lim = w["limitation"]
        self.info.setText(
            f"Demand ₹{fmt_inr(w['demand'])} (tax {fmt_inr(c.tax)}, interest {fmt_inr(c.interest)}, penalty "
            f"{fmt_inr(c.penalty)})"
            + (f" · next: {w['next_step'].lower()} by <b>{lim.last_date:%d-%m-%Y}</b> ({lim.basis})" if lim else "")
            + (f" · pre-deposit ₹{fmt_inr(w['pre_deposit'])} – {w['pre_deposit_basis']}; paid "
               f"₹{fmt_inr(c.pre_deposit_paid)}" if w["pre_deposit"] else ""))
        ev = self.svc.events(c.id)
        self.e_model.set_rows([[e.on, e.kind, e.text, e.user] for e in ev])
        self.e_table.fit(500)

    def new_case(self, values: dict | None = None):
        if self.state.client is None:
            QMessageBox.information(self, "Litigation", "Select a client first.")
            return None
        if values is None:
            dlg = CaseDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = dlg.values()
        try:
            c = self.svc.add(self.state.client.id, self.state.user, **values)
        except ServiceError as exc:
            QMessageBox.warning(self, "Litigation", str(exc))
            return None
        self.reload()
        return c

    def from_notice(self, notice_id: int | None = None):
        from ...services.notices import NoticeService

        if self.state.client is None:
            return None
        if notice_id is None:
            notices = NoticeService(self.state.db).list(self.state.client.id)
            if not notices:
                QMessageBox.information(self, "Litigation", "This client has no notice on the GST notices page.")
                return None
            labels = [f"{n.form} {n.reference} – {n.notice_date:%d-%m-%Y}" for n in notices]
            label, ok = QInputDialog.getItem(self, "From a notice", "Notice:", labels, 0, False)
            if not ok:
                return None
            notice_id = notices[labels.index(label)].id
        try:
            c = self.svc.from_notice(notice_id, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Litigation", str(exc))
            return None
        self.reload()
        return c

    def change(self, values: dict | None = None, event: str | None = None):
        c = self._selected()
        if c is None:
            return None
        if values is None:
            dlg = CaseDialog(self, c)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = dlg.values()
        try:
            c = self.svc.update(c.id, self.state.user, event=event, **values)
        except ServiceError as exc:
            QMessageBox.warning(self, "Litigation", str(exc))
            return None
        self.reload()
        return c

    def add_event(self, values: tuple | None = None):
        c = self._selected()
        if c is None:
            return None
        if values is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Add to history")
            form = QFormLayout(dlg)
            on, kind, text = _date(date.today()), QComboBox(), QLineEdit()
            kind.addItems(["hearing", "reply", "order", "payment", "filing", "note"])
            for label, w in (("Date", on), ("Kind", kind), ("What happened", text)):
                form.addRow(label, w)
            b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            b.accepted.connect(dlg.accept)
            b.rejected.connect(dlg.reject)
            form.addRow(b)
            if dlg.exec() != QDialog.Accepted:
                return None
            values = (_py(on) or date.today(), kind.currentText(), text.text())
        try:
            e = self.svc.add_event(c.id, *values, self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Litigation", str(exc))
            return None
        self.reload()
        return e

    def make_tasks(self) -> int:
        n = self.svc.make_tasks(self.state.user)
        self.alerts_lbl.setText(f"{n} staff task(s) created on Fees & tasks.<br>" + self.alerts_lbl.text())
        self.state.notify()
        return n

    def export(self, path: str | None = None):
        path = path or QFileDialog.getSaveFileName(self, "Cases", "GST_cases.xlsx", "Excel (*.xlsx)")[0]
        if not path:
            return None
        return self.svc.export_xlsx(path, self._client_id())

    def delete(self) -> bool:
        c = self._selected()
        if c is None or QMessageBox.question(self, "Litigation", f"Delete the case '{c.title}' and its history?") \
                != QMessageBox.Yes:
            return False
        self.svc.delete(c.id, self.state.user)
        self.reload()
        return True
