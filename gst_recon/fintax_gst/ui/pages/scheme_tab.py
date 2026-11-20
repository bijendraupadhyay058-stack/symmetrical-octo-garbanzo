"""GSTR-3B & annual → Composition / QRMP: CMP-08 and GSTR-4 for composition dealers; IFF and PMT-06 for QRMP."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ...core.money import fmt_inr
from ...services.common import ServiceError
from ...services.composition import CATEGORIES, CompositionService, quarter_label
from ..widgets import RowsModel, Table, primary, section


class SchemeTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.svc = CompositionService(state.db)
        lay = QVBoxLayout(self)
        lay.addWidget(section("Composition scheme – CMP-08 and GSTR-4"))
        row = QHBoxLayout()
        self.cat = QComboBox()
        self.cat.addItem("— not a composition dealer —", None)
        for k, (label, rate) in CATEGORIES.items():
            self.cat.addItem(f"{label} – {rate}%", k)
        save = QPushButton("Save")
        save.clicked.connect(lambda: self.save_category())
        self.period = QLineEdit(f"{date.today():%Y-%m}")
        self.period.setMaximumWidth(90)
        cmp_btn = primary("CMP-08 for the quarter")
        cmp_btn.clicked.connect(lambda: self.show_cmp08())
        g4 = QPushButton("GSTR-4 (year)")
        g4.clicked.connect(lambda: self.show_gstr4())
        for w in (QLabel("Category"), self.cat, save, QLabel("Month"), self.period, cmp_btn, g4):
            row.addWidget(w)
        row.addStretch()
        lay.addLayout(row)
        self.c_model = RowsModel(["Item", "Value", "CGST", "SGST", "IGST", "Total"],
                                 kinds=["text", "money", "money", "money", "money", "money"])
        t = Table()
        t.setModel(self.c_model)
        t.setSortingEnabled(False)
        lay.addWidget(t, 1)
        self.c_table = t
        self.c_info = QLabel()
        self.c_info.setWordWrap(True)
        self.c_info.setObjectName("Muted")
        lay.addWidget(self.c_info)
        lay.addWidget(section("QRMP – IFF and monthly payment (PMT-06)"))
        r2 = QHBoxLayout()
        pmt = primary("Work out PMT-06 for the month")
        pmt.clicked.connect(lambda: self.show_pmt06())
        r2.addWidget(pmt)
        r2.addStretch()
        lay.addLayout(r2)
        self.p_model = RowsModel(["Method", "IGST", "CGST", "SGST", "Cess", "Total"],
                                 kinds=["text", "money", "money", "money", "money", "money"])
        t2 = Table()
        t2.setModel(self.p_model)
        t2.setSortingEnabled(False)
        lay.addWidget(t2, 1)
        self.p_table = t2
        self.p_info = QLabel()
        self.p_info.setWordWrap(True)
        lay.addWidget(self.p_info)

    def reload(self) -> None:
        if self.state.client is None:
            return
        cat = self.svc.category(self.state.client.id)
        self.cat.setCurrentIndex(max(self.cat.findData(cat), 0))

    def save_category(self) -> None:
        if self.state.client is not None:
            self.svc.set_category(self.state.client.id, self.cat.currentData(), self.state.user)
            self.c_info.setText("Saved.")

    def show_cmp08(self):
        if self.state.client is None:
            return None
        try:
            q = self.svc.cmp08(self.state.client.id, self.period.text().strip())
        except ServiceError as exc:
            self.c_info.setText(str(exc))
            return None
        out, rcm = q.tax_outward, q.tax_rcm
        self.c_model.set_rows([
            [f"Outward supplies @ {q.rate}% ({q.category})", q.turnover, out["cgst"], out["sgst"], out["igst"],
             sum(out.values())],
            ["Inward supplies under reverse charge", None, rcm["cgst"], rcm["sgst"], rcm["igst"], sum(rcm.values())],
            ["Tax payable (CMP-08)", None, out["cgst"] + rcm["cgst"], out["sgst"] + rcm["sgst"],
             out["igst"] + rcm["igst"], q.total]])
        self.c_table.fit(360)
        self.c_info.setText(f"Quarter {quarter_label(q.months[0])}: pay <b>₹{fmt_inr(q.total)}</b> in cash."
                            + "<br>" + "<br>".join(f"• {n}" for n in q.notes))
        return q

    def show_gstr4(self):
        if self.state.client is None:
            return None
        try:
            g = self.svc.gstr4(self.state.client.id, self.state.fy)
        except ServiceError as exc:
            self.c_info.setText(str(exc))
            return None
        rows = [[f"Quarter {quarter_label(q.months[0])}", q.turnover, q.tax_outward["cgst"] + q.tax_rcm["cgst"],
                 q.tax_outward["sgst"] + q.tax_rcm["sgst"], q.tax_outward["igst"] + q.tax_rcm["igst"], q.total]
                for q in g["quarters"]]
        rows.append(["Year", g["turnover"], None, None, None, g["tax"]])
        rows.append(["Inward supplies (purchase register)", g["inward_taxable"], None, None, None, g["inward_tax"]])
        self.c_model.set_rows(rows)
        self.c_table.fit(360)
        self.c_info.setText(f"GSTR-4 for {self.state.fy} is due by 30 June after the year.")
        return g

    def show_pmt06(self):
        if self.state.client is None:
            return None
        try:
            p = self.svc.pmt06(self.state.client.id, self.period.text().strip())
        except ServiceError as exc:
            self.p_info.setText(str(exc))
            return None
        rows = []
        for label, v in (("Fixed sum", p.fixed_sum), ("Self-assessment (actual tax − ITC)", p.self_assessed)):
            if v is not None:
                rows.append([label, v["igst"], v["cgst"], v["sgst"], v["cess"], sum(v.values())])
        self.p_model.set_rows(rows)
        self.p_table.fit(360)
        self.p_info.setText((f"Fixed sum: {p.fixed_basis}. " if p.fixed_basis else "") +
                            f"IFF: {p.iff_docs} B2B invoice(s), ₹{fmt_inr(p.iff_value)}"
                            + (" – <span style='color:#C62828'>over the ₹50 lakh limit</span>" if p.iff_over_limit
                               else "") + "<br>" + "<br>".join(f"• {n}" for n in p.notes))
        return p
