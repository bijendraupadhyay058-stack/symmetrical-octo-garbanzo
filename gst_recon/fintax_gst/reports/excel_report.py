"""Audit-ready Excel workbook (17 sheets) built from a saved reconciliation run.

Written in openpyxl write-only mode so 50,000+ lines stay within modest memory.
All amounts are written as exact Decimals. Every detail sheet is an Excel
table (filter/sort, pivot-ready) with frozen headers and SUBTOTAL totals that
follow filters. The executive summary carries formula cross-checks against
the Complete Reconciliation sheet so totals can be verified inside Excel.
"""
from __future__ import annotations

import json
import re
import warnings
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, NamedStyle, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableColumn, TableStyleInfo

from .. import PRODUCT_FULL_NAME, TAGLINE, __version__
from ..core.models import (
    PARTIAL_CATEGORIES, Category, DocType, ExceptionStatus, Flag, ReconLine, relabel, side_labels,
)
from ..core.money import ZERO
from ..engine.summary import (
    DASHBOARD_LABELS, SUGGESTED_ACTIONS, category_summary, current_books, dashboard, is_pending, itc_at_risk,
    month_summary, side_totals, supplier_summary,
)

NAVY, TEAL, WHITE = "1F3864", "00897B", "FFFFFF"
MONEY_FMT = "#,##0.00;[Red]-#,##0.00"
DATE_FMT = "DD-MM-YYYY"

CATEGORY_COLORS = {
    Category.FULLY_MATCHED: "C8E6C9", Category.MANUALLY_MATCHED: "C8E6C9",
    Category.MISSING_IN_2B: "FFCDD2", Category.MISSING_IN_BOOKS: "F8BBD0",
    Category.DUPLICATE_IN_BOOKS: "E1BEE7", Category.DUPLICATE_IN_2B: "E1BEE7",
    Category.PROBABLE: "BBDEFB", Category.PREVIOUS_PERIOD: "D7CCC8", Category.PENDING_CLARIFICATION: "CFD8DC",
}
for _c in PARTIAL_CATEGORIES:
    CATEGORY_COLORS.setdefault(_c, "FFF3C4")


def _thin():
    s = Side(style="thin", color="B0BEC5")
    return Border(left=s, right=s, top=s, bottom=s)


def _register_styles(wb: Workbook) -> None:
    styles = [
        NamedStyle("ftp_title", font=Font(name="Calibri", size=16, bold=True, color=WHITE),
                   fill=PatternFill("solid", fgColor=NAVY), alignment=Alignment(vertical="center")),
        NamedStyle("ftp_subtitle", font=Font(name="Calibri", size=10, italic=True, color=WHITE),
                   fill=PatternFill("solid", fgColor=TEAL)),
        NamedStyle("ftp_header", font=Font(bold=True, color=WHITE), fill=PatternFill("solid", fgColor=NAVY),
                   alignment=Alignment(wrap_text=True, vertical="center", horizontal="center"), border=_thin()),
        NamedStyle("ftp_label", font=Font(bold=True, color=NAVY)),
        NamedStyle("ftp_money", number_format=MONEY_FMT),
        NamedStyle("ftp_money_bold", number_format=MONEY_FMT, font=Font(bold=True),
                   fill=PatternFill("solid", fgColor="E0F2F1"), border=_thin()),
        NamedStyle("ftp_total_label", font=Font(bold=True), fill=PatternFill("solid", fgColor="E0F2F1"),
                   border=_thin()),
        NamedStyle("ftp_date", number_format=DATE_FMT),
        NamedStyle("ftp_wrap", alignment=Alignment(wrap_text=True, vertical="top")),
        NamedStyle("ftp_note", font=Font(italic=True, color="455A64"), alignment=Alignment(wrap_text=True)),
        NamedStyle("ftp_input", number_format=MONEY_FMT, fill=PatternFill("solid", fgColor="FFF9C4"),
                   border=_thin()),
        NamedStyle("ftp_ok", font=Font(bold=True, color="2E7D32")),
    ]
    for color in sorted(set(CATEGORY_COLORS.values())):
        styles.append(NamedStyle(f"ftp_cat_{color}", fill=PatternFill("solid", fgColor=color)))
    for st in styles:
        wb.add_named_style(st)


