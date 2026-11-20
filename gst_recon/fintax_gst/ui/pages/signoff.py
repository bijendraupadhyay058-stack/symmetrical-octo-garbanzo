"""Sign-off: preparer and reviewer of each working paper of the client's year, out of date when data changes."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ...services.auth import PermissionDenied
from ...services.common import ServiceError
from ...services.signoff import SignOffService
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary

COLOURS = {"not_prepared": "#FFFFFF", "prepared": "#FFF3C4", "reviewed": "#C8E6C9", "changed": "#FFCDD2"}


class SignOffPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.rows = state, []
        self.svc = SignOffService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header(
            "Sign-off", "Who prepared and who reviewed each working paper of the client's year. A different person "
            "must review. If the data behind a working changes after sign-off (a new import, a decision, a "
            "classification, a review mark) it shows as out of date and must be prepared and reviewed again."))
        bar = QHBoxLayout()
        self.prep_btn = primary("Mark prepared…")
        self.prep_btn.clicked.connect(lambda: self.prepare())
        self.rev_btn = QPushButton("Mark reviewed…")
        self.rev_btn.clicked.connect(lambda: self.review())
        self.reopen_btn = QPushButton("Reopen…")
        self.reopen_btn.clicked.connect(lambda: self.reopen())
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda: self.export())
        for b in (self.prep_btn, self.rev_btn, self.reopen_btn):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.model = RowsModel(["Working paper", "Status", "Prepared by", "Prepared on", "Note", "Reviewed by",
                                "Reviewed on", "Reviewer's note"],
                               colors=lambda r, _c: QColor(COLOURS.get(self.model.payload[r].state, "#FFFFFF")))
        self.table = Table()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        lay.addWidget(self.table, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy = st.client.id, st.fy
        return lambda: SignOffService(st.db).status(cid, fy)

    def reload(self) -> None:
        st = self.state
        if st.client is None:
            self.rows = []
            self.model.set_rows([], [])
            self.summary.setText("Select a client.")
            return
        try:
            self.rows = self.svc.status(st.client.id, st.fy)
        except ServiceError as exc:
            self.summary.setText(str(exc))
            return

        def when(d):
            return f"{d:%d-%m-%Y %H:%M}" if d else ""

        self.model.set_rows([[x.title, x.label, x.row.prepared_by if x.row else "",
                              when(x.row.prepared_at) if x.row else "", x.row.prepared_note if x.row else "",
                              x.row.reviewed_by if x.row else "", when(x.row.reviewed_at) if x.row else "",
                              x.row.review_note if x.row else ""] for x in self.rows], self.rows)
        self.table.fit(360)
        n = {k: sum(1 for x in self.rows if x.state == k) for k in COLOURS}
        self.summary.setText(f"<b>{st.client.name} · FY {st.fy}</b> · reviewed {n['reviewed']} · awaiting review "
                             f"{n['prepared']} · out of date {n['changed']} · not prepared {n['not_prepared']} · "
                             f"you are signed in as <b>{st.user}</b>")

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.rows[rows[0].row()] if rows else None

    def _note(self, title: str, label: str, note: str | None) -> str | None:
        if note is not None:
            return note
        text, ok = QInputDialog.getText(self, title, label)
        return text if ok else None

    def _do(self, fn, *args) -> bool:
        try:
            fn(*args)
        except (ServiceError, PermissionDenied) as exc:
            QMessageBox.warning(self, "Sign-off", str(exc))
            return False
        self.reload()
        return True

    def prepare(self, note: str | None = None) -> bool:
        x, st = self.selected(), self.state
        if x is None:
            QMessageBox.information(self, "Sign-off", "Select a working paper first.")
            return False
        note = self._note("Prepared", f"{x.title}: preparer's note (optional)", note)
        return note is not None and self._do(self.svc.prepare, st.client.id, st.fy, x.area, st.session, note)

    def review(self, note: str | None = None) -> bool:
        x, st = self.selected(), self.state
        if x is None:
            QMessageBox.information(self, "Sign-off", "Select a working paper first.")
            return False
        note = self._note("Reviewed", f"{x.title}: reviewer's note (optional)", note)
        return note is not None and self._do(self.svc.review, st.client.id, st.fy, x.area, st.session, note)

    def reopen(self, reason: str | None = None) -> bool:
        x, st = self.selected(), self.state
        if x is None or x.row is None:
            return False
        reason = self._note("Reopen", f"{x.title}: why reopen? (kept in the audit log)", reason)
        return reason is not None and self._do(self.svc.reopen, st.client.id, st.fy, x.area, st.session, reason)

    def export(self, path: str | None = None, open_file: bool = True):
        st = self.state
        if st.client is None:
            return None
        path = path or QFileDialog.getSaveFileName(self, "Save sign-off sheet",
                                                   f"Signoff_{st.client.gstin}_{st.fy}.xlsx", "Excel (*.xlsx)")[0]
        if not path:
            return None
        try:
            out = self.svc.export_xlsx(st.client.id, st.fy, path)
        except (OSError, ServiceError) as exc:
            QMessageBox.warning(self, "Sign-off", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out
