"""Outbox: e-mails prepared by the program, checked and sent by the user through the firm's mail account."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ...services.common import ServiceError
from ...services.mailer import KINDS, MailService
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, sortable

STATUSES = {"draft": "To send", "failed": "Failed", "sent": "Sent", "cancelled": "Cancelled", "": "All"}


class OutboxPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.svc = MailService(state.db)
        self.mails = []
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Outbox", "Supplier letters, client reports and document reminders prepared as "
                                            "e-mails. Check each one, then send – nothing goes out until you click "
                                            "Send."))
        bar = QHBoxLayout()
        self.status_cb = QComboBox()
        for k, label in STATUSES.items():
            self.status_cb.addItem(label, k)
        self.status_cb.currentIndexChanged.connect(lambda _i: self.reload())
        self.account_lbl = QLabel()
        acc_btn = QPushButton("E-mail account…")
        acc_btn.clicked.connect(lambda: self.edit_account())
        acc_btn.setEnabled(state.can("settings"))
        bar.addWidget(QLabel("Show"))
        bar.addWidget(self.status_cb)
        bar.addStretch()
        bar.addWidget(self.account_lbl)
        bar.addWidget(acc_btn)
        lay.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.model = RowsModel(["#", "Type", "Client", "To", "Subject", "Files", "Status", "Check"],
                               kinds=["int", "text", "text", "text", "text", "int", "text", "text"],
                               colors=self._color)
        self.table = Table()
        self.table.setModel(sortable(self.model))
        self.table.selectionModel().selectionChanged.connect(lambda *_a: self.show_mail())
        ll.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.send_btn = primary("Send selected")
        self.send_btn.clicked.connect(lambda: self.send_selected())
        self.cancel_btn = QPushButton("Remove selected")
        self.cancel_btn.clicked.connect(lambda: self.cancel_selected())
        self.info = QLabel()
        self.info.setWordWrap(True)
        row.addWidget(self.send_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.info, 1)
        ll.addLayout(row)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.to, self.cc, self.subject = QLineEdit(), QLineEdit(), QLineEdit()
        self.to.setPlaceholderText("e-mail address(es), separated by commas")
        form.addRow("To", self.to)
        form.addRow("Cc", self.cc)
        form.addRow("Subject", self.subject)
        rl.addLayout(form)
        self.body = QPlainTextEdit()
        rl.addWidget(self.body, 1)
        self.files_lbl = QLabel()
        self.files_lbl.setWordWrap(True)
        self.files_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.files_lbl.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        rl.addWidget(self.files_lbl)
        self.save_btn = QPushButton("Save changes")
        self.save_btn.clicked.connect(lambda: self.save_mail())
        rl.addWidget(self.save_btn)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([700, 480])
        lay.addWidget(split, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _color(self, row, _col):
        st = self.model.rows[row][6]
        return {"Failed": QColor("#FFCDD2"), "Sent": QColor("#C8E6C9")}.get(st) or (
            QColor("#FFF3C4") if self.model.rows[row][7] else None)

    def reload(self) -> None:
        acc = self.svc.account()
        self.account_lbl.setText(f"Sending from <b>{acc.sender}</b>" if acc.ready else
                                 "<span style='color:#C62828'>No e-mail account set up yet</span>")
        names = {c.id: c.name for c in self.state.clients.list()}
        self.mails = self.svc.drafts(self.status_cb.currentData() or None)
        rows = []
        for m in self.mails:
            files = json.loads(m.attachments_json)
            check = "; ".join(self.svc.problems(m)) if m.status in ("draft", "failed") else ""
            if m.status == "failed":
                check = (m.error + ("; " + check if check else "")).strip("; ")
            rows.append([m.id, KINDS.get(m.kind, m.kind), names.get(m.client_id, ""), m.to_addr, m.subject,
                         len(files), STATUSES.get(m.status, m.status), check])
        self.model.set_rows(rows, self.mails)
        self.table.fit(320)
        ready = sum(1 for r in rows if r[6] == "To send" and not r[7])
        self.info.setText(f"{len(rows)} mail(s) · {ready} ready to send" if rows else "The outbox is empty.")
        self.send_btn.setEnabled(acc.ready and self.state.can("letters"))
        self.show_mail()

    def selected(self) -> list:
        rows = self.table.selectionModel().selectedRows()
        return [self.table.model().index(r.row(), 0).data(OBJECT_ROLE) for r in rows]

    def show_mail(self) -> None:
        sel = self.selected()
        m = sel[0] if len(sel) == 1 else None
        editable = m is not None and m.status in ("draft", "failed")
        for w in (self.to, self.cc, self.subject):
            w.setText(getattr(m, {self.to: "to_addr", self.cc: "cc_addr", self.subject: "subject"}[w]) if m else "")
            w.setReadOnly(not editable)
        self.body.setPlainText(m.body if m else "")
        self.body.setReadOnly(not editable)
        self.save_btn.setEnabled(editable)
        files = json.loads(m.attachments_json) if m else []
        self.files_lbl.setText("Attached: " + ", ".join(
            f"<a href='{QUrl.fromLocalFile(f).toString()}'>{Path(f).name}</a>" for f in files) if files else "")

    def save_mail(self) -> bool:
        sel = self.selected()
        if len(sel) != 1:
            return False
        try:
            self.svc.update_draft(sel[0].id, self.state.user, to_addr=self.to.text().strip(),
                                  cc_addr=self.cc.text().strip(), subject=self.subject.text().strip(),
                                  body=self.body.toPlainText())
        except ServiceError as exc:
            QMessageBox.warning(self, "Outbox", str(exc))
            return False
        keep = sel[0].id
        self.reload()
        for r, m in enumerate(self.model.payload or []):
            if m.id == keep:
                self.table.selectRow(self.table.model().mapFromSource(self.model.index(r, 0)).row())
        return True

    def edit_account(self) -> bool:
        from ..dialogs.mail_account import MailAccountDialog

        ok = MailAccountDialog(self, self.state).exec() == MailAccountDialog.Accepted
        self.reload()
        return ok

    def send_selected(self, password: str | None = None):
        from ..workers import run_task

        sel = [m for m in self.selected() if m.status in ("draft", "failed")]
        if not sel:
            QMessageBox.information(self, "Outbox", "Select the mails to send (only unsent ones are sent).")
            return None
        if password is None and not self.svc.has_saved_password() and self.svc.account().username:
            password, ok = QInputDialog.getText(self, "E-mail password", "Password (app password) of "
                                                f"{self.svc.account().username}:", QLineEdit.Password)
            if not ok:
                return None
        if QMessageBox.question(self, "Send e-mails", f"Send {len(sel)} e-mail(s) now from "
                                f"{self.svc.account().sender}?") != QMessageBox.Yes:
            return None
        task = run_task(self, "Sending e-mails", self.svc.send, [m.id for m in sel], self.state.session, password,
                        cancellable=False)
        if not task.ok:
            QMessageBox.warning(self, "Outbox", task.message)
            self.reload()
            return None
        sent, problems = task.result_value
        QMessageBox.information(self, "Outbox", f"{sent} e-mail(s) sent." + (
            "\n\nNot sent:\n" + "\n".join(problems[:15]) if problems else ""))
        self.state.notify()
        return sent, problems

    def cancel_selected(self) -> int:
        sel = self.selected()
        if not sel:
            return 0
        n = self.svc.cancel([m.id for m in sel], self.state.user)
        self.reload()
        return n