class _Sheet:
    def __init__(self, wb: Workbook, title: str, widths: list[int] | None = None):
        self.wb = wb
        self.lab = getattr(wb, "_ftp_label", None) or (lambda t: t)
        title = self.lab(title)
        self.ws = wb.create_sheet(title)
        self.title = title
        self.row = 0
        self._styles: dict = {}
        for i, w in enumerate(widths or [], start=1):
            self.ws.column_dimensions[get_column_letter(i)].width = w

    def cell(self, value, style: str | None = None) -> WriteOnlyCell:
        c = WriteOnlyCell(self.ws, value=value)
        if style:
            # Resolving a named style is slow; resolve once per sheet and share the
            # immutable style array (write-only cells are serialised immediately).
            cached = self._styles.get(style)
            if cached is None:
                c.style = style
                self._styles[style] = c._style
            else:
                c._style = cached
        return c

    def append(self, values: list) -> int:
        self.ws.append(values)
        self.row += 1
        return self.row

    def banner(self, title: str, subtitle: str, width: int) -> None:
        title, subtitle = self.lab(title), self.lab(subtitle)
        self.append([self.cell(title, "ftp_title")] + [self.cell(None, "ftp_title") for _ in range(width - 1)])
        self.append([self.cell(subtitle, "ftp_subtitle")] + [self.cell(None, "ftp_subtitle") for _ in range(width - 1)])
        self.append([])


def section_label(sh: "_Sheet", text: str):
    return sh.cell(text, "ftp_label")


def _table_name(title: str) -> str:
    return "tbl" + re.sub(r"[^A-Za-z0-9]", "", title)[:40]


def _write_table(sh: _Sheet, headers: list[str], rows: list[list], kinds: list[str], name: str | None = None,
                 totals: bool = True, cell_styles: Callable[[int, int, object], str | None] | None = None) -> tuple[int, int]:
    """Write an Excel table starting at the next row. Returns (first_data_row, last_data_row)."""
    header_row = sh.append([sh.cell(sh.lab(h), "ftp_header") for h in headers])
    if not rows:
        rows = [["No records"] + [None] * (len(headers) - 1)]
    base_styles = [{"money": "ftp_money", "date": "ftp_date", "wrap": "ftp_wrap", "input": "ftp_input"}.get(k)
                   for k in kinds]
    for r_index, values in enumerate(rows):
        out = []
        for c_index, v in enumerate(values):
            style = base_styles[c_index] if (v is not None or kinds[c_index] == "input") else None
            if cell_styles:
                style = cell_styles(r_index, c_index, v) or style
            out.append(sh.cell(v, style) if style else v)
        sh.append(out)
    first, last = header_row + 1, sh.row
    ref = f"A{header_row}:{get_column_letter(len(headers))}{last}"
    table = Table(displayName=_table_name(name or sh.title), ref=ref)
    table.tableColumns = [TableColumn(id=i, name=str(sh.lab(h))) for i, h in enumerate(headers, start=1)]
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    with warnings.catch_warnings():  # columns are supplied explicitly above
        warnings.simplefilter("ignore", UserWarning)
        sh.ws.add_table(table)
    if totals:
        tot = [sh.cell("Total (visible rows)", "ftp_total_label")]
        for i, kind in enumerate(kinds[1:], start=2):
            if kind in ("money", "count"):
                col = get_column_letter(i)
                tot.append(sh.cell(f"=SUBTOTAL(109,{col}{first}:{col}{last})",
                                   "ftp_money_bold" if kind == "money" else "ftp_total_label"))
            else:
                tot.append(sh.cell(None, "ftp_total_label"))
        sh.append(tot)
    return first, last


# ----------------------------------------------------------------- line columns
def _rec(ln: ReconLine, side: str):
    return ln.books if side == "books" else ln.gstr2b


def _amount(ln: ReconLine, side: str, name: str):
    r = _rec(ln, side)
    return r.signed(name) if r is not None else None


def _diff(ln: ReconLine, name: str) -> Decimal:
    return ln.side("books", name) - ln.side("gstr2b", name)


def _books_scope(ln: ReconLine) -> str:
    if ln.books is None:
        return ""
    return "Prior period" if ln.books.is_prior_period else "Yes"


