"""Return comparison: GSTR-3B vs GSTR-2B, GSTR-1 vs GSTR-3B and GSTR-2A vs GSTR-2B, from the returns downloaded
from the GST portal (imported here directly)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QTabWidget, QVBoxLayout,
    QWidget,
)

from ...core.money import fmt_inr
from ...services.common import ServiceError
from ...services.return_compare import (
    DOC_STATUSES, KINDS, MATCHED, RETURN_LABELS, RETURN_TYPES, ReturnCompareService,
)
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, primary, section, sortable

RED, AMBER, GREEN, GREY = "#FFCDD2", "#FFF3C4", "#C8E6C9", "#EEEEEE"
SEVERITY = {"high": RED, "medium": AMBER, "info": "#E3F2FD"}
PORTAL_FILTER = "GST portal files (*.json *.zip *.xlsx *.xls *.csv *.pdf);;All files (*)"
HOW = ("<b>Download from the GST portal</b> (sign in on the official site yourself – the program never asks for "
       "your portal password): Returns Dashboard → choose the year and month →<br>"
       "• <b>GSTR-1</b>: GSTR-1 → View / Download → JSON (ZIP) &nbsp; • <b>GSTR-3B</b>: GSTR-3B → Download filed "
       "GSTR-3B (PDF) or the JSON &nbsp; • <b>GSTR-2A</b>: GSTR-2A → Download → Generate JSON / Excel &nbsp; "
       "• <b>GSTR-2B</b>: GSTR-2B → Download → JSON / Excel.<br>Then press <b>Import from GST portal</b> and pick "
       "the files (several at once), or <b>Pick up from Downloads</b>. The GSTIN in each file decides the client.")


def _status_colour(text: str) -> str:
    return GREEN if text == "Matches" else RED if text == "Difference" else GREY


class CompareTab(QWidget):
    """One comparison: months, the breakdown of the month selected, findings (and documents for 2A vs 2B)."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind, self.comp = kind, None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        self.kpi = QLabel()
        self.kpi.setWordWrap(True)
        self.kpi.setTextFormat(Qt.RichText)
        lay.addWidget(self.kpi)
        split = QSplitter(Qt.Vertical)
        self.m_model = RowsModel(["Month", "Status", "Left", "Right", "Difference", "IGST diff", "CGST diff",
                                  "SGST diff", "Cess diff"],
                                 kinds=["text", "text"] + ["money"] * 7,
                                 colors=lambda r, c: QColor(_status_colour(self.m_model.rows[r][1])) if c == 1 else None)
        self.m_table = Table()
        self.m_table.setModel(self.m_model)
        self.m_table.setSortingEnabled(False)
        self.m_table.selectionModel().currentRowChanged.connect(lambda cur, _p: self.show_month(cur.row()))
        split.addWidget(self.m_table)
        bottom = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.d_title = section("Breakdown of the month")
        ll.addWidget(self.d_title)
        self.d_model = RowsModel(["Line", "Left taxable", "Left tax", "Right taxable", "Right tax", "Difference"],
                                 kinds=["text"] + ["money"] * 5,
                                 colors=lambda r, c: QColor(RED) if c == 5 and self.d_model.rows[r][5] not in (
                                     None, 0) and abs(self.d_model.rows[r][5]) > 1 else None)
        dt = Table()
        dt.setModel(self.d_model)
        dt.setSortingEnabled(False)
        ll.addWidget(dt, 1)
        self.d_table = dt
        bottom.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(section("Findings"))
        self.f_model = RowsModel(["Month", "Finding", "Amount"], kinds=["text", "text", "money"],
                                 colors=lambda r, _c: QColor(SEVERITY.get(self.f_model.payload[r].severity, "#FFFFFF")))
        ft = Table()
        ft.setModel(self.f_model)
        ft.setWordWrap(True)
        rl.addWidget(ft, 1)
        self.f_table = ft
        self.notes = QLabel()
        self.notes.setObjectName("Muted")
        self.notes.setWordWrap(True)
        rl.addWidget(self.notes)
        bottom.addWidget(right)
        bottom.setSizes([520, 520])
        split.addWidget(bottom)
        if kind == "2A_2B":
            docs = QWidget()
            dl = QVBoxLayout(docs)
            dl.setContentsMargins(0, 0, 0, 0)
            bar = QHBoxLayout()
            bar.addWidget(section("Documents"))
            self.doc_filter = QComboBox()
            self.doc_filter.addItem("Differences only", "diff")
            self.doc_filter.addItem("All documents", "all")
            for s in DOC_STATUSES:
                self.doc_filter.addItem(s, s)
            self.doc_filter.currentIndexChanged.connect(lambda _i: self.show_docs())
            bar.addStretch()
            bar.addWidget(QLabel("Show"))
            bar.addWidget(self.doc_filter)
            dl.addLayout(bar)
            self.doc_model = RowsModel(["Status", "Supplier GSTIN", "Supplier", "Invoice no", "Date", "Type",
                                        "GSTR-2A month", "GSTR-2B month", "Tax in 2A", "Tax in 2B", "Difference",
                                        "Note"],
                                       kinds=["text"] * 8 + ["money"] * 3 + ["text"],
                                       colors=lambda r, c: QColor(GREEN if self.doc_model.rows[r][0] == MATCHED
                                                                  else AMBER) if c == 0 else None)
            self.doc_table = Table()
            self.doc_table.setModel(sortable(self.doc_model))
            dl.addWidget(self.doc_table, 1)
            split.addWidget(docs)
            split.setSizes([260, 220, 300])
        else:
            split.setSizes([300, 300])
        lay.addWidget(split, 1)

    def set_comparison(self, comp) -> None:
        self.comp = comp
        a, b = comp.sides
        self.m_model.headers[2:5] = [a, b, f"Difference ({a} − {b})"]
        self.d_model.headers[1:6] = [f"{a} taxable", f"{a} tax", f"{b} taxable", f"{b} tax", "Difference (tax)"]
        rows = []
        for r in comp.rows:
            d = r.diff
            rows.append([r.label, r.status(a, b), None if r.left is None else r.left.total,
                         None if r.right is None else r.right.total, None if d is None else d.total,
                         *(None if d is None else getattr(d, h) for h in ("igst", "cgst", "sgst", "cess"))])
        self.m_model.set_rows(rows, comp.rows)
        self.m_model.headerDataChanged.emit(Qt.Horizontal, 0, len(self.m_model.headers) - 1)
        self.d_model.headerDataChanged.emit(Qt.Horizontal, 0, len(self.d_model.headers) - 1)
        diff = comp.difference
        both = sum(1 for r in comp.rows if r.left is not None and r.right is not None)
        risk = {"3B_2B": "excess ITC claimed" if diff.total > 1 else "ITC not yet claimed" if diff.total < -1 else "",
                "1_3B": "possible short payment" if diff.total > 1 else "more tax in GSTR-3B" if diff.total < -1
                else "", "2A_2B": ""}[comp.kind]
        self.kpi.setText(f"<b>{comp.title}</b> – {comp.client} ({comp.gstin}), {comp.fy}: {both} month(s) with both "
                         f"returns · {a} <b>₹{fmt_inr(comp.total('left').total)}</b> · {b} "
                         f"<b>₹{fmt_inr(comp.total('right').total)}</b> · difference <b>₹{fmt_inr(diff.total)}</b>"
                         + (f" ({risk})" if risk else "") + f" · {comp.months_with_difference} month(s) differ")
        labels = {r.period: r.label for r in comp.rows}
        self.f_model.set_rows([[labels.get(f.period, f.period), f.text, f.amount] for f in comp.findings],
                              comp.findings)
        self.notes.setText("<br>".join(f"• {n}" for n in comp.notes))
        first = next((i for i, r in enumerate(comp.rows) if r.status(a, b) == "Difference"),
                     next((i for i, r in enumerate(comp.rows) if r.left is not None or r.right is not None), 0))
        self.m_table.selectRow(first)
        self.show_month(first)
        self.m_table.resizeColumnsToContents()
        self.f_table.setColumnWidth(0, 90)
        self.f_table.setColumnWidth(1, 420)
        if self.kind == "2A_2B":
            self.show_docs()

    def show_month(self, row: int) -> None:
        if self.comp is None or not 0 <= row < len(self.comp.rows):
            self.d_model.set_rows([])
            return
        r = self.comp.rows[row]
        self.d_title.setText(f"Breakdown of {r.label}")
        out = []
        for d in self.comp.details_for(r.period):
            diff = d.diff
            out.append([d.label, d.left.taxable if d.left is not None and d.taxable else None,
                        None if d.left is None else d.left.total,
                        d.right.taxable if d.right is not None and d.taxable else None,
                        None if d.right is None else d.right.total, None if diff is None else diff.total])
        self.d_model.set_rows(out)
        self.d_table.setColumnWidth(0, 380)

    def show_docs(self) -> None:
        if self.comp is None:
            return
        f = self.doc_filter.currentData()
        docs = [d for d in self.comp.docs if f == "all" or (f == "diff" and d.status != MATCHED) or d.status == f]
        self.doc_model.set_rows([[d.status, d.gstin, d.name, d.invoice_no, d.invoice_date, d.doc_type, d.period_2a,
                                  d.period_2b, d.itc_2a, d.itc_2b, d.diff, d.note] for d in docs], docs)
        self.doc_table.fit(220)


