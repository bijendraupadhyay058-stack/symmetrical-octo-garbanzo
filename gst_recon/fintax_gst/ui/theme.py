"""FIN TAX PRO visual identity: navy, white and teal."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtGui import QColor

from ..core.models import PARTIAL_CATEGORIES, Category
from ..core.money import fmt_inr

NAVY = "#1F3864"
NAVY_DARK = "#152847"
NAVY_LIGHT = "#2E4E87"
TEAL = "#00897B"
TEAL_LIGHT = "#E0F2F1"
BG = "#F4F7FB"
TEXT = "#1B2A41"
MUTED = "#5C6B80"
BORDER = "#D5DEEA"
RED = "#C62828"
AMBER = "#EF8F00"
GREEN = "#2E7D32"

CATEGORY_COLORS = {
    Category.FULLY_MATCHED: "#C8E6C9", Category.MANUALLY_MATCHED: "#B2DFDB",
    Category.MISSING_IN_2B: "#FFCDD2", Category.MISSING_IN_BOOKS: "#F8BBD0",
    Category.DUPLICATE_IN_BOOKS: "#E1BEE7", Category.DUPLICATE_IN_2B: "#E1BEE7",
    Category.PROBABLE: "#BBDEFB", Category.PREVIOUS_PERIOD: "#D7CCC8",
    Category.PENDING_CLARIFICATION: "#CFD8DC",
}
for _c in PARTIAL_CATEGORIES:
    CATEGORY_COLORS.setdefault(_c, "#FFF3C4")

#: Short labels for filter chips.
CATEGORY_SHORT = {
    Category.FULLY_MATCHED: "Fully matched", Category.DATE_DIFFERENCE: "Date diff",
    Category.NUMBER_VARIATION: "Inv. no. variation", Category.TAXABLE_DIFFERENCE: "Taxable diff",
    Category.IGST_DIFFERENCE: "IGST diff", Category.CGST_SGST_DIFFERENCE: "CGST/SGST diff",
    Category.CESS_DIFFERENCE: "Cess diff", Category.MULTIPLE_DIFFERENCES: "Multiple diffs",
    Category.MISSING_IN_2B: "Missing in 2B", Category.MISSING_IN_BOOKS: "Missing in books",
    Category.DUPLICATE_IN_BOOKS: "Dup. in books", Category.DUPLICATE_IN_2B: "Dup. in 2B",
    Category.PREVIOUS_PERIOD: "Previous period", Category.CDN_DIFFERENCE: "CN/DN diff",
    Category.AMENDED: "Amended", Category.PROBABLE: "Probable", Category.MANUALLY_MATCHED: "Manual",
    Category.PENDING_CLARIFICATION: "Clarification",
}


def category_color(cat: Category) -> QColor:
    return QColor(CATEGORY_COLORS.get(cat, "#FFFFFF"))


def money(v: Decimal | None, symbol: bool = False) -> str:
    if v is None:
        return ""
    return ("₹ " if symbol else "") + fmt_inr(v)


STYLESHEET = f"""
* {{ font-family: "Segoe UI", "Inter", "DejaVu Sans", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#Page {{ background: {BG}; }}
QWidget#Header {{ background: {NAVY}; }}
QLabel#Brand {{ color: white; font-size: 17pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#Tagline {{ color: #B3D4F5; font-size: 9pt; }}
QLabel#HeaderLabel {{ color: #D6E4F5; font-size: 9pt; }}
QWidget#Header QComboBox {{ background: {NAVY_LIGHT}; color: white; border: 1px solid #4C6CA3;
    border-radius: 6px; padding: 4px 10px; min-width: 120px; }}
QWidget#Header QComboBox QAbstractItemView {{ background: white; color: {TEXT}; }}
QListWidget#Nav {{ background: {NAVY_DARK}; border: none; padding-top: 8px; outline: 0; }}
QListWidget#Nav::item {{ color: #C9D6EA; padding: 11px 16px; border-left: 4px solid transparent; }}
QListWidget#Nav::item:selected {{ background: {NAVY}; color: white; border-left: 4px solid {TEAL}; }}
QListWidget#Nav::item:hover {{ background: #1C355E; }}
QLabel#PageTitle {{ font-size: 16pt; font-weight: 700; color: {NAVY}; }}
QLabel#PageSubtitle {{ color: {MUTED}; }}
QLabel#SectionTitle {{ font-size: 11pt; font-weight: 700; color: {NAVY}; padding-top: 6px; }}
QFrame#Card {{ background: white; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#KpiCard {{ background: white; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#KpiTitle {{ color: {MUTED}; font-size: 9pt; }}
QLabel#KpiValue {{ font-size: 17pt; font-weight: 700; color: {NAVY}; }}
QLabel#KpiSub {{ color: {MUTED}; font-size: 8.5pt; }}
QLabel#StepBadge {{ background: {NAVY}; color: white; border-radius: 14px; font-weight: 700;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; qproperty-alignment: AlignCenter; }}
QLabel#StepBadgeDone {{ background: {TEAL}; color: white; border-radius: 14px; font-weight: 700;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; qproperty-alignment: AlignCenter; }}
QLabel#StepTitle {{ font-size: 11pt; font-weight: 700; color: {NAVY}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Warn {{ color: {AMBER}; }}
QLabel#Error {{ color: {RED}; }}
QLabel#Ok {{ color: {GREEN}; font-weight: 600; }}
QPushButton {{ background: white; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {TEAL}; }}
QPushButton:disabled {{ color: #9AA7B8; background: #EEF2F7; }}
QPushButton#Primary {{ background: {TEAL}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #00796B; }}
QPushButton#Primary:disabled {{ background: #9CCFC9; }}
QPushButton#Danger {{ color: {RED}; }}
QPushButton#Chip {{ border-radius: 12px; padding: 3px 10px; font-size: 9pt; }}
QPushButton#Chip:checked {{ border: 2px solid {NAVY}; font-weight: 600; }}
QTableView {{ background: white; border: 1px solid {BORDER}; border-radius: 6px; gridline-color: #EDF1F6;
    selection-background-color: #CFE3F7; selection-color: {TEXT}; alternate-background-color: #FAFCFE; }}
QHeaderView::section {{ background: {NAVY}; color: white; padding: 5px; border: none;
    border-right: 1px solid {NAVY_LIGHT}; font-weight: 600; }}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: white;
    border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 6px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {TEAL}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; background: white; }}
QTabBar::tab {{ padding: 6px 14px; background: #E8EEF6; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabBar::tab:selected {{ background: white; color: {NAVY}; font-weight: 600; }}
QProgressBar {{ border: 1px solid {BORDER}; border-radius: 6px; text-align: center; background: white; height: 18px; }}
QProgressBar::chunk {{ background: {TEAL}; border-radius: 5px; }}
QStatusBar {{ background: white; border-top: 1px solid {BORDER}; }}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: {BORDER}; }}
"""