LINE_COLUMNS: list[tuple[str, Callable[[ReconLine], object], str, int]] = [
    ("Line No", lambda ln: ln.line_no, "int", 8),
    ("Category", lambda ln: ln.category.value, "text", 34),
    ("Match Level", lambda ln: ln.match_level, "int", 8),
    ("Confidence %", lambda ln: ln.confidence, "int", 10),
    ("Status", lambda ln: ln.status.value, "text", 22),
    ("Supplier GSTIN", lambda ln: ln.supplier_gstin, "text", 18),
    ("Supplier Name", lambda ln: ln.supplier_name, "text", 28),
    ("Document Type", lambda ln: ln.doc_type.label, "text", 12),
    ("Books Invoice No", lambda ln: ln.books.invoice_no if ln.books else None, "text", 18),
    ("GSTR-2B Invoice No", lambda ln: ln.gstr2b.invoice_no if ln.gstr2b else None, "text", 18),
    ("Books Date", lambda ln: ln.books.invoice_date if ln.books else None, "date", 12),
    ("GSTR-2B Date", lambda ln: ln.gstr2b.invoice_date if ln.gstr2b else None, "date", 12),
    ("Date Diff (days)", lambda ln: ln.date_diff_days, "int", 9),
    ("Books Period", lambda ln: ln.books.period if ln.books else None, "text", 10),
    ("GSTR-2B Period", lambda ln: ln.gstr2b.period if ln.gstr2b else None, "text", 10),
    ("Books In Scope", _books_scope, "text", 11),
]
for _name, _label in (("taxable", "Taxable"), ("igst", "IGST"), ("cgst", "CGST"), ("sgst", "SGST"),
                      ("cess", "Cess"), ("itc", "ITC")):
    LINE_COLUMNS += [
        (f"Books {_label}", lambda ln, n=_name: _amount(ln, "books", n), "money", 14),
        (f"GSTR-2B {_label}", lambda ln, n=_name: _amount(ln, "gstr2b", n), "money", 14),
        (f"{_label} Difference", lambda ln, n=_name: _diff(ln, n), "money", 14),
    ]
LINE_COLUMNS += [
    ("ITC at Risk", itc_at_risk, "money", 13),
    ("Reasons", lambda ln: " | ".join(ln.reasons), "wrap", 60),
    ("Flags", lambda ln: ", ".join(ln.flags), "text", 30),
    ("GSTR-2B ITC Availability", lambda ln: ln.gstr2b.itc_availability if ln.gstr2b else None, "text", 10),
    ("Books Source (file:row)", lambda ln: ln.books.reference if ln.books else None, "text", 36),
    ("GSTR-2B Source (file:row)", lambda ln: ln.gstr2b.reference if ln.gstr2b else None, "text", 36),
    ("Assigned To", lambda ln: ln.assigned_to, "text", 14),
    ("Action Date", lambda ln: ln.action_date, "date", 12),
    ("Remarks", lambda ln: ln.remarks, "wrap", 30),
]
COL = {name: get_column_letter(i) for i, (name, *_r) in enumerate(LINE_COLUMNS, start=1)}
DIFF_COLUMNS = [n for n, *_r in LINE_COLUMNS if n.endswith("Difference")]


def _line_sheet(wb: Workbook, title: str, lines: list[ReconLine], settings, note: str) -> _Sheet:
    sh = _Sheet(wb, title, [w for *_x, w in LINE_COLUMNS])
    sh.ws.freeze_panes = "C5"
    sh.banner(title, note, 12)
    headers = [n for n, *_r in LINE_COLUMNS]
    kinds = [k for _n, _g, k, _w in LINE_COLUMNS]
    rows = [[getter(ln) for _n, getter, _k, _w in LINE_COLUMNS] for ln in lines]
    cat_idx = 1
    by_label = {sh.lab(c.value): c for c in Category}
    for r in rows:
        r[cat_idx] = sh.lab(r[cat_idx])

    def styles(_r, c, v):
        if c == cat_idx and v in by_label:
            return f"ftp_cat_{CATEGORY_COLORS[by_label[v]]}"
        return None

    first, last = _write_table(sh, headers, rows, kinds, cell_styles=styles)
    tol = settings.amount_tolerance
    big = settings.large_difference_threshold
    red = PatternFill("solid", fgColor="EF9A9A")
    amber = PatternFill("solid", fgColor="FFE082")
    for name in DIFF_COLUMNS:
        col = COL[name]
        rng = f"{col}{first}:{col}{last}"
        sh.ws.conditional_formatting.add(rng, FormulaRule(formula=[f"ABS({col}{first})>={big}"], fill=red,
                                                          font=Font(bold=True), stopIfTrue=True))
        sh.ws.conditional_formatting.add(rng, CellIsRule(operator="notBetween", formula=[f"-{tol}", f"{tol}"],
                                                         fill=amber))
    return sh


