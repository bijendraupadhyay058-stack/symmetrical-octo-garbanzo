"""Client and financial-year dashboard. All figures are computed from the run's lines."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...core.models import PAIRED_CATEGORIES, Category
from ...engine.summary import category_summary, dashboard, month_summary, supplier_summary
from .. import charts
from ..state import AppState
from ..theme import AMBER, NAVY, RED, TEAL, money
from ..widgets import KpiCard, LazyPage, RowsModel, Table, card, page_header, section, sortable

CARDS = [
    ("total_purchase_invoices", "Total Purchase Invoices", NAVY),
    ("purchase_taxable_value", "Purchase Taxable Value", NAVY),
    ("itc_as_per_books", "ITC as per Books", NAVY),
    ("itc_as_per_gstr2b", "ITC as per GSTR-2B", TEAL),
    ("fully_matched", "Fully Matched Invoices", TEAL),
    ("partially_matched", "Partially Matched Invoices", AMBER),
    ("missing_in_gstr2b", "Invoices Missing in GSTR-2B", RED),
    ("missing_in_books", "Invoices Missing in Books", RED),
    ("itc_difference", "ITC Difference (Books − 2B)", AMBER),
    ("itc_at_risk", "Potential ITC at Risk", RED),
    ("duplicates", "Duplicate Invoices", "#8E24AA"),
    ("pending_cases", "Pending Reconciliation Cases", AMBER),
]
MONEY_KEYS = {"purchase_taxable_value", "itc_as_per_books", "itc_as_per_gstr2b", "itc_difference", "itc_at_risk"}


class DashboardPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(22, 18, 22, 18)
        self.header = page_header("Dashboard", "")
        self.lay.addWidget(self.header)
        self.empty = QLabel()
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        self.lay.addWidget(self.empty)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards: dict[str, KpiCard] = {}
        for i, (key, title, accent) in enumerate(CARDS):
            c = KpiCard(title, accent)
            self.cards[key] = c
            grid.addWidget(c, i // 4, i % 4)
        self.lay.addLayout(grid)
        self.charts_box = QGridLayout()
        self.charts_box.setSpacing(12)
        self.lay.addLayout(self.charts_box)
        self.lay.addWidget(section("Financial-year overview (latest monthly run of each month)"))
        self.fy_model = RowsModel(["Month", "Run", "Books ITC", "GSTR-2B ITC", "ITC Difference", "ITC at Risk",
                                   "Fully Matched", "Pending"],
                                  kinds=["text", "int", "money", "money", "money", "money", "int", "int"])
        self.fy_table = Table()
        self.fy_table.setModel(sortable(self.fy_model))
        self.fy_table.setMinimumHeight(220)
        self.lay.addWidget(self.fy_table)
        self.lay.addStretch()
        for sig in (state.runChanged, state.clientChanged, state.dataChanged):
            sig.connect(self.lazy(self.refresh))
        self.chart_views = []
        self.lazy(self.refresh)()  # loads when first shown

    def _clear_charts(self) -> None:
        for v in self.chart_views:
            v.setParent(None)
            v.deleteLater()
        self.chart_views = []

    def refresh(self) -> None:
        st = self.state
        self._clear_charts()
        title, subtitle = self.header.title, self.header.subtitle
        if st.client is None:
            title.setText("Dashboard")
            subtitle.setText("")
            self.empty.setText("Select or create a client to begin (Clients page or the selector above).")
            self._set_cards(None)
            self.fy_model.set_rows([])
            return
        title.setText(f"Dashboard – {st.client.name}")
        self._fy_overview()
        if st.run_id is None:
            self.empty.setText(f"No reconciliation for FY {st.fy} yet. Use the Reconcile workflow to import "
                               "the purchase register and GSTR-2B and start a reconciliation.")
            self._set_cards(None)
            subtitle.setText(f"GSTIN {st.client.gstin} · FY {st.fy}")
            return
        ctx = st.run_context()
        lines = ctx.result.lines
        self.empty.setText("")
        subtitle.setText(f"GSTIN {st.client.gstin} · FY {ctx.run.financial_year} · Run #{ctx.run.id} "
                         f"({ctx.run.period_from} to {ctx.run.period_to}) · {ctx.run.started_at:%d-%m-%Y %H:%M}")
        d = dashboard(lines)
        self._set_cards(d)
        months = [(m.month, m.books.itc, m.gstr2b.itc) for m in month_summary(lines)]
        paired = sum(1 for ln in lines if ln.category in PAIRED_CATEGORIES)
        probable = sum(1 for ln in lines if ln.category in (Category.PROBABLE, Category.PENDING_CLARIFICATION))
        sup = [r for r in supplier_summary(lines) if r.itc_difference != 0][:10]
        exposure = [(r.category, r.itc_at_risk) for r in category_summary(lines) if r.itc_at_risk > 0]
        views = [
            charts.monthly_itc(months),
            charts.match_donut(paired, probable, len(lines) - paired - probable),
            charts.vendor_mismatch([(r.name or r.gstin, r.itc_difference) for r in sup]),
            charts.exposure_pie(exposure),
        ]
        for i, v in enumerate(views):
            frame, lay = card()
            lay.setContentsMargins(4, 4, 4, 4)
            lay.addWidget(v)
            self.charts_box.addWidget(frame, i // 2, i % 2)
            self.chart_views.append(frame)

    def _set_cards(self, d: dict | None) -> None:
        for key, c in self.cards.items():
            if d is None:
                c.set("–")
                continue
            v = d[key]
            sub = ""
            if key == "missing_in_gstr2b":
                sub = f"ITC {money(d['missing_in_gstr2b_itc'], True)}"
            elif key == "missing_in_books":
                sub = f"ITC {money(d['missing_in_books_itc'], True)}"
            elif key == "fully_matched":
                sub = f"{d['match_percentage']}% of lines paired"
            elif key == "pending_cases":
                sub = f"incl. {d['probable_matches']} probable matches"
            elif key == "itc_as_per_gstr2b":
                sub = f"{d['gstr2b_documents']} documents"
            elif key == "total_purchase_invoices" and d["prior_period_books_matched"]:
                sub = f"+{d['prior_period_books_matched']} prior-period matched"
            c.set(money(v, True) if key in MONEY_KEYS else str(v), sub)

    def _fy_overview(self) -> None:
        rows = []
        for r in self.state.tracking.fy_overview(self.state.client.id, self.state.fy):
            s = r["summary"]
            if s is None:
                rows.append([r["month"], None, None, None, None, None, None, None])
                continue
            dec = lambda k: Decimal(str(s.get(k, "0")))  # noqa: E731
            rows.append([r["month"], r["run_id"], dec("itc_as_per_books"), dec("itc_as_per_gstr2b"),
                         dec("itc_difference"), dec("itc_at_risk"), s.get("fully_matched"), s.get("pending_cases")])
        self.fy_model.set_rows(rows)
        self.fy_table.fit()
