"""Return preparation: GSTR-1, GSTR-3B, GSTR-9 and GSTR-9C – checklist, figures, files to file, final mark."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...services.common import ServiceError
from ...services.return_prep import HOW, RETURNS, ReturnPrepService
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary, section

COLOURS = {"ok": "#C8E6C9", "warn": "#FFF3C4", "missing": "#FFCDD2"}
MARK = {"ok": "✔", "warn": "!", "missing": "✖"}


class ReturnPrepPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.prep, self.last_files = state, None, []
        self.svc = ReturnPrepService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Return preparation", "Prepare GSTR-1, GSTR-3B, GSTR-9 and GSTR-9C: check the data is "
                                                        "ready, review the figures, make the files for the portal and "
                                                        "mark the return final."))
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for k, v in RETURNS.items():
            self.kind.addItem(v, k)
        self.kind.currentIndexChanged.connect(lambda _i: self._period_default())
        self.period = QLineEdit()
        self.period.setMaximumWidth(100)
        check = primary("Check")
        check.clicked.connect(lambda: self.refresh())
        self.files_btn = QPushButton("Prepare files…")
        self.files_btn.clicked.connect(lambda: self.make_files())
        self.final_btn = QPushButton("Mark as final")
        self.final_btn.clicked.connect(lambda: self.mark_final())
        self.reopen_btn = QPushButton("Reopen")
        self.reopen_btn.clicked.connect(lambda: self.reopen())
        portal = QPushButton("Open GST portal")
        portal.clicked.connect(lambda: self.open_portal())
        for w in (QLabel("Return"), self.kind, QLabel("Period"), self.period, check, self.files_btn, self.final_btn,
                  self.reopen_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(portal)
        lay.addLayout(bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(section("1. Is the data ready?"))
        self.c_model = RowsModel(["", "Check"], colors=lambda r, _c: QColor(COLOURS.get(self.c_model.payload[r].status,
                                                                                         "#FFFFFF")))
        ct = Table()
        ct.setModel(self.c_model)
        ct.setSortingEnabled(False)
        ll.addWidget(ct, 1)
        self.c_table = ct
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(section("2. Figures of the return"))
        self.f_model = RowsModel(["Table", "Value", "Tax"], kinds=["text", "money", "money"])
        ft = Table()
        ft.setModel(self.f_model)
        ft.setSortingEnabled(False)
        rl.addWidget(ft, 1)
        self.f_table = ft
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([520, 700])
        lay.addWidget(split, 1)
        lay.addWidget(section("3. How to file"))
        self.how = QLabel()
        self.how.setWordWrap(True)
        lay.addWidget(self.how)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setObjectName("Muted")
        lay.addWidget(self.notes)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.refresh))
        self._period_default()

    def _period_default(self) -> None:
        kind = self.kind.currentData()
        if kind in ("GSTR9", "GSTR9C"):
            self.period.setText(self.state.fy)
        else:
            t = date.today()
            y, m = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
            self.period.setText(f"{y}-{m:02d}")
        self.how.setText(HOW[kind])
        self.lazy(self.refresh)()

    def refresh(self) -> None:
        st = self.state
        if st.client is None:
            self.status.setText("Select a client.")
            self.prep = None
            return
        try:
            self.prep = p = self.svc.prepare(self.kind.currentData(), st.client.id, self.period.text().strip())
        except ServiceError as exc:
            self.prep = None
            self.status.setText(str(exc))
            self.c_model.set_rows([])
            self.f_model.set_rows([])
            return
        self.c_model.set_rows([[MARK[c.status], c.text] for c in p.checklist], p.checklist)
        self.c_table.fit(520)
        self.f_model.set_rows([[lbl, v, t] for lbl, v, t in p.figures])
        self.f_table.fit(420)
        name = RETURNS[p.kind]
        if p.final and p.changed_since_final:
            s = (f"<span style='color:#C62828'><b>{name} {p.period} was marked final on {p.final['at']} by "
                 f"{p.final['by']}, but the data has changed since</b></span> – prepare the files again.")
        elif p.final:
            s = (f"<span style='color:#2E7D32'><b>{name} {p.period}: final</b></span> ({p.final['at']}, "
                 f"{p.final['by']}). Files: {', '.join(p.final.get('files') or []) or '—'}")
        elif p.ready:
            s = f"<b>{name} {p.period}: ready to prepare.</b> Review the figures, then Prepare files."
        else:
            s = f"<span style='color:#C62828'><b>{name} {p.period}: not ready</b></span> – complete the red items."
        self.status.setText(s)
        self.notes.setText("<br>".join(f"• {n}" for n in p.notes[:8]))
        self.files_btn.setEnabled(p.ready)
        self.final_btn.setEnabled(p.ready and (not p.final or p.changed_since_final))
        self.reopen_btn.setEnabled(bool(p.final))

    def make_files(self, out_dir: str | None = None):
        p = self.prep
        if p is None:
            return None
        st = self.state
        default = Path(st.db.data_dir) / "returns" / st.client.gstin / p.period
        out_dir = out_dir or QFileDialog.getExistingDirectory(self, "Folder for the return files", str(default))
        if not out_dir:
            return None
        firm = str(st.qsettings.value("reminder_signature", "")).strip()
        try:
            self.last_files = files = self.svc.files(p.kind, st.client.id, p.period, out_dir, st.user, firm)
        except ServiceError as exc:
            QMessageBox.warning(self, "Return preparation", str(exc))
            return None
        self.status.setText(f"{len(files)} file(s) saved in {out_dir}: " + ", ".join(f.name for f in files) +
                            ". Check them, then click Mark as final.")
        return files

    def mark_final(self):
        p = self.prep
        if p is None:
            return None
        try:
            data = self.svc.mark_final(p.kind, self.state.client.id, p.period, self.state.user,
                                       [f.name for f in self.last_files])
        except ServiceError as exc:
            QMessageBox.warning(self, "Return preparation", str(exc))
            return None
        self.refresh()
        return data

    def reopen(self) -> bool:
        p = self.prep
        if p is None or not p.final:
            return False
        self.svc.reopen(p.kind, self.state.client.id, p.period, self.state.user)
        self.refresh()
        return True

    def open_portal(self) -> bool:
        from ...services.portal import PORTAL_LOGIN

        online = getattr(self.state, "online", None)
        if online is not None and online.online is False:
            QMessageBox.information(self, "GST portal", "There is no internet connection right now.")
            return False
        return bool(QDesktopServices.openUrl(QUrl(PORTAL_LOGIN)))