_CAT_BY_VALUE = {c.value: c for c in Category}


# ------------------------------------------------------------------- sheets
def _executive_summary(wb, ctx, lines, dash, n_lines_sheet) -> None:
    client, run, settings = ctx.client, ctx.run, ctx.result.settings
    sh = _Sheet(wb, "Executive Summary", [44, 12, 14, 14, 18, 18, 18, 18, 16, 16, 16, 10])
    left, right = side_labels(run.comparison)
    sh.banner(f"FIN TAX PRO – GST Reconciliation ({left} vs {right})", TAGLINE, 12)
    info = [
        ("Client", f"{client.name}" + (f" ({client.trade_name})" if client.trade_name and client.trade_name != client.name else "")),
        ("GSTIN / PAN", f"{client.gstin} / {client.pan}"),
        ("State", client.state), ("Financial year", run.financial_year),
        ("Reconciliation period", f"{run.period_from} to {run.period_to}"),
        ("Run ID / prepared on", f"#{run.id} / {run.started_at:%d-%m-%Y %H:%M}"),
        ("Tolerances", f"₹{settings.amount_tolerance} per tax component; {settings.date_tolerance_days} days for dates"),
    ]
    for k, v in info:
        sh.append([sh.cell(k, "ftp_label"), v])
    sh.append([])
    sh.append([sh.cell("KEY FIGURES", "ftp_label")])
    sh.append([sh.cell("Metric", "ftp_header"), sh.cell("Value", "ftp_header")])
    for key, label, kind in DASHBOARD_LABELS:
        v = dash[key]
        sh.append([sh.lab(label), sh.cell(v, "ftp_money") if kind == "money" else v])
    sh.append(["Matching percentage (paired lines / all lines)", f"{dash['match_percentage']}%"])
    if dash["prior_period_books_matched"]:
        sh.append(["Prior-period books documents matched in this run", dash["prior_period_books_matched"]])
        sh.append(["ITC of those prior-period documents (not in books total above)",
                   sh.cell(dash["prior_period_itc"], "ftp_money")])
    sh.append([])
    sh.append([sh.cell("CATEGORY SUMMARY (each document counted once on its own side)", "ftp_label")])
    headers = ["Category", "Lines", "Books Docs", "GSTR-2B Docs", "Books Taxable", "GSTR-2B Taxable", "Books ITC",
               "GSTR-2B ITC", "ITC Difference", "ITC at Risk", "Check: Lines (formula)", "Check"]
    rows = []
    cs = [r for r in category_summary(lines) if r.lines]
    start_row = sh.row + 2
    src = "'Complete Reconciliation'!"
    first, last = 5, 4 + max(n_lines_sheet, 1)  # banner rows 1-3, header row 4

    def rng(col_name):
        return f"{src}${COL[col_name]}${first}:${COL[col_name]}${last}"

    for i, r in enumerate(cs):
        row_no = start_row + i
        rows.append([
            sh.lab(r.category.value), r.lines, r.books.count, r.gstr2b.count, r.books.taxable, r.gstr2b.taxable,
            r.books.itc, r.gstr2b.itc, r.itc_difference, r.itc_at_risk,
            f"=COUNTIF({rng('Category')},A{row_no})",
            f'=IF(AND(K{row_no}=B{row_no},ABS(SUMIFS({rng("Books ITC")},{rng("Category")},A{row_no},'
            f'{rng("Books In Scope")},"Yes")-G{row_no})<0.005,ABS(SUMIFS({rng("GSTR-2B ITC")},{rng("Category")},'
            f'A{row_no})-H{row_no})<0.005),"OK","CHECK")',
        ])
    kinds = ["text", "count", "count", "count", "money", "money", "money", "money", "money", "money", "count", "text"]
    _write_table(sh, headers, rows, kinds, name="CategorySummary", totals=True)
    books, g2b, _prior = side_totals(lines)
    sh.append([])
    sh.append([sh.cell("RECONCILIATION OF TOTALS", "ftp_label")])
    sh.append([sh.cell("Check", "ftp_header"), sh.cell("Documents", "ftp_header"), sh.cell("ITC", "ftp_header"),
               sh.cell("Result", "ftp_header")])
    input_books_itc = sum((r.signed("itc") for r in ctx.result.books), ZERO)
    input_g_itc = sum((r.signed("itc") for r in ctx.result.gstr2b), ZERO)
    sh.append(["Books documents in scope / ITC", len(ctx.result.books), sh.cell(input_books_itc, "ftp_money"),
               sh.cell("OK" if (len(ctx.result.books), input_books_itc) == (books.count, books.itc) else "MISMATCH", "ftp_ok")])
    sh.append(["GSTR-2B documents / ITC", len(ctx.result.gstr2b), sh.cell(input_g_itc, "ftp_money"),
               sh.cell("OK" if (len(ctx.result.gstr2b), input_g_itc) == (g2b.count, g2b.itc) else "MISMATCH", "ftp_ok")])
    sh.append(["Books ITC – GSTR-2B ITC", None, sh.cell(books.itc - g2b.itc, "ftp_money")])
    sh.append([])
    sh.append([sh.cell("Amounts are signed: credit notes reduce taxable value and ITC. Matched pairs are never "
                       "double-counted – books amounts are summed on the books side and GSTR-2B amounts on the "
                       "GSTR-2B side. 'ITC at Risk' is an exposure indicator for professional review, not a "
                       "determination of eligibility.", "ftp_note")])
    sh.append([sh.cell(f"{PRODUCT_FULL_NAME} v{__version__} · engine {ctx.result.engine_version} · "
                       f"input fingerprint {ctx.result.fingerprint[:16]}…", "ftp_note")])


