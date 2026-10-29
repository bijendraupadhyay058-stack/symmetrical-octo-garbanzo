"""ITC review: rule flags, claim register (claim / reverse / reclaim) and rule configuration."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ...importers.gstr3b import Gstr3bValues
from ...itc.review import BUCKET_LABELS
from ...itc.rules import Rule
from ...services.common import ServiceError
from ..state import AppState
from ..theme import AMBER, NAVY, RED, TEAL, money
from ..widgets import OBJECT_ROLE, KpiCard, LazyPage, RowsModel, Table, card, page_header, primary, sortable

KPIS = [("itc_books", "ITC as per books", NAVY), ("itc_2b", "ITC in GSTR-2B", TEAL),
        ("not_claimed", "Not yet claimed", AMBER), ("claimed_register", "Claimed (register)", TEAL),
        ("blocked_17_5", "Potentially blocked – 17(5)", RED), ("time_limit_exposure", "Time-limit exposure – 16(4)", RED)]
SEVERITY_COLORS = {"high": "#FFCDD2", "medium": "#FFF3C4", "info": "#E3F2FD"}


def _d(qd: QDate) -> date:
    return date(qd.year(), qd.month(), qd.day())


class ItcPage(LazyPage):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setObjectName("Page")
        self.reviews = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        self.header = page_header("ITC review", "")
        lay.addWidget(self.header)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Review as of"))
        self.as_of = QDateEdit(QDate.currentDate())
        self.as_of.setCalendarPopup(True)
        self.as_of.setDisplayFormat("dd-MM-yyyy")
        self.as_of.dateChanged.connect(lambda _d: self.reload())
        bar.addWidget(self.as_of)
        bar.addStretch()
        lay.addLayout(bar)
        grid = QGridLayout()
        self.cards = {}
        for i, (k, label, color) in enumerate(KPIS):
            c = KpiCard(label, color)
            self.cards[k] = c
            grid.addWidget(c, i // 3, i % 3)
        lay.addLayout(grid)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._flags_tab(), "Flags for review")
        self.tabs.addTab(self._summary_tab(), "ITC summary")
        self.tabs.addTab(self._claims_tab(), "Claim register")
        self.tabs.addTab(self._rules_tab(), "Rules")
        lay.addWidget(self.tabs, 1)
        for sig in (state.runChanged, state.dataChanged, state.clientChanged):
            sig.connect(self.lazy(self.reload))
        self.lazy(self.reload)()

    # --------------------------------------------------------------- tabs
    def _flags_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QHBoxLayout()
        self.sev_cb = QComboBox()
        self.sev_cb.addItems(["All severities", "high", "medium", "info"])
        self.open_only = QCheckBox("Open flags only")
        self.open_only.setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search invoice, supplier, rule…")
        for x in (self.sev_cb, self.open_only, self.search):
            f.addWidget(x)
        lay.addLayout(f)
        split = QSplitter(Qt.Horizontal)
        self.flag_model = RowsModel(
            ["Line", "Invoice No", "Supplier", "Rule", "Severity", "Decision", "Date", "ITC", "In 2B", "Claim",
             "Deadline", "Days"],
            kinds=["int", "text", "text", "text", "text", "text", "date", "money", "text", "text", "date", "int"],
            colors=self._flag_color)
        self.flag_proxy = sortable(self.flag_model)
        self.flags = Table()
        self.flags.setModel(self.flag_proxy)
        self.flags.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.flags.selectionModel().selectionChanged.connect(self._flag_selected)
        for sig in (self.sev_cb.currentIndexChanged, self.open_only.toggled):
            sig.connect(lambda *_: self._fill_flags())
        self.search.textChanged.connect(self.flag_proxy.setFilterFixedString)
        split.addWidget(self.flags)
        frame, dl = card()
        self.detail = QLabel("Select a flag")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dl.addWidget(self.detail)
        row = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm flag")
        self.dismiss_btn = QPushButton("Dismiss flag…")
        self.confirm_btn.clicked.connect(lambda: self.decide("CONFIRMED"))
        self.dismiss_btn.clicked.connect(lambda: self.decide("DISMISSED"))
        row.addWidget(self.confirm_btn)
        row.addWidget(self.dismiss_btn)
        dl.addLayout(row)
        row2 = QHBoxLayout()
        self.claim_sel_btn = primary("Claim selected…")
        self.reverse_btn = QPushButton("Reverse…")
        self.reclaim_btn = QPushButton("Reclaim…")
        self.claim_sel_btn.clicked.connect(self.claim_selected)
        self.reverse_btn.clicked.connect(lambda: self.adjust("reverse"))
        self.reclaim_btn.clicked.connect(lambda: self.adjust("reclaim"))
        for b in (self.claim_sel_btn, self.reverse_btn, self.reclaim_btn):
            row2.addWidget(b)
        dl.addLayout(row2)
        dl.addStretch()
        split.addWidget(frame)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        return w

    def _summary_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.bucket_model = RowsModel(["Measure", "Amount"], kinds=["text", "money"])
        t = Table()
        t.setModel(self.bucket_model)
        t.setSortingEnabled(False)
        lay.addWidget(t)
        note = QLabel("Measures are views over documents (a document can be both 'not yet claimed' and "
                      "'potentially blocked'). Flags are for professional review – not conclusions on eligibility.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def _claims_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.claim_all_btn = primary("Claim all eligible documents of this run…")
        self.claim_all_btn.setToolTip("Matched with GSTR-2B and no open high/medium flag; already-claimed "
                                      "documents are never claimed twice")
        self.claim_all_btn.clicked.connect(self.claim_all)
        row.addWidget(self.claim_all_btn)
        row.addStretch()
        lay.addLayout(row)
        self.claim_model = RowsModel(["Period", "Action", "Supplier GSTIN", "Invoice No", "Date", "Amount", "Reason",
                                      "Rule ref", "By", "At"],
                                     kinds=["text", "text", "text", "text", "date", "money", "text", "text", "text",
                                            "text"])
        t = Table()
        t.setModel(sortable(self.claim_model))
        lay.addWidget(t, 1)
        self.claims_table = t
        return w

    def _rules_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Scope"))
        self.scope_cb = QComboBox()
        self.scope_cb.addItems(["This client", "All clients"])
        self.scope_cb.currentIndexChanged.connect(lambda _i: self._fill_rules())
        row.addWidget(self.scope_cb)
        row.addStretch()
        self.new_rule_btn = QPushButton("New keyword rule…")
        self.new_rule_btn.clicked.connect(self.new_rule)
        row.addWidget(self.new_rule_btn)
        lay.addLayout(row)
        split = QSplitter(Qt.Horizontal)
        self.rule_model = RowsModel(["Code", "On", "Severity", "From", "To", "Rule", "Reference"],
                                    kinds=["text", "text", "text", "date", "date", "text", "text"])
        self.rules_table = Table()
        self.rules_table.setModel(self.rule_model)
        self.rules_table.setSortingEnabled(False)
        self.rules_table.selectionModel().selectionChanged.connect(self._rule_selected)
        split.addWidget(self.rules_table)
        frame, fl = card()
        form = QFormLayout()
        self.r_enabled = QCheckBox("Enabled")
        self.r_severity = QComboBox()
        self.r_severity.addItems(["high", "medium", "info"])
        self.r_from = QDateEdit()
        self.r_from.setDisplayFormat("dd-MM-yyyy")
        self.r_to_set = QCheckBox("Ends on")
        self.r_to = QDateEdit()
        self.r_to.setDisplayFormat("dd-MM-yyyy")
        self.r_keywords = QLineEdit()
        self.r_gstins = QLineEdit()
        self.r_guidance = QLabel()
        self.r_guidance.setWordWrap(True)
        to_row = QHBoxLayout()
        to_row.addWidget(self.r_to_set)
        to_row.addWidget(self.r_to)
        for label, wdg in (("", self.r_enabled), ("Severity", self.r_severity), ("Effective from", self.r_from),
                           ("", to_row), ("Keywords (comma-separated)", self.r_keywords),
                           ("Supplier GSTINs", self.r_gstins), ("Guidance", self.r_guidance)):
            form.addRow(label, wdg)
        fl.addLayout(form)
        btns = QHBoxLayout()
        self.r_save = primary("Save rule")
        self.r_save.clicked.connect(self.save_rule)
        self.r_reset = QPushButton("Reset to default")
        self.r_reset.clicked.connect(self.reset_rule)
        btns.addWidget(self.r_save)
        btns.addWidget(self.r_reset)
        fl.addLayout(btns)
        fl.addStretch()
        split.addWidget(frame)
        lay.addWidget(split, 1)
        return w

    # --------------------------------------------------------------- data
    def _flag_color(self, row, col):
        from PySide6.QtGui import QColor

        if col != 4:
            return None
        sev = self.flag_model.rows[row][4]
        return QColor(SEVERITY_COLORS.get(sev, "#FFFFFF"))

    def reload(self) -> None:
        st = self.state
        self._apply_permissions()
        if st.client is None or st.run_id is None:
            self.header.subtitle.setText("Select a client and run a reconciliation first.")
            self.reviews, self.buckets = [], {}
            self._fill_flags()
            self.bucket_model.set_rows([])
            self.claim_model.set_rows([])
            self._fill_rules()
            return
        ctx = st.run_context()
        self.header.subtitle.setText(f"{ctx.client.name} · Run #{ctx.run.id} · {ctx.run.period_from} to "
                                     f"{ctx.run.period_to} · flags carry statutory references and guidance")
        self.reviews, self.buckets = st.itc.review_run(st.run_id, _d(self.as_of.date()))
        for k, c in self.cards.items():
            c.set(money(self.buckets.get(k, Decimal(0)), True))
        self.bucket_model.set_rows([[label, self.buckets.get(k, Decimal(0))] for k, label in BUCKET_LABELS])
        self._fill_flags()
        self._fill_claims()
        self._fill_rules()

    def _fill_flags(self) -> None:
        sev = self.sev_cb.currentText()
        rows, payload = [], []
        for rv in self.reviews:
            for h in rv.hits:
                if self.open_only.isChecked() and not h.open:
                    continue
                if sev in ("high", "medium", "info") and h.severity != sev:
                    continue
                rows.append([rv.line_no, rv.record.invoice_no, rv.record.supplier_name, h.code, h.severity,
                             h.decision or "Open", rv.record.invoice_date, rv.itc, "Yes" if rv.in_2b else "No",
                             "Claimed" if rv.claim.is_claimed else "Not claimed", rv.deadline, rv.days_left])
                payload.append((rv, h))
        self.flag_model.set_rows(rows, payload)
        self.flags.fit(220)
        self._flag_selected()

    def _fill_claims(self) -> None:
        st = self.state
        rows = []
        for c, inv in st.itc.claim_register(st.client.id):
            rows.append([c.period, c.action, inv.supplier_gstin, inv.invoice_no, inv.invoice_date,
                         c.igst + c.cgst + c.sgst + c.cess, c.reason, c.rule_ref, c.user,
                         f"{c.created_at:%d-%m-%Y %H:%M}"])
        self.claim_model.set_rows(rows)
        self.claims_table.fit(260)

    def _fill_rules(self) -> None:
        cid = self._rule_scope()
        self.rules = self.state.itc.rules(cid) if (cid or self.scope_cb.currentIndex() == 1) else []
        self.rule_model.set_rows([[r.code, "Yes" if r.enabled else "No", r.severity, r.effective_from,
                                   r.effective_to, r.title, r.reference] for r in self.rules], self.rules)
        self.rules_table.fit(320)

    def _rule_scope(self) -> int | None:
        if self.scope_cb.currentIndex() == 1:
            return None
        return self.state.client.id if self.state.client else None

    # ------------------------------------------------------------ helpers
    def ask(self, title: str, label: str, default: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, label, text=default)
        return text if ok else None

    def selected(self):
        rows = sorted({i.row() for i in self.flags.selectionModel().selectedRows()})
        return [self.flag_proxy.index(r, 0).data(OBJECT_ROLE) for r in rows]

    def _flag_selected(self, *_):
        sel = self.selected()
        on = bool(sel)
        can_review, can_claim = self.state.can("review"), self.state.can("claim")
        self.confirm_btn.setEnabled(on and can_review)
        self.dismiss_btn.setEnabled(on and can_review)
        self.claim_sel_btn.setEnabled(on and can_claim)
        self.reverse_btn.setEnabled(len(sel) == 1 and can_claim)
        self.reclaim_btn.setEnabled(len(sel) == 1 and can_claim)
        if not sel:
            self.detail.setText("Select a flag to see its reference and guidance.")
            return
        rv, h = sel[0]
        claim = rv.claim
        self.detail.setText(
            f"<b>{h.title}</b><br><i>{h.reference}</i><p>{h.message}</p><p>{h.guidance}</p>"
            f"<p><b>{rv.record.invoice_no}</b> · {rv.record.supplier_name} · ITC {money(rv.itc, True)}<br>"
            f"Claimed {money(claim.claimed, True)} · reversed {money(claim.reversed, True)} · "
            f"reclaimed {money(claim.reclaimed, True)}"
            + (f"<br>Section 16(4) last date {rv.deadline:%d-%m-%Y} ({rv.days_left} days)" if rv.deadline else "")
            + (f"<br>Decision: {h.decision} – {h.remarks}" if h.decision else "") + "</p>")

    def _run(self, fn, *args) -> bool:
        try:
            fn(*args)
        except ServiceError as exc:
            QMessageBox.warning(self, "ITC review", str(exc))
            return False
        self.state.notify(keep_cache=True)
        self.reload()
        return True

    def _apply_permissions(self) -> None:
        self.claim_all_btn.setEnabled(self.state.can("claim"))
        for w in (self.r_save, self.r_reset, self.new_rule_btn):
            w.setEnabled(self.state.can("manage_rules"))

    # ------------------------------------------------------------ actions
    def decide(self, decision: str) -> None:
        sel = self.selected()
        if not sel:
            return
        remarks = self.ask("Dismiss flag" if decision == "DISMISSED" else "Confirm flag",
                           "Reason (recorded in the audit trail):")
        if remarks is None:
            return

        def apply():
            for rv, h in sel:
                self.state.itc.set_review(self.state.client.id, rv.record.db_id, h.code, decision, remarks,
                                          self.state.user)
        self._run(apply)

    def _default_period(self) -> str:
        ctx = self.state.run_context()
        return ctx.run.period_to if ctx else ""

    def claim_selected(self) -> None:
        docs = sorted({rv.record.db_id for rv, _h in self.selected() if rv.record.source.value == "BOOKS"})
        if not docs:
            return
        period = self.ask("Claim ITC", "GSTR-3B period of the claim (YYYY-MM):", self._default_period())
        if period:
            def apply():
                res = self.state.itc.claim(self.state.client.id, docs, period, self.state.user, self.state.run_id)
                if res.skipped:
                    QMessageBox.information(self, "Claim", "\n".join(f"#{i}: {why}" for i, why in res.skipped))
            self._run(apply)

    def claim_all(self) -> None:
        if self.state.run_id is None:
            return
        period = self.ask("Claim eligible ITC", "GSTR-3B period of the claim (YYYY-MM):", self._default_period())
        if not period:
            return

        def apply():
            res = self.state.itc.claim_eligible_from_run(self.state.run_id, period, self.state.user,
                                                         _d(self.as_of.date()))
            QMessageBox.information(self, "Claim", f"Claimed {len(res.claimed)} document(s) in {period}; "
                                                   f"{len(res.skipped)} left for review.")
        self._run(apply)

    def adjust(self, action: str) -> None:
        sel = self.selected()
        if len(sel) != 1:
            return
        rv, h = sel[0]
        period = self.ask(action.title(), "GSTR-3B period (YYYY-MM):", self._default_period())
        if not period:
            return
        reason = self.ask(action.title(), "Reason:", h.title if action == "reverse" else "")
        if reason is None:
            return
        amount = self.ask(action.title(), "Amount (blank = the full eligible amount; IGST,CGST,SGST,Cess):", "")
        if amount is None:
            return
        values = None
        if amount.strip():
            try:
                parts = [Decimal(x.strip() or "0") for x in amount.split(",")] + [Decimal(0)] * 4
            except InvalidOperation:
                QMessageBox.warning(self, action.title(), "Amounts must be numbers")
                return
            values = Gstr3bValues(*parts[:4])
        if action == "reverse":
            self._run(self.state.itc.reverse, self.state.client.id, rv.record.db_id, period, self.state.user, reason,
                      h.code, values)
        else:
            self._run(self.state.itc.reclaim, self.state.client.id, rv.record.db_id, period, self.state.user,
                      reason, values)

    # -------------------------------------------------------------- rules
    def _rule_selected(self, *_):
        rows = self.rules_table.selectionModel().selectedRows()
        self.current_rule: Rule | None = self.rules[rows[0].row()] if rows else None
        r = self.current_rule
        if r is None:
            return
        self.r_enabled.setChecked(r.enabled)
        self.r_severity.setCurrentText(r.severity)
        self.r_from.setDate(QDate(r.effective_from.year, r.effective_from.month, r.effective_from.day))
        self.r_to_set.setChecked(r.effective_to is not None)
        if r.effective_to:
            self.r_to.setDate(QDate(r.effective_to.year, r.effective_to.month, r.effective_to.day))
        self.r_keywords.setText(", ".join(r.keywords))
        self.r_gstins.setText(", ".join(r.gstins))
        self.r_keywords.setEnabled(r.kind == "keyword")
        self.r_gstins.setEnabled(r.kind == "gstin")
        self.r_guidance.setText(f"<i>{r.reference}</i><br>{r.guidance}")

    def save_rule(self) -> None:
        r = getattr(self, "current_rule", None)
        if r is None:
            return
        r.enabled = self.r_enabled.isChecked()
        r.severity = self.r_severity.currentText()
        r.effective_from = _d(self.r_from.date())
        r.effective_to = _d(self.r_to.date()) if self.r_to_set.isChecked() else None
        r.keywords = [k.strip() for k in self.r_keywords.text().split(",") if k.strip()]
        r.gstins = [g.strip().upper() for g in self.r_gstins.text().split(",") if g.strip()]
        self._run(self.state.itc.save_rule, r, self._rule_scope(), self.state.user)

    def reset_rule(self) -> None:
        r = getattr(self, "current_rule", None)
        if r is not None:
            self._run(self.state.itc.reset_rule, r.code, self._rule_scope(), self.state.user)

    def new_rule(self) -> None:
        name = self.ask("New keyword rule", "Short code (letters/digits):")
        if not name:
            return
        title = self.ask("New keyword rule", "Title:") or name
        reference = self.ask("New keyword rule", "Statutory reference:") or "Client-specific review"
        keywords = self.ask("New keyword rule", "Keywords (comma-separated):") or ""
        code = "CUSTOM_" + "".join(ch for ch in name.upper() if ch.isalnum())[:30]
        rule = Rule(code, title, reference, "keyword", "blocked", "medium",
                    keywords=[k.strip() for k in keywords.split(",") if k.strip()])
        self._run(self.state.itc.save_rule, rule, self._rule_scope(), self.state.user)

