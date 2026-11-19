"""Duplicates & notes: duplicate invoices and credit / debit note checks of the client's year, each to review."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ...services.common import ServiceError
from ...services.doc_checks import DECISIONS, SOURCES, DocCheckService
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary, section

COLOURS = {"red": "#FFCDD2", "amber": "#FFF3C4", "info": "#E3F2FD"}
DONE = "#E8F5E9"
HEADS = ["Register", "Party", "GSTIN", "Finding", "Tax at stake", "Confidence", "Review", "Note"]


class DocChecksPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.report = state, None
        self.svc = DocCheckService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header(
            "Duplicates & notes", "Duplicate invoices (same number twice, the same bill in two months, numbers "
            "written two ways, same party-date-value) and credit / debit note checks (original invoice, amount, "
            "section 34 and 16(4) time limits, supplier credit notes in GSTR-2B not booked). Each finding is "
            "reviewed – nothing is deleted or changed in the data."))
        bar = QHBoxLayout()
        run = primary("Check now")
        run.clicked.connect(lambda: self.reload())
        self.src = QComboBox()
        self.src.addItem("Both registers", "")
        for k, v in SOURCES.items():
            self.src.addItem(v, k)
        self.src.currentIndexChanged.connect(lambda _i: self.fill())
        self.hide_done = QCheckBox("Hide reviewed")
        self.hide_done.toggled.connect(lambda _on: self.fill())
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda: self.export())
        for w in (run, self.src, self.hide_done):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        split = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        self.models, self.tables = {}, {}
        for area, title in (("duplicate", "Duplicate invoices"), ("note", "Credit / debit notes")):
            m = RowsModel(HEADS, kinds=["text", "text", "text", "text", "money", "text", "text", "text"],
                          colors=lambda r, _c, area=area: self._colour(area, r))
            t = Table()
            t.setModel(m)
            t.setSortingEnabled(False)
            t.selectionModel().selectionChanged.connect(lambda *_a: self.show_docs())
            self.models[area], self.tables[area] = m, t
            self.tabs.addTab(t, title)
        self.rev_model = RowsModel(["Month", "Credit notes booked", "Tax on them", "In 2B, not booked",
                                    "Tax on them", "ITC to reduce"],
                                   kinds=["text", "int", "money", "int", "money", "money"])
        rev = Table()
        rev.setModel(self.rev_model)
        self.tabs.addTab(rev, "ITC to reverse (credit notes)")
        self.tabs.currentChanged.connect(lambda _i: self.show_docs())
        split.addWidget(self.tabs)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Selected finding"))
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.detail)
        row = QHBoxLayout()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Reviewer's note (required for 'Not an issue')")
        self.ok_btn = QPushButton("Confirm (fix in Tally)")
        self.ok_btn.clicked.connect(lambda: self.mark("confirmed"))
        self.no_btn = QPushButton("Not an issue…")
        self.no_btn.clicked.connect(lambda: self.mark("not_issue"))
        self.back_btn = QPushButton("Back to 'to check'")
        self.back_btn.clicked.connect(lambda: self.mark("pending"))
        row.addWidget(self.note, 1)
        for w in (self.ok_btn, self.no_btn, self.back_btn):
            row.addWidget(w)
        bl.addLayout(row)
        bl.addStretch()
        split.addWidget(box)
        split.setSizes([520, 200])
        lay.addWidget(split, 1)
        for sig in (state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy = st.client.id, st.fy
        return lambda: DocCheckService(st.db).check(cid, fy)

    # ------------------------------------------------------------ data
    def reload(self) -> None:
        st = self.state
        self.report = None
        if st.client is None:
            self.summary.setText("Select a client.")
            for m in self.models.values():
                m.set_rows([], [])
            self.rev_model.set_rows([])
            self.show_docs()
            return
        try:
            self.report = self.svc.check(st.client.id, st.fy)
        except ServiceError as exc:
            self.summary.setText(str(exc))
            return
        self.fill()

    def _shown(self, area: str) -> list:
        r = self.report
        if r is None:
            return []
        src = self.src.currentData()
        items = r.duplicates if area == "duplicate" else r.notes
        return [f for f in items if (not src or f.source == src or (src == "BOOKS" and f.source == "GSTR2B"))
                and not (self.hide_done.isChecked() and f.decision != "pending")]

    def _colour(self, area: str, row: int):
        f = self.models[area].payload[row]
        return QColor(DONE if f.decision != "pending" else COLOURS.get(f.severity, "#FFFFFF"))

    def fill(self) -> None:
        r = self.report
        if r is None:
            return
        for area, m in self.models.items():
            items = self._shown(area)
            m.set_rows([[SOURCES.get(f.source, "GSTR-2B"), f.party, f.gstin, f.title, f.tax,
                         f.confidence or {"red": "fix", "amber": "check"}.get(f.severity, ""),
                         DECISIONS[f.decision], f.note] for f in items], items)
            self.tables[area].fit(420)
        self.rev_model.set_rows([[x["month"], x["count"], x["books"], x["nb_count"], x["not_booked"], x["total"]]
                                 for x in r.reverse])
        dup_tax = sum((f.tax for f in r.open("duplicate")), 0)
        self.summary.setText(
            f"<b>{r.client} · FY {r.fy}</b> · duplicates: {len(r.duplicates)} found, {len(r.open('duplicate'))} to "
            f"check (tax counted again ₹{dup_tax:,.2f}) · credit / debit notes: {len(r.notes)} finding(s), "
            f"{len(r.open('note'))} to check · ITC to reduce on credit notes "
            f"₹{sum((x['total'] for x in r.reverse), 0):,.2f}")
        self.show_docs()

    def area(self) -> str | None:
        return {0: "duplicate", 1: "note"}.get(self.tabs.currentIndex())

    def selected(self):
        a = self.area()
        if a is None:
            return None
        rows = self.tables[a].selectionModel().selectedRows()
        return self.models[a].payload[rows[0].row()] if rows else None

    def select(self, area: str, row: int) -> None:
        self.tabs.setCurrentIndex(0 if area == "duplicate" else 1)
        self.tables[area].selectRow(row)
        self.show_docs()

    def show_docs(self) -> None:
        f = self.selected()
        for b in (self.ok_btn, self.no_btn, self.back_btn):
            b.setEnabled(f is not None)
        if f is None:
            self.detail.setText("Select a finding to see its documents." if self.area() else
                                "Tax on supplier credit notes, month by month: reduce ITC in GSTR-3B (Table 4B) "
                                "for the month in which the credit note is received.")
            return
        docs = "<br>".join(d.text() for d in f.docs)
        mark = f"<br><i>{DECISIONS[f.decision]}{' by ' + f.marked_by if f.marked_by else ''}: {f.note}</i>" \
            if f.decision != "pending" else ""
        self.detail.setText(f"<b>{f.title}</b><br>{f.detail}<br><br>{docs}{mark}")
        self.note.setText(f.note)

    # ------------------------------------------------------------ actions
    def mark(self, decision: str, note: str | None = None) -> bool:
        f = self.selected()
        st = self.state
        if f is None or st.client is None:
            return False
        note = self.note.text() if note is None else note
        if decision == "not_issue" and not note.strip():
            note, ok = QInputDialog.getText(self, "Not an issue", "Why is this not an issue? (kept with the working)")
            if not ok:
                return False
        try:
            self.svc.mark(st.client.id, f, decision, note, st.user)
        except ServiceError as exc:
            QMessageBox.warning(self, "Duplicates & notes", str(exc))
            return False
        area, row = self.area(), self.tables[self.area()].selectionModel().selectedRows()[0].row()
        self.reload()
        if row < self.models[area].rowCount():
            self.select(area, row)
        return True

    def export(self, path: str | None = None, open_file: bool = True):
        st = self.state
        if st.client is None:
            return None
        path = path or QFileDialog.getSaveFileName(
            self, "Save duplicate and note checks", f"Duplicates_notes_{st.client.gstin}_{st.fy}_{date.today()}.xlsx",
            "Excel (*.xlsx)")[0]
        if not path:
            return None
        try:
            out = self.svc.export_xlsx(st.client.id, st.fy, path)
        except (OSError, ServiceError) as exc:
            QMessageBox.warning(self, "Duplicates & notes", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out