def _supplier_sheet(wb, lines, vendors=None) -> None:
    vendors = vendors or {}
    sh = _Sheet(wb, "Supplier-Wise Summary", [18, 34, 10, 10, 16, 16, 15, 15, 15, 10, 10, 10, 10, 10, 15, 30])
    sh.ws.freeze_panes = "C5"
    sh.banner("Supplier-Wise Summary", "Sorted by absolute ITC difference. Filter or sort the table as needed; "
              "drill down via the Complete Reconciliation sheet (filter on Supplier GSTIN).", 12)
    rows = [[r.gstin, r.name, r.books.count, r.gstr2b.count, r.books.taxable, r.gstr2b.taxable, r.books.itc,
             r.gstr2b.itc, r.itc_difference, r.missing_in_2b, r.missing_in_books, r.duplicates, r.probable,
             r.unresolved, r.itc_at_risk, _vendor_note(vendors.get(r.gstin))] for r in supplier_summary(lines)]
    headers = ["Supplier GSTIN", "Supplier Name", "Books Docs", "GSTR-2B Docs", "Books Taxable", "GSTR-2B Taxable",
               "Books ITC", "GSTR-2B ITC", "ITC Difference", "Missing in GSTR-2B", "Missing in Books",
               "Duplicates", "Probable", "Unresolved", "ITC at Risk", "Follow-up Remarks"]
    kinds = ["text", "text", "count", "count", "money", "money", "money", "money", "money", "count", "count",
             "count", "count", "count", "money", "wrap"]
    first, last = _write_table(sh, headers, rows, kinds)
    if rows:
        n = min(len(rows), 10)
        chart = BarChart()
        chart.type = "bar"
        chart.title = "Top suppliers by ITC difference"
        chart.y_axis.title = "₹"
        chart.add_data(Reference(sh.ws, min_col=9, min_row=first - 1, max_row=first + n - 1), titles_from_data=True)
        chart.set_categories(Reference(sh.ws, min_col=2, min_row=first, max_row=first + n - 1))
        chart.height, chart.width = 9, 18
        sh.ws.add_chart(chart, f"R{first}")


