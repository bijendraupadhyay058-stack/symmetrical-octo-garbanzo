"""Year on year: the client's figures of the chosen year beside the earlier years – totals, month by month, a chart
and the main suppliers."""
from __future__ import annotations

from PySide6.QtCharts import QLineSeries
from PySide6.QtCore import QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPen
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...core.money import fmt_inr
from ...services.common import ServiceError
from ...services.yoy import LABELS, METRICS, MONTHS, YoyService
from ..state import AppState
from ..widgets import LazyPage, RowsModel, Table, page_header, section, sortable
from .mis import _cat_axis, _chart, _lakh, _tip, _value_axis, _view

#: older years in grey, the year before in orange, the chosen year in blue (the newest year reads first)
YEAR_COLOURS = ["#B8BEC6", "#9AA5B1", "#7D8A99", "#EB6834", "#2A78D6"]
UP, DOWN = "#C8E6C9", "#FFCDD2"
#: a rise is good news for these figures, a fall for the others (ITC at risk, cash paid)
HIGHER_IS_BETTER = {"sales": True, "output_tax": True, "itc_books": True, "itc_2b": True, "itc_claimed": True,
                    "itc_at_risk": False, "cash_paid": False}


class YoyPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state, self.yoy = state, None
        self.svc = YoyService(state.db)
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Year on year", "The client's sales, tax, ITC and suppliers of the chosen year beside "
                                                  "the earlier years."))
        bar = QHBoxLayout()
        self.years = QComboBox()
        for n in (2, 3, 4, 5):
            self.years.addItem(f"{n} years", n)
        self.years.setCurrentIndex(1)
        self.years.currentIndexChanged.connect(lambda _i: self.reload())
        self.metric_cb = QComboBox()
        for k, label in METRICS:
            self.metric_cb.addItem(label, k)
        self.metric_cb.currentIndexChanged.connect(lambda _i: self.show_metric())
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda: self.export())
        self.kpi = QLabel()
        self.kpi.setWordWrap(True)
        self.kpi.setTextFormat(Qt.RichText)
        for w in (QLabel("Compare"), self.years, QLabel("Month by month"), self.metric_cb):
            bar.addWidget(w)
        bar.addWidget(self.kpi, 1)
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)
        split = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(section("Totals of the year"))
        self.s_model = RowsModel(["Figure"], colors=self._summary_colour)
        self.s_table = Table()
        self.s_table.setModel(self.s_model)
        self.s_table.setSortingEnabled(False)
        self.s_table.selectionModel().currentRowChanged.connect(
            lambda cur, _p: cur.isValid() and self.metric_cb.setCurrentIndex(cur.row()))
        ll.addWidget(self.s_table, 1)
        top.addWidget(left)
        self.chart_box = QVBoxLayout()
        cw = QWidget()
        cw.setLayout(self.chart_box)
        self.chart_box.setContentsMargins(0, 0, 0, 0)
        top.addWidget(cw)
        top.setSizes([620, 520])
        split.addWidget(top)
        bottom = QSplitter(Qt.Horizontal)
        mw = QWidget()
        ml = QVBoxLayout(mw)
        ml.setContentsMargins(0, 0, 0, 0)
        self.m_title = section("Month by month")
        ml.addWidget(self.m_title)
        self.m_model = RowsModel(["Month"])
        self.m_table = Table()
        self.m_table.setModel(self.m_model)
        self.m_table.setSortingEnabled(False)
        ml.addWidget(self.m_table, 1)
        bottom.addWidget(mw)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(section("Main suppliers – purchases (taxable value)"))
        self.sup_model = RowsModel(["Supplier"])
        self.sup_table = Table()
        self.sup_table.setModel(sortable(self.sup_model))
        sl.addWidget(self.sup_table, 1)
        bottom.addWidget(sw)
        split.addWidget(bottom)
        lay.addWidget(split, 1)
        self.notes = QLabel()
        self.notes.setObjectName("Muted")
        self.notes.setWordWrap(True)
        lay.addWidget(self.notes)
        for sig in (state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _summary_colour(self, row: int, col: int):
        y = self.yoy
        if y is None or col != len(y.years) + 2:
            return None
        v = self.s_model.rows[row][col - 1]  # the change in rupees decides the colour of the % cell
        if v is None or v == 0:
            return None
        good = (v > 0) == HIGHER_IS_BETTER[METRICS[row][0]]
        return QColor(UP if good else DOWN)

    def warm(self):
        st = self.state
        if st.client is None:
            return None
        cid, fy, n = st.client.id, st.fy, self.years.currentData()
        return lambda: self.svc.build(cid, fy, n)

    def reload(self) -> None:
        st = self.state
        self.export_btn.setEnabled(st.client is not None)
        if st.client is None:
            self.yoy = None
            self.kpi.setText("Select a client.")
            for m in (self.s_model, self.m_model, self.sup_model):
                m.set_rows([])
            return
        try:
            self.yoy = y = self.svc.build(st.client.id, st.fy, self.years.currentData())
        except ServiceError as exc:
            self.kpi.setText(str(exc))
            return
        prev = y.previous
        self.s_model.headers = ["Figure", *y.years, f"Change vs {prev}", "Change %", "Like-for-like %"]
        self.s_model.kinds = ["text"] + ["money"] * (len(y.years) + 1) + ["text", "text"]
        rows = []
        for k, label in METRICS:
            d, p = y.change(k)
            a, b, n = y.like_for_like(k)
            lfl = None
            if a is not None and b:
                lfl = f"{(a - b) * 100 / abs(b):+.1f}% ({n} m)"
            rows.append([label, *(y.total(fy, k) for fy in y.years), d, "" if p is None else f"{p:+.1f}%",
                         lfl or ""])
        self.s_model.set_rows(rows)
        self.s_model.headerDataChanged.emit(Qt.Horizontal, 0, len(self.s_model.headers) - 1)
        self.s_table.resizeColumnsToContents()
        d, p = y.change("sales")
        self.kpi.setText(f"{y.client} · {y.years[0]} to <b>{y.latest}</b>"
                         + (f" · sales {'+' if (p or 0) >= 0 else ''}{p}% vs {prev}" if p is not None else ""))
        self.sup_model.headers = ["Supplier", "GSTIN", *(f"Purchases {fy}" for fy in y.years), "Note"]
        self.sup_model.kinds = ["text", "text"] + ["money"] * len(y.years) + ["text"]
        self.sup_model.set_rows([[s.name, s.gstin, *(s.purchases.get(fy) for fy in y.years), s.status(y.years)]
                                 for s in y.suppliers], y.suppliers)
        self.sup_model.headerDataChanged.emit(Qt.Horizontal, 0, len(self.sup_model.headers) - 1)
        self.sup_table.fit(220)
        self.notes.setText("<br>".join(f"• {n}" for n in y.notes))
        self.show_metric()

    def show_metric(self) -> None:
        y = self.yoy
        if y is None:
            return
        k = self.metric_cb.currentData()
        self.m_title.setText(f"Month by month – {LABELS[k]}")
        self.m_model.headers = ["Month", *y.years] + ([f"Change vs {y.previous}"] if y.previous else [])
        self.m_model.kinds = ["text"] + ["money"] * (len(self.m_model.headers) - 1)
        rows = []
        for i, mon in enumerate(MONTHS):
            vals = [y.month(fy, k, i) for fy in y.years]
            ch = [] if not y.previous else [None if vals[-1] is None or vals[-2] is None else vals[-1] - vals[-2]]
            rows.append([mon, *vals, *ch])
        self.m_model.set_rows(rows)
        self.m_model.headerDataChanged.emit(Qt.Horizontal, 0, len(self.m_model.headers) - 1)
        self.m_table.resizeColumnsToContents()
        self._chart(k)

    def _chart(self, k: str) -> None:
        y = self.yoy
        while self.chart_box.count():
            w = self.chart_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        ch = _chart(f"{LABELS[k]} by month (₹ lakh)")
        ax = _cat_axis(list(MONTHS))
        ch.addAxis(ax, Qt.AlignBottom)
        series_vals = {fy: [y.month(fy, k, i) for i in range(12)] for fy in y.years}
        ay = _value_axis([_lakh(v) for vals in series_vals.values() for v in vals if v is not None])
        ch.addAxis(ay, Qt.AlignLeft)
        colours = YEAR_COLOURS[-len(y.years):]
        for fy, colour in zip(y.years, colours):
            s = QLineSeries()
            s.setName(fy)
            pen = QPen(QColor(colour))
            pen.setWidth(3 if fy == y.latest else 2)
            s.setPen(pen)
            s.setPointsVisible(True)
            vals = series_vals[fy]
            for i, v in enumerate(vals):
                if v is not None:
                    s.append(QPointF(i, _lakh(v)))
            s.hovered.connect(lambda p, on, f=fy, d=vals: on and 0 <= round(p.x()) < 12 and _tip(
                f"{f} – {MONTHS[round(p.x())]}: ₹{fmt_inr(d[round(p.x())] or 0)}"))
            ch.addSeries(s)
            s.attachAxis(ax)
            s.attachAxis(ay)
        self.chart = _view(ch)
        self.chart_box.addWidget(self.chart)

    def export(self, path: str | None = None, open_file: bool = True):
        if self.yoy is None:
            return None
        y = self.yoy
        path = path or QFileDialog.getSaveFileName(self, "Save year-on-year comparison",
                                                   f"Year_on_year_{y.gstin}_{y.years[0]}_{y.latest}.xlsx",
                                                   "Excel (*.xlsx)")[0]
        if not path:
            return None
        try:
            out = self.svc.export_xlsx(y, path)
        except OSError as exc:
            QMessageBox.warning(self, "Year on year", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out
