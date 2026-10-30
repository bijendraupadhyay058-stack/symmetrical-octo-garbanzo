"""Exception management: filter, compare, review, match/unmatch, attach evidence."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from ...core.models import Category, ExceptionStatus, ReconLine
from ...engine.summary import itc_at_risk
from ...services.common import ConflictError, ServiceError
from ..state import AppState
from ..theme import CATEGORY_COLORS, money
from ..widgets import CategoryChips, LazyPage, LinesFilter, LinesModel, OBJECT_ROLE, RowsModel, Table, page_header, primary

COMPARE_FIELDS = [("Supplier GSTIN", "supplier_gstin"), ("Supplier name", "supplier_name"),
                  ("Document type", "doc"), ("Invoice number", "invoice_no"), ("Invoice date", "invoice_date"),
                  ("Period", "period"), ("Taxable value", "taxable"), ("IGST", "igst"), ("CGST", "cgst"),
                  ("SGST", "sgst"), ("Cess", "cess"), ("Total ITC", "itc"), ("ITC availability", "itc_avl"),
                  ("Source (file:row)", "ref")]
MONEY_FIELDS = {"taxable", "igst", "cgst", "sgst", "cess", "itc"}


def _value(rec, key):
    if rec is None:
        return None
    if key in MONEY_FIELDS:
        return rec.signed(key)
    return {"doc": rec.doc_type.label, "ref": rec.reference, "itc_avl": rec.itc_availability or ""}.get(
        key, getattr(rec, key, None))


class ExceptionsPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        self.current: ReconLine | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        self.header = page_header("Exceptions", "")
        lay.addWidget(self.header)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search supplier, GSTIN, invoice number, reason…")
        self.search.textChanged.connect(self._filter)
        self.status_cb = QComboBox()
        self.status_cb.addItem("All statuses")
        self.status_cb.addItems([s.value for s in ExceptionStatus])
        self.status_cb.currentIndexChanged.connect(self._filter)
        self.pending_cb = QCheckBox("Pending only")
        self.pending_cb.toggled.connect(self._filter)
        bar.addWidget(self.search, 2)
        bar.addWidget(self.status_cb)
        bar.addWidget(self.pending_cb)
        lay.addLayout(bar)
        self.chips = CategoryChips()
        self.chips.changed.connect(self._filter)
        chip_scroll = QScrollArea()
        chip_scroll.setWidget(self.chips)
        chip_scroll.setWidgetResizable(True)
        chip_scroll.setFixedHeight(44)
        chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lay.addWidget(chip_scroll)

        split = QSplitter(Qt.Horizontal)
        self.model = LinesModel()
        self.proxy = LinesFilter()
        self.proxy.setSourceModel(self.model)
        self.table = Table(stretch_last=False)
        self.table.setModel(self.proxy)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.selectionModel().selectionChanged.connect(self._selected)
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("Muted")
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.table)
        ll.addWidget(self.count_lbl)
        split.addWidget(left)
        split.addWidget(self._detail_panel())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        self._suppress = False
        state.runChanged.connect(self.lazy(lambda: self.reload(-1)))
        state.dataChanged.connect(self.lazy(self._on_data))
        self.lazy(self.reload)()  # loads when first shown

    def _on_data(self) -> None:
        if not self._suppress:
            self.reload()

    # ------------------------------------------------------------- layout
    def _detail_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        w.setObjectName("Page")
        scroll.setWidget(w)
        lay = QVBoxLayout(w)
        self.detail_title = QLabel("Select a line")
        self.detail_title.setObjectName("SectionTitle")
        self.detail_title.setWordWrap(True)
        lay.addWidget(self.detail_title)
        self.cmp_model = RowsModel(["Field", "Books", "GSTR-2B", "Difference"],
                                   kinds=["text", "text", "text", "money"])
        self.cmp_table = Table()
        self.cmp_table.setSortingEnabled(False)
        self.cmp_table.setModel(self.cmp_model)
        self.cmp_table.setMinimumHeight(16 * 26 + 30)
        self.cmp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.cmp_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.cmp_table)
        self.reasons = QLabel()
        self.reasons.setWordWrap(True)
        self.reasons.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.reasons)

        actions = QHBoxLayout()
        self.confirm_btn = primary("Confirm match")
        self.confirm_btn.setToolTip("Accept the suggested pair on this line")
        self.match_btn = QPushButton("Manual match")
        self.match_btn.setToolTip("Select one books-only line and one GSTR-2B-only line (Ctrl+click)")
        self.unmatch_btn = QPushButton("Unmatch")
        self.unmatch_btn.setObjectName("Danger")
        self.clarify_btn = QPushButton("Pending clarification")
        for b, fn in ((self.confirm_btn, self.confirm), (self.match_btn, self.manual_match),
                      (self.unmatch_btn, self.unmatch), (self.clarify_btn, self.clarify)):
            b.clicked.connect(fn)
            actions.addWidget(b)
        lay.addLayout(actions)

        form = QFormLayout()
        self.status_edit = QComboBox()
        self.status_edit.addItems([s.value for s in ExceptionStatus])
        self.assigned = QLineEdit()
        self.action_set = QCheckBox("Set")
        self.action_date = QDateEdit()
        self.action_date.setCalendarPopup(True)
        self.action_date.setDisplayFormat("dd-MM-yyyy")
        self.action_date.setDate(QDate.currentDate())
        ad = QHBoxLayout()
        ad.addWidget(self.action_set)
        ad.addWidget(self.action_date)
        ad.addStretch()
        self.remarks = QPlainTextEdit()
        self.remarks.setFixedHeight(70)
        form.addRow("Status", self.status_edit)
        form.addRow("Assigned to", self.assigned)
        form.addRow("Action date", ad)
        form.addRow("Remarks", self.remarks)
        lay.addLayout(form)
        self.save_btn = primary("Save review")
        self.save_btn.clicked.connect(self.save)
        lay.addWidget(self.save_btn)

        ev = QHBoxLayout()
        ev.addWidget(QLabel("<b>Evidence</b>"))
        ev.addStretch()
        self.attach_btn = QPushButton("Attach file…")
        self.attach_btn.clicked.connect(self.attach_dialog)
        ev.addWidget(self.attach_btn)
        lay.addLayout(ev)
        self.evidence = QListWidget()
        self.evidence.setFixedHeight(70)
        self.evidence.itemDoubleClicked.connect(self._open_evidence)
        lay.addWidget(self.evidence)
        lay.addWidget(QLabel("<b>History</b>"))
        self.history = QListWidget()
        self.history.setFixedHeight(110)
        lay.addWidget(self.history)
        lay.addStretch()
        self._enable(False)
        return scroll

    # -------------------------------------------------------------- data
    def reload(self, keep_line: int | None = None) -> None:
        st = self.state
        keep_line = keep_line if isinstance(keep_line, int) and not isinstance(keep_line, bool) else (
            self.current.line_no if self.current else None)
        if st.run_id is None:
            self.header.title.setText("Exceptions")
            self.header.subtitle.setText("No reconciliation run selected.")
            self.model.set_lines([])
            self.chips.set_counts({})
            self._show(None)
            return
        ctx = st.run_context()
        self.run = ctx.run
        self.header.title.setText(f"Exceptions – {ctx.client.name}")
        self.header.subtitle.setText(f"Run #{ctx.run.id} · {ctx.run.period_from} to {ctx.run.period_to} · "
                                     "Ctrl+click two lines for a manual match")
        lines = ctx.result.lines
        selected_cats = self.chips.selected()
        self.model.set_lines(lines, st.attachments.counts(st.run_id))
        counts: dict[Category, int] = {}
        for ln in lines:
            counts[ln.category] = counts.get(ln.category, 0) + 1
        self.chips.set_counts(counts)
        if selected_cats:
            self.chips.choose(selected_cats & set(counts))
        self._filter()
        self.table.fit(220)
        self.select_line(keep_line)

    def _filter(self) -> None:
        self.proxy.categories = self.chips.selected()
        self.proxy.status = None if self.status_cb.currentIndex() == 0 else self.status_cb.currentText()
        self.proxy.pending_only = self.pending_cb.isChecked()
        self.proxy.text = self.search.text().strip()
        self.proxy.refresh()
        self.count_lbl.setText(f"{self.proxy.rowCount()} of {self.model.rowCount()} lines shown")

    def select_line(self, line_no: int | None) -> None:
        if line_no is None:
            self._show(None)
            return
        for r in range(self.proxy.rowCount()):
            ln = self.proxy.index(r, 0).data(OBJECT_ROLE)
            if ln is not None and ln.line_no == line_no:
                self.table.selectRow(r)
                self.table.scrollTo(self.proxy.index(r, 0))
                return
        self._show(None)

    def selected_lines(self) -> list[ReconLine]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.proxy.index(r, 0).data(OBJECT_ROLE) for r in rows]

    def _selected(self, *_):
        sel = self.selected_lines()
        self._show(sel[0] if sel else None)
        self.match_btn.setEnabled(len(sel) == 2 and self.state.can("review"))

    def _enable(self, on: bool) -> None:
        on = on and self.state.can("review")
        for w in (self.confirm_btn, self.unmatch_btn, self.clarify_btn, self.save_btn, self.attach_btn,
                  self.status_edit, self.assigned, self.remarks, self.action_set, self.action_date):
            w.setEnabled(on)
        self.match_btn.setEnabled(False)

    def _show(self, ln: ReconLine | None) -> None:
        self.current = ln
        self.evidence.clear()
        self.history.clear()
        if ln is None:
            self.detail_title.setText("Select a line")
            self.detail_title.setStyleSheet("")
            self.cmp_model.set_rows([])
            self.reasons.setText("")
            self._enable(False)
            return
        self._enable(True)
        self.detail_title.setText(f"Line {ln.line_no} – {ln.category.value}"
                                  + (f" · level {ln.match_level}" if ln.match_level else "")
                                  + (f" · confidence {ln.confidence}%" if ln.confidence else ""))
        self.detail_title.setStyleSheet(
            f"background: {CATEGORY_COLORS.get(ln.category, '#FFFFFF')}; padding: 6px; border-radius: 6px;")
        rows = []
        for label, key in COMPARE_FIELDS:
            b, g = _value(ln.books, key), _value(ln.gstr2b, key)
            fmt = (lambda v: money(v) if v is not None else "") if key in MONEY_FIELDS else (
                lambda v: v.strftime("%d-%m-%Y") if isinstance(v, date) else ("" if v is None else str(v)))
            diff = (ln.side("books", key) - ln.side("gstr2b", key)) if key in MONEY_FIELDS and ln.books \
                and ln.gstr2b else None
            rows.append([label, fmt(b), fmt(g), diff])
        if ln.date_diff_days:
            rows.append(["Date difference (days)", "", "", None])
            rows[-1][1] = str(ln.date_diff_days)
        self.cmp_model.set_rows(rows)
        self.cmp_table.resizeColumnToContents(0)
        self.cmp_table.resizeColumnToContents(3)
        reasons = "".join(f"<li>{r}</li>" for r in ln.reasons)
        extra = f"<p><b>ITC at risk:</b> {money(itc_at_risk(ln), True)}</p>"
        if ln.candidates:
            extra += f"<p><b>Candidates:</b> {len(ln.candidates)} document(s) – see the related lines.</p>"
        self.reasons.setText(f"<b>Reasons</b><ul>{reasons}</ul>{extra}")
        paired = ln.books is not None and ln.gstr2b is not None
        can = self.state.can("review")
        self.confirm_btn.setEnabled(can and paired and ln.category in (Category.PROBABLE,
                                                                       Category.PENDING_CLARIFICATION))
        self.unmatch_btn.setEnabled(can and paired)
        self.status_edit.setCurrentText(ln.status.value)
        self.assigned.setText(ln.assigned_to)
        self.remarks.setPlainText(ln.remarks)
        self.action_set.setChecked(ln.action_date is not None)
        if ln.action_date:
            self.action_date.setDate(QDate(ln.action_date.year, ln.action_date.month, ln.action_date.day))
        for att in self.state.attachments.for_line(self.state.run_id, ln.line_no):
            item = QListWidgetItem(f"📎 {att.file_name}  ({att.created_at:%d-%m-%Y}, {att.user}) {att.description}")
            item.setData(Qt.UserRole, att.stored_path)
            self.evidence.addItem(item)
        for h in self.state.recon.line_history(self.state.run_id, ln.line_no):
            after = h["details"].get("after", {})
            text = ", ".join(f"{k}: {v}" for k, v in after.items() if v not in (None, "")) if isinstance(after, dict) else ""
            self.history.addItem(f"{h['at']:%d-%m-%Y %H:%M} {h['user']} – {h['action']} {text}")
        if ln.books and ln.books.db_id:
            for h in self.state.tracking.document_history(ln.books.db_id):
                if h["run_id"] != self.state.run_id:
                    self.history.addItem(f"Run #{h['run_id']} ({h['period']}): {h['category']} – {h['status']}")

    # ------------------------------------------------------------ actions
    def ask(self, title: str, label: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, label)
        return text if ok else None

    def _do(self, fn, *args, keep: int | None = None) -> bool:
        try:
            result = fn(*args)
        except ServiceError as exc:
            QMessageBox.warning(self, "Exceptions", str(exc))
            return False
        self._suppress = True
        try:
            self.state.notify()  # other pages refresh; this page reloads once below
        finally:
            self._suppress = False
        self.reload(keep if keep is not None else (result if isinstance(result, int) else None))
        return True

    def save(self) -> None:
        ln = self.current
        if ln is None:
            return
        d = self.action_date.date()
        action = date(d.year(), d.month(), d.day()) if self.action_set.isChecked() else None
        try:
            ln.version = self.state.recon.update_line(
                self.state.run_id, ln.line_no, self.state.user, status=self.status_edit.currentText(),
                remarks=self.remarks.toPlainText(), assigned_to=self.assigned.text(), action_date=action,
                expected_version=ln.version)
        except ConflictError as exc:  # someone else saved this line since it was loaded
            QMessageBox.warning(self, "Changed by another user", str(exc))
            self.state.notify()
            self.reload(ln.line_no)
            return
        except ServiceError as exc:
            QMessageBox.warning(self, "Exceptions", str(exc))
            return
        # Fast path: apply the saved values to the shared in-memory line instead of reloading the run.
        ln.status = ExceptionStatus(self.status_edit.currentText())
        ln.remarks, ln.assigned_to, ln.action_date = self.remarks.toPlainText(), self.assigned.text(), action
        self.model.update_line(ln)
        self._suppress = True
        try:
            self.state.notify(keep_cache=True)
        finally:
            self._suppress = False
        self._filter()
        self.select_line(ln.line_no)

    def confirm(self) -> None:
        ln = self.current
        if ln is None:
            return
        remarks = self.ask("Confirm match", "Reason / remarks (recorded in the audit trail):")
        if remarks is not None:
            self._do(self.state.recon.confirm_match, self.state.run_id, ln.line_no, self.state.user, remarks,
                     keep=ln.line_no)

    def manual_match(self) -> None:
        sel = self.selected_lines()
        if len(sel) != 2:
            QMessageBox.information(self, "Manual match", "Select exactly two lines (Ctrl+click).")
            return
        remarks = self.ask("Manual match", "Reason / remarks (recorded in the audit trail):")
        if remarks is not None:
            self._do(self.state.recon.manual_match, self.state.run_id, sel[0].line_no, sel[1].line_no,
                     self.state.user, remarks)

    def unmatch(self) -> None:
        ln = self.current
        if ln is None:
            return
        remarks = self.ask("Unmatch", "Why are these not the same document?")
        if remarks is not None:
            self._do(self.state.recon.unmatch, self.state.run_id, ln.line_no, self.state.user, remarks,
                     keep=ln.line_no)

    def clarify(self) -> None:
        ln = self.current
        if ln is None:
            return
        remarks = self.ask("Pending clarification", "What is being asked, and from whom?")
        if remarks is not None:
            self._do(self.state.recon.mark_pending_clarification, self.state.run_id, ln.line_no, self.state.user,
                     remarks, keep=ln.line_no)

    def attach_dialog(self) -> None:
        if self.current is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Attach evidence", "", "All files (*)")
        if path:
            self.attach(path)

    def attach(self, path: str | Path, description: str = "") -> None:
        ln = self.current
        self._do(lambda: self.state.attachments.add(self.state.run_id, ln.line_no, path, self.state.user,
                                                    description), keep=ln.line_no)

    def _open_evidence(self, item: QListWidgetItem) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))