def _vendor_note(v) -> str:
    if v is None:
        return ""
    parts = [v.followup_status, v.contact_person, v.email, v.phone,
             f"next {v.next_followup:%d-%m-%Y}" if v.next_followup else "", v.remarks]
    return " | ".join(p for p in parts if p)


def _month_sheet(wb, lines) -> list:
    sh = _Sheet(wb, "Month-Wise ITC Summary", [12, 10, 16, 16, 10, 16, 16, 16, 16, 16])
    sh.banner("Month-Wise ITC Summary", "Books by booking month; GSTR-2B by return period", 10)
    months = month_summary(lines)
    rows = [[m.month, m.books.count, m.books.taxable, m.books.itc, m.gstr2b.count, m.gstr2b.taxable, m.gstr2b.itc,
             m.itc_difference, m.matched_books_itc, m.unmatched_books_itc] for m in months]
    headers = ["Month", "Books Docs", "Books Taxable", "Books ITC", "GSTR-2B Docs", "GSTR-2B Taxable",
               "GSTR-2B ITC", "ITC Difference", "Books ITC Matched", "Books ITC Unmatched"]
    kinds = ["text", "count", "money", "money", "count", "money", "money", "money", "money", "money"]
    first, _last = _write_table(sh, headers, rows, kinds)
    if rows:
        chart = BarChart()
        chart.title = "ITC: Books vs GSTR-2B"
        chart.add_data(Reference(sh.ws, min_col=4, min_row=first - 1, max_row=first + len(rows) - 1), titles_from_data=True)
        chart.add_data(Reference(sh.ws, min_col=7, min_row=first - 1, max_row=first + len(rows) - 1), titles_from_data=True)
        chart.set_categories(Reference(sh.ws, min_col=1, min_row=first, max_row=first + len(rows) - 1))
        chart.height, chart.width = 8, 16
        sh.ws.add_chart(chart, f"L{first}")
    return months


def _gstr3b_sheet(wb, months) -> None:
    sh = _Sheet(wb, "GSTR-3B ITC Comparison", [12, 16, 16, 18, 16, 16, 50])
    sh.banner("GSTR-3B ITC Comparison (working)",
              "Enter ITC claimed in GSTR-3B Table 4(A)(5) in the yellow cells; differences recalculate.", 7)
    headers = ["Month", "ITC as per Books", "ITC as per GSTR-2B", "ITC Claimed in GSTR-3B", "3B − 2B", "3B − Books",
               "Observation"]
    first = sh.row + 2
    rows = []
    for i, m in enumerate(months):
        r = first + i
        rows.append([m.month, m.books.itc, m.gstr2b.itc, None, f"=IF(D{r}=\"\",\"\",D{r}-C{r})",
                     f"=IF(D{r}=\"\",\"\",D{r}-B{r})",
                     f"=IF(D{r}=\"\",\"GSTR-3B not entered\",IF(D{r}-C{r}>0.5,\"Claimed exceeds GSTR-2B – verify\",\"Within GSTR-2B\"))"])
    _write_table(sh, headers, rows, ["text", "money", "money", "input", "money", "money", "text"])
    sh.append([])
    sh.append([sh.cell("No GSTR-3B imported for these periods. Import the GSTR-3B JSON or template to get the "
                       "full Table 4 working; meanwhile this sheet is an editable working paper.", "ftp_note")])


def _ims_sheet(wb) -> None:
    sh = _Sheet(wb, "IMS Review", [18, 18, 14, 16, 16, 40])
    sh.banner("IMS Review", "Invoice Management System status comparison", 6)
    _write_table(sh, ["Supplier GSTIN", "Invoice No", "Invoice Date", "IMS Action", "Books Status", "Observation"],
                 [["No IMS data imported for this run", None, None, None, None,
                   "Import the IMS download to compare it. No portal action is ever performed by this software."]],
                 ["text"] * 6, totals=False)


