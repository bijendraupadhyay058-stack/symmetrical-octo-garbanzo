"""Reusable widgets and table models."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy, QTableView,
    QVBoxLayout, QWidget,
)

from ..core.models import Category, ReconLine
from ..engine.summary import itc_at_risk
from .theme import CATEGORY_SHORT, category_color, money

SORT_ROLE = Qt.UserRole + 1
OBJECT_ROLE = Qt.UserRole + 2


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        self.title = QLabel(title)
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)


def page_header(title: str, subtitle: str = "") -> PageHeader:
    return PageHeader(title, subtitle)


def section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("SectionTitle")
    return lbl


def card(layout_cls=QVBoxLayout) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    lay = layout_cls(frame)
    lay.setContentsMargins(14, 12, 14, 12)
    return frame, lay


def primary(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Primary")
    return b


class LazyPage(QWidget):
    """Page that refreshes only while visible; hidden pages refresh when next shown."""

    def lazy(self, fn):
        def slot(*_args):
            if self.isVisible():
                fn()
            else:
                self._pending = fn
        return slot

    def showEvent(self, event):
        super().showEvent(event)
        fn = getattr(self, "_pending", None)
        if fn is not None:
            self._pending = None
            fn()


class KpiCard(QFrame):
    def __init__(self, title: str, accent: str = "#00897B"):
        super().__init__()
        self.setObjectName("KpiCard")
        self.setStyleSheet(f"QFrame#KpiCard {{ border-left: 5px solid {accent}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("KpiTitle")
        self.value = QLabel("–")
        self.value.setObjectName("KpiValue")
        self.sub = QLabel("")
        self.sub.setObjectName("KpiSub")
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)


class Table(QTableView):
    def __init__(self, parent=None, stretch_last: bool = True):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        self.horizontalHeader().setStretchLastSection(stretch_last)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setResizeContentsPrecision(150)  # size columns from a sample, not 50k rows
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setWordWrap(False)

    def fit(self, max_width: int = 260) -> None:
        self.resizeColumnsToContents()
        for c in range(self.model().columnCount() if self.model() else 0):
            if self.columnWidth(c) > max_width:
                self.setColumnWidth(c, max_width)


class RowsModel(QAbstractTableModel):
    """Generic read-only model over a list of row tuples. ``kinds`` drive alignment and formatting."""

    def __init__(self, headers: Sequence[str], rows: list[Sequence] | None = None, kinds: Sequence[str] = (),
                 payload: list | None = None, colors: Callable[[int, int], QColor | None] | None = None):
        super().__init__()
        self.headers = list(headers)
        self.rows = rows or []
        self.kinds = list(kinds) or ["text"] * len(headers)
        self.payload = payload
        self.colors = colors

    def set_rows(self, rows: list[Sequence], payload: list | None = None) -> None:
        self.beginResetModel()
        self.rows = rows
        self.payload = payload
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        v = self.rows[index.row()][index.column()]
        kind = self.kinds[index.column()]
        if role == Qt.DisplayRole:
            if v is None:
                return ""
            if kind == "money":
                return money(v)
            if isinstance(v, date):
                return v.strftime("%d-%m-%Y")
            return str(v)
        if role == SORT_ROLE:
            if v is None:
                return -1e18 if kind in ("money", "int") else ""
            return float(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, date) else v)
        if role == Qt.TextAlignmentRole and kind in ("money", "int"):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and kind == "money" and isinstance(v, Decimal) and v < 0:
            return QColor("#C62828")
        if role == Qt.BackgroundRole and self.colors:
            return self.colors(index.row(), index.column())
        if role == OBJECT_ROLE and self.payload is not None:
            return self.payload[index.row()]
        return None


def sortable(model: QAbstractTableModel) -> QSortFilterProxyModel:
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setSortRole(SORT_ROLE)
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    return proxy


# ---------------------------------------------------------------- lines model
LINE_HEADERS = ["Line", "Category", "Status", "Supplier GSTIN", "Supplier", "Type", "Books Inv No", "2B Inv No",
                "Books Date", "2B Date", "Books ITC", "2B ITC", "ITC Diff", "ITC at Risk", "Conf.", "Assigned",
                "Evidence"]
LINE_KINDS = ["int", "cat", "text", "text", "text", "text", "text", "text", "date", "date", "money", "money",
              "money", "money", "int", "text", "int"]


def line_row(ln: ReconLine, evidence: int = 0) -> list:
    b, g = ln.books, ln.gstr2b
    return [ln.line_no, ln.category.value, ln.status.value, ln.supplier_gstin, ln.supplier_name, ln.doc_type.label,
            b.invoice_no if b else None, g.invoice_no if g else None, b.invoice_date if b else None,
            g.invoice_date if g else None, b.signed("itc") if b else None, g.signed("itc") if g else None,
            ln.diff("itc"), itc_at_risk(ln), ln.confidence, ln.assigned_to, evidence or None]


class LinesModel(RowsModel):
    def __init__(self):
        super().__init__(LINE_HEADERS, [], [k if k != "cat" else "text" for k in LINE_KINDS])
        self.lines: list[ReconLine] = []

    def set_lines(self, lines: list[ReconLine], evidence: dict[int, int] | None = None) -> None:
        evidence = evidence or {}
        self.lines = lines
        self.set_rows([line_row(ln, evidence.get(ln.line_no, 0)) for ln in lines], payload=lines)

    def update_line(self, ln: ReconLine) -> None:
        for i, existing in enumerate(self.lines):
            if existing.line_no == ln.line_no:
                evidence = self.rows[i][-1] or 0
                self.rows[i] = line_row(ln, evidence)
                self.dataChanged.emit(self.index(i, 0), self.index(i, self.columnCount() - 1))
                return

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.BackgroundRole and index.isValid() and index.column() == 1:
            return category_color(self.lines[index.row()].category)
        return super().data(index, role)


class LinesFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setSortRole(SORT_ROLE)
        self.categories: set[Category] | None = None
        self.status: str | None = None
        self.pending_only = False
        self.gstin: str | None = None
        self.text = ""

    def refresh(self) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.10+
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # pragma: no cover - older Qt
            self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:
        model: LinesModel = self.sourceModel()
        ln = model.lines[row]
        if self.categories is not None and ln.category not in self.categories:
            return False
        if self.status and ln.status.value != self.status:
            return False
        if self.pending_only and ln.status.value in ("No Action Required", "Resolved", "Closed After Review"):
            return False
        if self.gstin and not ((ln.books and ln.books.supplier_gstin == self.gstin)
                               or (ln.gstr2b and ln.gstr2b.supplier_gstin == self.gstin)):
            return False
        if self.text:
            hay = " ".join(str(v) for v in model.rows[row] if v is not None).lower()
            if self.text.lower() not in hay and self.text.lower() not in " ".join(ln.reasons).lower():
                return False
        return True


class CategoryChips(QWidget):
    """Colour-coded, toggleable category filter chips with counts."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        self.buttons: dict[Category, QPushButton] = {}
        self.all_btn = QPushButton("All")
        self.all_btn.setObjectName("Chip")
        self.all_btn.clicked.connect(self.select_all)
        self.lay.addWidget(self.all_btn)

    def set_counts(self, counts: dict[Category, int]) -> None:
        for btn in self.buttons.values():
            btn.deleteLater()
        self.buttons.clear()
        for cat in Category:
            n = counts.get(cat, 0)
            if not n:
                continue
            b = QPushButton(f"{CATEGORY_SHORT[cat]} {n}")
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setToolTip(cat.value)
            b.setStyleSheet(f"QPushButton#Chip {{ background: {category_color(cat).name()}; }}")
            b.toggled.connect(lambda _c: self.changed.emit())
            self.buttons[cat] = b
            self.lay.insertWidget(self.lay.count(), b)

    def select_all(self) -> None:
        for b in self.buttons.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self.changed.emit()

    def selected(self) -> set[Category] | None:
        chosen = {c for c, b in self.buttons.items() if b.isChecked()}
        return chosen or None

    def choose(self, cats: set[Category]) -> None:
        for c, b in self.buttons.items():
            b.blockSignals(True)
            b.setChecked(c in cats)
            b.blockSignals(False)
        self.changed.emit()