class ReturnComparePage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.comps, self.avail = state, {}, None
        self.svc = ReturnCompareService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Return comparison", "GSTR-3B vs GSTR-2B, GSTR-1 vs GSTR-3B and GSTR-2A vs GSTR-2B, "
                                                       "month by month, from the returns downloaded from the GST "
                                                       "portal."))
        bar = QHBoxLayout()
        self.import_btn = primary("Import from GST portal…")
        self.import_btn.setToolTip("Pick GSTR-1, GSTR-3B, GSTR-2A and GSTR-2B files downloaded from the portal "
                                   "(JSON, ZIP, Excel, or the filed GSTR-3B PDF) – several at once")
        self.import_btn.clicked.connect(lambda: self.import_dialog())
        self.pick_btn = QPushButton("Pick up from Downloads")
        self.pick_btn.setToolTip("Imports this client's returns saved in the Downloads folder in the last 7 days")
        self.pick_btn.clicked.connect(lambda: self.pick_up())
        portal = QPushButton("Open GST portal")
        portal.clicked.connect(lambda: self.open_portal())
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda: self.export())
        self.status = QLabel()
        self.status.setWordWrap(True)
        for w in (self.import_btn, self.pick_btn, portal):
            bar.addWidget(w)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)
        self.tabs = QTabWidget()
        avail = QWidget()
        al = QVBoxLayout(avail)
        al.setContentsMargins(0, 6, 0, 0)
        how = QLabel(HOW)
        how.setWordWrap(True)
        how.setTextFormat(Qt.RichText)
        al.addWidget(how)
        self.a_model = RowsModel(["Month", *(RETURN_LABELS[k] for k in RETURN_TYPES)],
                                 colors=lambda r, c: (QColor(GREEN if self.a_model.rows[r][c].startswith("✔")
                                                             else GREY) if c else None))
        self.a_table = Table()
        self.a_table.setModel(self.a_model)
        self.a_table.setSortingEnabled(False)
        al.addWidget(self.a_table, 1)
        self.tabs.addTab(avail, "Returns imported")
        self.tabs_by_kind = {}
        for kind, title in KINDS.items():
            t = CompareTab(kind)
            self.tabs_by_kind[kind] = t
            self.tabs.addTab(t, title.split(" (")[0])
        lay.addWidget(self.tabs, 1)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # ------------------------------------------------------------ loading
    def _compute(self, cid: int, fy: str):
        return self.svc.availability(cid, fy), {k: self.svc.compare(k, cid, fy) for k in KINDS}

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy = st.client.id, st.fy
        return lambda: self._compute(cid, fy)

    def reload(self) -> None:
        st = self.state
        enabled = st.client is not None
        for b in (self.import_btn, self.pick_btn, self.export_btn):
            b.setEnabled(enabled)
        if not enabled:
            self.comps, self.avail = {}, None
            self.status.setText("Select a client.")
            self.a_model.set_rows([])
            return
        try:
            self.avail, self.comps = self._compute(st.client.id, st.fy)
        except ServiceError as exc:
            self.status.setText(str(exc))
            return
        rows = []
        for m in self.avail.months:
            label = f"{m[5:]}-{m[:4]}"
            rows.append([label, *(("✔ imported" + (f" ({self.avail.have[k][m]})" if self.avail.have[k][m] else ""))
                                  if self.avail.has(k, m) else "–" for k in RETURN_TYPES)])
        self.a_model.set_rows(rows)
        self.a_table.resizeColumnsToContents()
        for kind, tab in self.tabs_by_kind.items():
            tab.set_comparison(self.comps[kind])
        diffs = {KINDS[k].split(" (")[0]: c.months_with_difference for k, c in self.comps.items()}
        self.status.setText(f"{st.client.name} · {st.fy} · months with a difference: "
                            + ", ".join(f"{k} {v}" for k, v in diffs.items()))

    # ------------------------------------------------------------ imports
    def import_dialog(self) -> None:
        paths = QFileDialog.getOpenFileNames(self, "Returns downloaded from the GST portal", "", PORTAL_FILTER)[0]
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths) -> list:
        st = self.state
        if st.client is None:
            return []
        res = self.svc.import_portal_files(st.client.id, paths, st.user)
        if any(ok for _n, ok, _m in res):
            st.notify()
        lines = [f"{'✔' if ok else '✖'} {name}: {msg}" for name, ok, msg in res]
        saved = sum(1 for _n, ok, _m in res if ok)
        QMessageBox.information(self, "Import from GST portal", f"{saved} of {len(res)} file(s) saved.\n\n"
                                + "\n".join(lines))
        return res

    def pick_up(self, folder: str | Path | None = None) -> list:
        from ...services.portal import default_downloads

        st = self.state
        if st.client is None:
            return []
        folder = Path(folder) if folder else Path(str(st.qsettings.value("portal_downloads", "")) or default_downloads())
        found = self.svc.downloads(st.client.id, folder)
        if not found:
            QMessageBox.information(self, "Pick up from Downloads", f"No new GSTR-1 / 3B / 2A / 2B file of "
                                    f"{st.client.name} in {folder} from the last 7 days.")
            return []
        names = "\n".join(f"• {pf.label} {pf.period or ''} – {pf.path.name}" for pf in found)
        if QMessageBox.question(self, "Pick up from Downloads", f"Import these files for {st.client.name}?\n\n"
                                f"{names}") != QMessageBox.Yes:
            return []
        return self.import_paths([pf.path for pf in found])

    def open_portal(self) -> bool:
        from ...services.portal import RETURNS_DASHBOARD

        online = getattr(self.state, "online", None)
        if online is not None and online.online is False:
            QMessageBox.information(self, "GST portal", "There is no internet connection right now.")
            return False
        return bool(QDesktopServices.openUrl(QUrl(RETURNS_DASHBOARD)))

    def export(self, path: str | None = None, open_file: bool = True):
        if not self.comps:
            return None
        c = next(iter(self.comps.values()))
        path = path or QFileDialog.getSaveFileName(self, "Save return comparison",
                                                   f"Return_comparison_{c.gstin}_{c.fy}.xlsx", "Excel (*.xlsx)")[0]
        if not path:
            return None
        try:
            out = self.svc.export_xlsx(list(self.comps.values()), path)
        except OSError as exc:
            QMessageBox.warning(self, "Return comparison", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out