def _pending_sheet(wb, lines, evidence=None) -> None:
    evidence = evidence or {}
    sh = _Sheet(wb, "Pending Action Register", [8, 34, 18, 28, 18, 12, 14, 14, 14, 50, 26, 14, 12, 30])
    sh.ws.freeze_panes = "C5"
    sh.banner("Pending Action Register", "Update Status, Assigned To, Action Date and Remarks here or in the "
              "application (the application keeps the audit trail).", 12)
    pending = [ln for ln in lines if is_pending(ln)]
    rows = [[ln.line_no, ln.category.value, ln.supplier_gstin, ln.supplier_name, ln.primary.invoice_no,
             ln.primary.invoice_date, ln.side("books", "itc") if current_books(ln) else None,
             ln.side("gstr2b", "itc") if ln.gstr2b else None, itc_at_risk(ln),
             SUGGESTED_ACTIONS.get(ln.category, "Review"), ln.status.value, ln.assigned_to, ln.action_date,
             ln.remarks, evidence.get(ln.line_no, 0)] for ln in pending]
    headers = ["Line No", "Category", "Supplier GSTIN", "Supplier Name", "Invoice No", "Invoice Date", "Books ITC",
               "GSTR-2B ITC", "ITC at Risk", "Suggested Action", "Status", "Assigned To", "Action Date", "Remarks",
               "Evidence Files"]
    kinds = ["int", "text", "text", "text", "text", "date", "money", "money", "money", "wrap", "text", "text",
             "date", "wrap", "count"]
    first, last = _write_table(sh, headers, rows, kinds)
    dv = DataValidation(type="list", formula1='"' + ",".join(s.value for s in ExceptionStatus) + '"',
                        allow_blank=True)
    dv.add(f"K{first}:K{last}")
    sh.ws.data_validations.append(dv)


def _sources_sheet(wb, ctx, issues) -> None:
    sh = _Sheet(wb, "Source Files & Settings", [10, 36, 14, 26, 10, 66, 10, 10, 10, 10])
    sh.banner("Source Files and Reconciliation Settings", "Every document in this workbook traces to a file and "
              "row listed here", 10)
    sh.append([sh.cell("SETTINGS", "ftp_label")])
    for k, v in ctx.result.settings.to_dict().items():
        sh.append([k.replace("_", " ").capitalize(), str(v)])
    sh.append(["Engine version", ctx.result.engine_version])
    sh.append(["Input fingerprint (SHA-256)", ctx.result.fingerprint])
    sh.append([])
    sh.append([sh.cell("SOURCE FILES", "ftp_label")])
    rows = [[f.id, f.file_name, f.source_type, f.layout, f.period or "", f.sha256, f.rows_read,
             f.documents_imported, f.rows_rejected, f.documents_skipped_existing] for f in ctx.source_files]
    _write_table(sh, ["File ID", "File Name", "Source", "Layout", "Period", "SHA-256", "Rows Read",
                      "Documents Imported", "Rows Rejected", "Skipped (already imported)"], rows,
                 ["int", "text", "text", "text", "text", "text", "count", "count", "count", "count"],
                 name="SourceFiles", totals=False)
    sh.append([])
    sh.append([sh.cell("IMPORT ISSUES (rejected rows are kept here with their original values)", "ftp_label")])
    names = {f.id: f.file_name for f in ctx.source_files}
    rows = [[i.source_file_id, names.get(i.source_file_id, ""), i.severity.upper(), i.row_ref, None, i.message,
             _compact(i.raw_json)] for i in issues]
    _write_table(sh, ["File ID", "File Name", "Severity", "Row", "Sheet", "Message", "Original Values"], rows,
                 ["int", "text", "text", "text", "text", "wrap", "wrap"], name="ImportIssues", totals=False)


def _compact(raw_json: str) -> str:
    try:
        data = json.loads(raw_json or "{}")
    except ValueError:
        return raw_json
    return "; ".join(f"{k}={v}" for k, v in data.items() if v not in ("", None))[:1000]


