"""Data health: one check of a client's year, with what to fix and where."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout, QWidget

from ...services.common import ServiceError
from ...services.health import HealthService
from ..state import AppState
from ..widgets import OBJECT_ROLE, LazyPage, RowsModel, Table, page_header, primary, section

COLOURS = {"red": "#FFCDD2", "amber": "#FFF3C4", "info": "#E3F2FD"}
LABEL = {"red": "Fix now", "amber": "Check", "info": "Note"}


class HealthPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.report = state, None
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Data health", "One check of the selected client's year: wrong GSTINs, duplicates, "
                                                  "odd dates and amounts, missing months, reconciliations not done or "
                                                  "out of date, and suppliers whose registration is cancelled."))
        bar = QHBoxLayout()
        run = primary("Check now")
        run.clicked.connect(lambda: self.reload())
        self.all_btn = QPushButton("Check all clients")
        self.all_btn.clicked.connect(lambda: self.check_all())
        self.go_btn = QPushButton("Go to the page to fix it")
        self.go_btn.clicked.connect(lambda: self.go_fix())
        self.hide_notes = QCheckBox("Hide notes")
        self.hide_notes.toggled.connect(lambda _on: self.fill())
        for w in (run, self.all_btn, self.hide_notes):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.go_btn)
        lay.addLayout(bar)
        self.score = QLabel()
        self.score.setWordWrap(True)
        lay.addWidget(self.score)
        split = QSplitter(Qt.Vertical)
        self.model = RowsModel(["", "Area", "Finding", "Count", "What to do"],
                               kinds=["text", "text", "text", "int", "text"],
                               colors=lambda r, _c: QColor(COLOURS.get(self.model.payload[r].severity, "#FFFFFF")))
        self.table = Table()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        self.table.selectionModel().selectionChanged.connect(lambda *_a: self.show_examples())
        split.addWidget(self.table)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Examples"))
        self.examples = QLabel()
        self.examples.setWordWrap(True)
        self.examples.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.examples)
        self.all_model = RowsModel(["Client", "Score", "Fix now", "Check", "Notes"],
                                   kinds=["text", "int", "int", "int", "int"])
        self.all_table = Table()
        self.all_table.setModel(self.all_model)
        bl.addWidget(self.all_table)
        split.addWidget(box)
        lay.addWidget(split, 1)
        for sig in (state.clientChanged, state.dataChanged, state.runChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def reload(self) -> None:
        st = self.state
        if st.client is None:
            self.report = None
            self.score.setText("Select a client.")
            self.model.set_rows([])
            return
        try:
            self.report = HealthService(st.db).check(st.client.id, st.fy)
        except ServiceError as exc:
            self.score.setText(str(exc))
            return
        self.fill()

    def fill(self) -> None:
        r = self.report
        if r is None:
            return
        items = [i for i in r.items if not (self.hide_notes.isChecked() and i.severity == "info")]
        self.model.set_rows([[LABEL[i.severity], i.area, i.title, i.count, i.detail] for i in items], items)
        self.table.fit(520)
        colour = "#2E7D32" if r.score >= 85 else ("#EF6C00" if r.score >= 60 else "#C62828")
        self.score.setText(f"<b>{r.client} · FY {r.fy}: health score <span style='color:{colour}'>{r.score}/100"
                           f"</span></b> · {r.count('red')} to fix now · {r.count('amber')} to check · "
                           f"{r.count('info')} note(s)" if r.items else
                           f"<b>{r.client} · FY {r.fy}: no problems found.</b>")
        self.show_examples()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.model.payload[rows[0].row()] if rows else None

    def show_examples(self) -> None:
        i = self._selected()
        self.examples.setText("<br>".join(i.examples) if i and i.examples else
                              ("No examples for this finding." if i else "Select a finding to see examples."))
        self.go_btn.setEnabled(bool(i and i.page))

    def go_fix(self) -> str | None:
        i = self._selected()
        if i is None or not i.page:
            return None
        self.navigate.emit(i.page)
        return i.page

    def check_all(self) -> list:
        svc = HealthService(self.state.db)
        rows = []
        for c in self.state.clients.list():
            try:
                rep = svc.check(c.id, self.state.fy)
            except ServiceError:
                continue
            rows.append([c.name, rep.score, rep.count("red"), rep.count("amber"), rep.count("info")])
        rows.sort(key=lambda r: r[1])
        self.all_model.set_rows(rows)
        self.all_table.fit(300)
        return rows


__all__ = ["HealthPage", "OBJECT_ROLE"]
