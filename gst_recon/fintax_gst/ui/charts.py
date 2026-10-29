"""Dashboard charts (Qt Charts). Every value comes from reconciliation lines."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QHorizontalBarSeries, QPieSeries, QValueAxis,
)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QFont, QPainter

from ..core.models import Category
from .theme import CATEGORY_SHORT, NAVY, TEAL

PALETTE = ["#1F3864", "#00897B", "#EF6C00", "#C62828", "#6A1B9A", "#0277BD", "#9E9D24", "#5D4037", "#AD1457",
           "#455A64"]


def _chart(title: str) -> QChart:
    ch = QChart()
    ch.setTitle(title)
    f = QFont()
    f.setPointSize(10)
    f.setBold(True)
    ch.setTitleFont(f)
    ch.setTitleBrush(QColor(NAVY))
    ch.setBackgroundRoundness(10)
    ch.setMargins(QMargins(6, 6, 6, 6))
    ch.setAnimationOptions(QChart.NoAnimation)
    ch.legend().setAlignment(Qt.AlignBottom)
    return ch


def _view(chart: QChart) -> QChartView:
    v = QChartView(chart)
    v.setRenderHint(QPainter.Antialiasing)
    v.setMinimumHeight(250)
    return v


def _lakh(v: Decimal) -> float:
    return float(v) / 100000.0


def monthly_itc(months: list[tuple[str, Decimal, Decimal]]) -> QChartView:
    """[(month, books ITC, GSTR-2B ITC)] in ₹ lakh."""
    ch = _chart("Monthly ITC – Books vs GSTR-2B (₹ lakh)")
    books, g2b = QBarSet("Books"), QBarSet("GSTR-2B")
    books.setColor(QColor(NAVY))
    g2b.setColor(QColor(TEAL))
    for _m, b, g in months:
        books.append(_lakh(b))
        g2b.append(_lakh(g))
    series = QBarSeries()
    series.append(books)
    series.append(g2b)
    ch.addSeries(series)
    ax = QBarCategoryAxis()
    ax.append([m for m, *_ in months] or ["–"])
    ch.addAxis(ax, Qt.AlignBottom)
    series.attachAxis(ax)
    ay = QValueAxis()
    ay.setLabelFormat("%.1f")
    hi = max([_lakh(x) for _m, b, g in months for x in (b, g)] + [1.0])
    ay.setRange(min(0.0, min([_lakh(x) for _m, b, g in months for x in (b, g)] + [0.0])), hi * 1.15)
    ch.addAxis(ay, Qt.AlignLeft)
    series.attachAxis(ay)
    return _view(ch)


def match_donut(paired: int, probable: int, unmatched: int) -> QChartView:
    total = paired + probable + unmatched
    pct = (paired * 100 / total) if total else 0
    ch = _chart(f"Matching – {pct:.1f}% of lines paired")
    s = QPieSeries()
    s.setHoleSize(0.5)
    for label, n, color in (("Paired", paired, TEAL), ("Probable / review", probable, "#64B5F6"),
                            ("Unmatched", unmatched, "#E57373")):
        if n:
            sl = s.append(f"{label} ({n})", n)
            sl.setColor(QColor(color))
    ch.addSeries(s)
    return _view(ch)


def vendor_mismatch(rows: list[tuple[str, Decimal]]) -> QChartView:
    """Top suppliers by absolute ITC difference: [(name, difference)]."""
    ch = _chart("Top suppliers by ITC difference (₹)")
    bs = QBarSet("ITC difference")
    bs.setColor(QColor("#EF6C00"))
    names = []
    for name, diff in reversed(rows):
        bs.append(float(diff))
        names.append(name[:22] or "–")
    series = QHorizontalBarSeries()
    series.append(bs)
    ch.addSeries(series)
    ay = QBarCategoryAxis()
    ay.append(names or ["–"])
    ch.addAxis(ay, Qt.AlignLeft)
    series.attachAxis(ay)
    ax = QValueAxis()
    ax.setLabelFormat("%.0f")
    vals = [float(d) for _n, d in rows] or [0.0]
    lo, hi = min(vals + [0.0]), max(vals + [1.0])
    ax.setRange(lo * 1.1, hi * 1.1)
    ch.addAxis(ax, Qt.AlignBottom)
    series.attachAxis(ax)
    ch.legend().setVisible(False)
    return _view(ch)


def exposure_pie(by_category: list[tuple[Category, Decimal]]) -> QChartView:
    ch = _chart("Potential ITC at risk by category")
    s = QPieSeries()
    for i, (cat, amount) in enumerate(by_category):
        if amount > 0:
            sl = s.append(f"{CATEGORY_SHORT[cat]} ₹{float(amount):,.0f}", float(amount))
            sl.setColor(QColor(PALETTE[i % len(PALETTE)]))
    if not s.count():
        s.append("No exposure", 1).setColor(QColor("#C8E6C9"))
    ch.addSeries(s)
    ch.legend().setAlignment(Qt.AlignRight)
    return _view(ch)