# ---------------------------------------------------------------- entry point
def build_workbook(ctx, issues=(), vendors=None, evidence=None, itc=None, outward=None) -> Workbook:
    from .itc_sheets import ItcReportData, gstr3b_sheet, ims_sheet, itc_review_sheet
    from .outward_sheets import OutwardReportData, gstr1_sections_sheet, liability_sheet

    itc = itc or ItcReportData()
    outward = outward or OutwardReportData()
    lines = ctx.result.lines
    settings = ctx.result.settings
    wb = Workbook(write_only=True)
    comparison = ctx.run.comparison
    wb._ftp_label = lambda t: relabel(t, comparison) if isinstance(t, str) else t
    is_outward = comparison.startswith("SALES")
    _register_styles(wb)
    dash = dashboard(lines)
    paired_with = lambda flags: [ln for ln in lines if ln.is_paired and set(ln.flags) & flags]  # noqa: E731
    tax_flags = {Flag.IGST_DIFF.value, Flag.CGST_DIFF.value, Flag.SGST_DIFF.value, Flag.CESS_DIFF.value}

    _executive_summary(wb, ctx, lines, dash, len(lines))
    _line_sheet(wb, "Complete Reconciliation", lines, settings,
                "Every books and GSTR-2B document appears exactly once")
    _line_sheet(wb, "Fully Matched Invoices", [ln for ln in lines if ln.category in
                                               (Category.FULLY_MATCHED, Category.MANUALLY_MATCHED)], settings,
                "All compared fields agree within tolerance")
    _line_sheet(wb, "Partially Matched Invoices", [ln for ln in lines if ln.category in PARTIAL_CATEGORIES],
                settings, "Same document, with reported differences")
    _line_sheet(wb, "Missing in GSTR-2B", [ln for ln in lines if ln.category == Category.MISSING_IN_2B], settings,
                "In books, not reported by supplier")
    _line_sheet(wb, "Missing in Books", [ln for ln in lines if ln.category == Category.MISSING_IN_BOOKS], settings,
                "In GSTR-2B, not in purchase register")
    _line_sheet(wb, "Taxable Value Differences", paired_with({Flag.TAXABLE_DIFF.value}), settings,
                "Matched documents with taxable value difference beyond tolerance")
    _line_sheet(wb, "GST Component Differences", paired_with(tax_flags), settings,
                "Matched documents with IGST/CGST/SGST/Cess differences beyond tolerance")
    _line_sheet(wb, "Duplicate Invoices", [ln for ln in lines if ln.category in (
        Category.DUPLICATE_IN_BOOKS, Category.DUPLICATE_IN_2B) or Flag.COUNTERPART_DUPLICATED.value in ln.flags],
                settings, "Repeated documents are excluded from automatic matching")
    _supplier_sheet(wb, lines, vendors)
    months = _month_sheet(wb, lines)
    if is_outward:
        liability_sheet(wb, outward)
    elif not gstr3b_sheet(wb, itc):
        _gstr3b_sheet(wb, months)
    _line_sheet(wb, "Previous-Period Adjustments", [ln for ln in lines if ln.category == Category.PREVIOUS_PERIOD
                                                    or Flag.DATED_BEFORE_PERIOD.value in ln.flags], settings,
                "Earlier-period documents reflected in this GSTR-2B")
    _line_sheet(wb, "Credit-Debit Note Differences", [ln for ln in lines if ln.doc_type != DocType.INVOICE
                                                      and ln.category != Category.FULLY_MATCHED], settings,
                "Credit and debit notes needing attention")
    if is_outward:
        gstr1_sections_sheet(wb, outward)
    elif not ims_sheet(wb, itc):
        _ims_sheet(wb)
    _pending_sheet(wb, lines, evidence)
    _sources_sheet(wb, ctx, issues)
    if not is_outward:
        itc_review_sheet(wb, itc)
    return wb


def export_excel(ctx, out_path: str | Path, issues=(), vendors=None, evidence=None, itc=None, outward=None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = build_workbook(ctx, issues, vendors, evidence, itc, outward)
    wb.properties.title = f"GST Reconciliation {ctx.client.gstin} {ctx.run.period_from}"
    wb.properties.creator = "FIN TAX PRO"
    wb.properties.created = datetime.now()
    tmp = out_path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(out_path)  # never leave a half-written report behind
    return out_path


SHEET_NAMES = [
    "Executive Summary", "Complete Reconciliation", "Fully Matched Invoices", "Partially Matched Invoices",
    "Missing in GSTR-2B", "Missing in Books", "Taxable Value Differences", "GST Component Differences",
    "Duplicate Invoices", "Supplier-Wise Summary", "Month-Wise ITC Summary", "GSTR-3B ITC Comparison",
    "Previous-Period Adjustments", "Credit-Debit Note Differences", "IMS Review", "Pending Action Register",
    "Source Files & Settings", "ITC Eligibility Review",
]
