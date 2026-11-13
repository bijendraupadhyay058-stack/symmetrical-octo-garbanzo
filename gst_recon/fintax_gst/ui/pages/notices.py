"""GST notices received by the client, and Word reply drafts built from the reconciliations."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

from ...notices.content import FORMS
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, card, page_header, primary, section, sortable


def _date_edit(d: QDate | None = None) -> QDateEdit:
    e = QDateEdit(d or QDate.currentDate())
    e.setCalendarPopup(True)
    e.setDisplayFormat("dd-MM-yyyy")
    return e


def _py(e: QDateEdit) -> date:
    d = e.date()
    return date(d.year(), d.month(), d.day())


class NoticesPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("GST notices", "Register of DRC-01B, DRC-01C, ASMT-10 and other notices, with reply "
                                                 "drafts built from the reconciliations – drafts only, nothing is "
                                                 "filed."))
        frame, fl = card()
        fl.addWidget(section("Record a notice"))
        grid = QGridLayout()
        self.form_cb = QComboBox()
        for code, label in FORMS.items():
            self.form_cb.addItem(f"{code} – {label}"[:80], code)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("Reference / DIN")
        self.notice_date = _date_edit()
        self.p_from, self.p_to = QLineEdit(), QLineEdit()
        self.p_from.setPlaceholderText("From YYYY-MM")
        self.p_to.setPlaceholderText("To YYYY-MM")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Amount in the notice")
        self.due_set = QCheckBox("Reply by")
        self.due_set.setChecked(True)
        self.reply_due = _date_edit(QDate.currentDate().addDays(30))
        self.officer = QLineEdit()
        self.officer.setPlaceholderText("Officer – designation, range / division")
        self.form_cb.setMaximumWidth(300)
        self.reference.setMinimumWidth(170)
        for w in (self.p_from, self.p_to):
            w.setMinimumWidth(100)
        self.amount.setMinimumWidth(140)
        self.reply_due.setMaximumWidth(140)
        self.add_btn = primary("Add notice")
        self.add_btn.clicked.connect(self.add)
        for i, (label, w) in enumerate((("Form", self.form_cb), ("Reference", self.reference),
                                        ("Date", self.notice_date), ("Period", self.p_from), ("", self.p_to),
                                        ("Amount", self.amount))):
            grid.addWidget(QLabel(label), 0, 2 * i)
            grid.addWidget(w, 0, 2 * i + 1)
        due = QHBoxLayout()
        due.addWidget(self.due_set)
        due.addWidget(self.reply_due)
        grid.addLayout(due, 1, 0, 1, 3)
        grid.addWidget(self.officer, 1, 3, 1, 6)
        grid.addWidget(self.add_btn, 1, 11)
        fl.addLayout(grid)
        lay.addWidget(frame)
        row = QHBoxLayout()
        self.draft_btn = primary("Draft reply…")
        self.draft_btn.clicked.connect(self.draft)
        self.signatory = QLineEdit()
        self.signatory.setPlaceholderText("Signatory (optional)")
        self.replied_btn = QPushButton("Mark replied")
        self.replied_btn.clicked.connect(lambda: self.set_status("REPLIED"))
        self.closed_btn = QPushButton("Mark closed")
        self.closed_btn.clicked.connect(lambda: self.set_status("CLOSED"))
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        for w in (self.draft_btn, self.signatory, self.replied_btn, self.closed_btn, self.delete_btn):
            row.addWidget(w)
        row.addWidget(self.info, 1)
        lay.addLayout(row)
        self.model = RowsModel(["#", "Form", "Reference", "Date", "Period", "Amount", "Reply by", "Status",
                                "Replied on", "Officer"],
                               kinds=["int", "text", "text", "date", "text", "money", "date", "text", "date", "text"],
                               colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        lay.addWidget(self.table, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _color(self, row, col):
        if col not in (6, 7):
            return None
        r = self.model.rows[row]
        if r[7] == "OPEN" and r[6] is not None and r[6] < date.today():
            return QColor("#FFCDD2")
        return QColor("#C8E6C9") if r[7] != "OPEN" else None

    def _svc(self):
        from ...services.notices import NoticeService

        return NoticeService(self.state.db)

    def _selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.model().index(rows[0].row(), 0).data(OBJECT_ROLE) if rows else None

    def reload(self) -> None:
        st = self.state
        can = st.client is not None and st.can("review")
        for b in (self.add_btn, self.replied_btn, self.closed_btn, self.delete_btn):
            b.setEnabled(can)
        self.draft_btn.setEnabled(st.client is not None and st.can("export"))
        if st.client is None:
            self.model.set_rows([])
            self.info.setText("Select a client.")
            return
        notices = self._svc().list(st.client.id)
        self.model.set_rows([[n.id, n.form, n.reference, n.notice_date,
                              n.period_from if n.period_from == n.period_to else f"{n.period_from}..{n.period_to}",
                              n.amount, n.reply_due, n.status, n.replied_on, n.officer] for n in notices],
                            [n.id for n in notices])
        self.table.fit(300)
        due = [n for n in notices if n.status == "OPEN" and n.reply_due and n.reply_due <= date.today()]
        self.info.setText(f"{len(notices)} notice(s); {len(due)} open with the reply date reached." if notices
                          else "No notices recorded for this client.")

    def add(self) -> None:
        st = self.state
        try:
            self._svc().add(st.client.id, st.session, form=self.form_cb.currentData(),
                            reference=self.reference.text().strip(), notice_date=_py(self.notice_date),
                            period_from=self.p_from.text().strip(),
                            period_to=self.p_to.text().strip() or self.p_from.text().strip(),
                            amount=self.amount.text().strip() or None,
                            reply_due=_py(self.reply_due) if self.due_set.isChecked() else None,
                            officer=self.officer.text().strip())
        except ServiceError as exc:
            QMessageBox.warning(self, "GST notices", str(exc))
            return
        for w in (self.reference, self.amount, self.p_from, self.p_to):
            w.clear()
        st.notify()

    def set_status(self, status: str) -> None:
        nid = self._selected_id()
        if nid is None:
            return
        try:
            self._svc().update(nid, self.state.session, status=status)
        except ServiceError as exc:
            QMessageBox.warning(self, "GST notices", str(exc))
            return
        self.state.notify()

    def delete(self) -> None:
        nid = self._selected_id()
        if nid is None or QMessageBox.question(self, "GST notices", f"Delete notice #{nid} from the register? "
                                               "This is recorded in the audit log.") != QMessageBox.Yes:
            return
        self._svc().delete(nid, self.state.session)
        self.state.notify()

    def draft(self, out_dir: str | None = None):
        nid = self._selected_id()
        if nid is None:
            QMessageBox.information(self, "GST notices", "Select a notice first.")
            return None
        out_dir = out_dir or QFileDialog.getExistingDirectory(self, "Folder for the draft reply")
        if not out_dir:
            return None
        try:
            path, d = self._svc().draft(nid, out_dir, signatory=self.signatory.text().strip(), user=self.state.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "GST notices", str(exc))
            return None
        QMessageBox.information(self, "GST notices", f"Draft saved:\n{path}\n\n{d.placeholders} highlighted item(s) "
                                "to complete, or to delete before sending (working notes). Review the whole reply "
                                "before filing it.")
        return path
