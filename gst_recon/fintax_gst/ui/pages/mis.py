"""Charts & MIS: the client's year in four charts, and the MIS pack for its management (PDF / Excel / e-mail)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QHorizontalBarSeries, QLineSeries, QValueAxis,
)
from PySide6.QtCore import QMargins, QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QToolTip, QVBoxLayout,
)

from ...core.money import fmt_inr
from ...services.common import ServiceError
from ..state import AppState
from ..widgets import LazyPage, page_header, primary

SERIES = ["#2A78D6", "#EB6834", "#1BAF7A"]  # validated categorical order; at most three series per chart
INK, MUTED, GRID = "#0B0B0B", "#52514E", "#E3E2DE"


def _lakh(v) -> float:
    return 0.0 if v is None else float(v) / 100000.0


def _chart(title: str) -> QChart:
    ch = QChart()
    ch.setTitle(title)
    f = QFont()
    f.setPointSize(10)
    f.setBold(True)
    ch.setTitleFont(f)
    ch.setTitleBrush(QColor(INK))
    ch.setMargins(QMargins(4, 4, 4, 4))
    ch.setAnimationOptions(QChart.NoAnimation)
    ch.legend().setAlignment(Qt.AlignBottom)
    ch.legend().setLabelColor(QColor(INK))
    return ch


def _value_axis(values: list[float], fmt: str = "%.1f") -> QValueAxis:
    ay = QValueAxis()
    hi = max(values + [0.0])
    lo = min(values + [0.0])
    ay.setRange(lo * 1.1 if lo < 0 else 0.0, hi * 1.15 if hi > 0 else 1.0)
    ay.setLabelFormat(fmt)
    ay.setTickCount(5)
    ay.applyNiceNumbers()  # round steps (0, 2,500, 5,000 …)
    ay.setGridLineColor(QColor(GRID))
    ay.setLabelsColor(QColor(MUTED))
    ay.setLinePenColor(QColor(GRID))
    return ay


def _cat_axis(labels: list[str]) -> QBarCategoryAxis:
    ax = QBarCategoryAxis()
    ax.append(labels or ["–"])
    ax.setLabelsColor(QColor(MUTED))
    ax.setGridLineVisible(False)
    ax.setLinePenColor(QColor(GRID))
    return ax


def _view(ch: QChart) -> QChartView:
    v = QChartView(ch)
    v.setRenderHint(QPainter.Antialiasing)
    v.setMinimumHeight(240)
    return v


def _tip(text: str) -> None:
    QToolTip.showText(QCursor.pos(), text)


def itc_chart(labels, books, g2b, claimed) -> QChartView:
    ch = _chart("ITC by month (₹ lakh)")
    ax = _cat_axis(labels)
    ch.addAxis(ax, Qt.AlignBottom)
    vals = [_lakh(v) for s in (books, g2b, claimed) for v in s]
    ay = _value_axis(vals)
    ch.addAxis(ay, Qt.AlignLeft)
    for (name, data), colour in zip((("As per books", books), ("GSTR-2B", g2b), ("Claimed in GSTR-3B", claimed)),
                                    SERIES):
        s = QLineSeries()
        s.setName(name)
        pen = QPen(QColor(colour))
        pen.setWidth(2)
        s.setPen(pen)
        s.setPointsVisible(True)
        for i, v in enumerate(data):
            if v is not None:
                s.append(QPointF(i, _lakh(v)))
        s.hovered.connect(lambda p, on, n=name, d=data: on and 0 <= round(p.x()) < len(d) and _tip(
            f"{n} – {labels[round(p.x())]}: ₹{fmt_inr(d[round(p.x())] or 0)}"))
        ch.addSeries(s)
        s.attachAxis(ay)
        s.attachAxis(ax)
    return _view(ch)


def month_bars(title: str, labels, data, name: str) -> QChartView:
    ch = _chart(title if any(data) else f"{title} – none in these months")
    bs = QBarSet(name)
    bs.setColor(QColor(SERIES[0]))
    bs.setBorderColor(QColor(SERIES[0]))
    for v in data:
        bs.append(_lakh(v))
    bs.hovered.connect(lambda on, i: on and _tip(f"{labels[i]}: ₹{fmt_inr(data[i] or 0)}"))
    s = QBarSeries()
    s.append(bs)
    s.setBarWidth(0.6 * min(1.0, len(data) / 6))  # few months: thin bars, not one wide block
    ch.addSeries(s)
    ax, ay = _cat_axis(labels), _value_axis([_lakh(v) for v in data])
    ch.addAxis(ax, Qt.AlignBottom)
    ch.addAxis(ay, Qt.AlignLeft)
    s.attachAxis(ax)
    s.attachAxis(ay)
    ch.legend().setVisible(False)  # one series: the title names it
    return _view(ch)


def supplier_bars(rows) -> QChartView:
    ch = _chart("Suppliers with the most ITC at risk (₹)")
    bs = QBarSet("ITC at risk")
    bs.setColor(QColor(SERIES[0]))
    bs.setBorderColor(QColor(SERIES[0]))
    ordered = list(reversed(rows))
    for _n, _g, amount, _d in ordered:
        bs.append(float(amount))
    bs.hovered.connect(lambda on, i: on and _tip(
        f"{ordered[i][0]} ({ordered[i][1]}): ₹{fmt_inr(ordered[i][2])} · {ordered[i][3]} document(s) not in GSTR-2B"))
    s = QHorizontalBarSeries()
    s.append(bs)
    s.setBarWidth(0.55 * min(1.0, len(rows) / 6))
    ch.addSeries(s)
    ay = _cat_axis([n[:26] for n, *_ in ordered])
    ax = _value_axis([float(a) for _n, _g, a, _d in rows], "%.0f")
    ch.addAxis(ay, Qt.AlignLeft)
    ch.addAxis(ax, Qt.AlignBottom)
    s.attachAxis(ay)
    s.attachAxis(ax)
    ch.legend().setVisible(False)
    return _view(ch)


class MisPage(LazyPage):
    navigate = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.mis = None
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.addWidget(page_header("Charts & MIS", "The client's financial year at a glance, and an MIS pack for its "
                                                  "management – PDF, Excel or e-mail."))
        bar = QHBoxLayout()
        self.kpi = QLabel()
        self.kpi.setWordWrap(True)
        self.pdf_btn = primary("MIS pack (PDF)…")
        self.pdf_btn.clicked.connect(lambda: self.export("pdf"))
        self.xlsx_btn = QPushButton("MIS pack (Excel)…")
        self.xlsx_btn.clicked.connect(lambda: self.export("xlsx"))
        self.mail_btn = QPushButton("E-mail to client…")
        self.mail_btn.setToolTip("Puts the MIS pack (PDF) in the Outbox as an e-mail to the client")
        self.mail_btn.clicked.connect(lambda: self.email())
        bar.addWidget(self.kpi, 1)
        for b in (self.pdf_btn, self.xlsx_btn, self.mail_btn):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.grid = QGridLayout()
        lay.addLayout(self.grid, 1)
        self.notes = QLabel()
        self.notes.setObjectName("Muted")
        self.notes.setWordWrap(True)
        lay.addWidget(self.notes)
        for sig in (state.dataChanged, state.clientChanged, state.runChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    def _clear(self) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def reload(self) -> None:
        from ...services.mis import MisService

        self._clear()
        st = self.state
        if st.client is None:
            self.mis = None
            self.kpi.setText("Select a client.")
            for b in (self.pdf_btn, self.xlsx_btn, self.mail_btn):
                b.setEnabled(False)
            return
        try:
            self.mis = mis = MisService(st.db).build(st.client.id, st.fy)
        except ServiceError as exc:
            self.kpi.setText(str(exc))
            return
        rows = mis.active
        self.kpi.setText(" · ".join(f"{k} <b>₹{fmt_inr(mis.total(a))}</b>" for k, a in (
            ("Sales", "sales"), ("Output tax", "output_tax"), ("ITC claimed", "itc_claimed"), ("Cash paid", "cash_paid"),
            ("ITC at risk", "itc_at_risk"))) + f" · {st.fy}")
        for b in (self.pdf_btn, self.xlsx_btn, self.mail_btn):
            b.setEnabled(True)
        if not rows:
            msg = QLabel("No GST data imported for this year yet – the charts appear once registers or returns are "
                         "imported.")
            self.grid.addWidget(msg, 0, 0)
            self.charts = []
        else:
            labels = [m.label for m in rows]
            self.charts = [
                itc_chart(labels, [m.itc_books for m in rows], [m.itc_2b for m in rows], [m.itc_claimed for m in rows]),
                month_bars("Sales by month (₹ lakh)", labels, [m.sales for m in rows], "Sales"),
                month_bars("Cash paid by month (₹ lakh)", labels, [m.cash_paid for m in rows], "Cash paid"),
            ]
            if mis.suppliers:
                self.charts.append(supplier_bars(mis.suppliers))
            for i, v in enumerate(self.charts):
                self.grid.addWidget(v, i // 2, i % 2)
        self.notes.setText("<br>".join(f"• {n}" for n in mis.notes))

    def export(self, kind: str, path: str | None = None, open_file: bool = True):
        from ...services.mis import MisService

        if self.mis is None:
            return None
        name = f"GST_MIS_{self.mis.gstin}_{self.mis.fy}.{kind}"
        path = path or QFileDialog.getSaveFileName(self, "Save MIS pack", name,
                                                   "PDF (*.pdf)" if kind == "pdf" else "Excel (*.xlsx)")[0]
        if not path:
            return None
        svc = MisService(self.state.db)
        firm = str(self.state.qsettings.value("reminder_signature", "")).strip()
        try:
            out = svc.export_pdf(self.mis, path, firm) if kind == "pdf" else svc.export_xlsx(self.mis, path)
        except OSError as exc:
            QMessageBox.warning(self, "MIS pack", f"Could not save: {exc}")
            return None
        if open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        return out

    def email(self, go: bool = True):
        from ...services.mailer import MailService
        from ...services.mis import MisService

        if self.mis is None:
            return None
        st = self.state
        folder = Path(st.db.data_dir) / "outbox"
        folder.mkdir(parents=True, exist_ok=True)
        firm = str(st.qsettings.value("reminder_signature", "")).strip()
        pdf = MisService(st.db).export_pdf(self.mis, folder / f"GST_MIS_{self.mis.gstin}_{self.mis.fy}.pdf", firm)
        c = st.clients.get(st.client.id)
        body = (f"Dear {c.contact_person or 'Sir/Madam'},\n\nPlease find attached the GST MIS of {c.name} for "
                f"{self.mis.fy}.\n\nRegards,\n{firm}").rstrip()
        m = MailService(st.db).add_draft("client_report", c.email or "", f"GST MIS {self.mis.fy} – {c.name}", body,
                                         [pdf], c.id, self.mis.fy, user=st.user)
        st.notify()
        QMessageBox.information(self, "MIS pack", "The MIS pack is in the Outbox as an e-mail to the client – check "
                                "and send it there." + ("" if m.to_addr else "\nThe client has no e-mail address yet."))
        if go and hasattr(self.window(), "go"):
            self.window().go("outbox")
        return m
