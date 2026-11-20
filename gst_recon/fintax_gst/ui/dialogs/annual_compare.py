"""GSTR-9 / GSTR-9C prepared elsewhere compared with this program's working."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ...services.annual_import import AnnualImportService
from ...services.common import ServiceError
from ..widgets import RowsModel, Table


class AnnualCompareDialog(QDialog):
    def __init__(self, parent, state, fy: str, kind: str):
        super().__init__(parent)
        self.state, self.fy, self.kind = state, fy, kind
        self.svc = AnnualImportService(state.db)
        name = "GSTR-9" if kind == "GSTR9" else "GSTR-9C"
        self.setWindowTitle(f"{name} imported vs working – {state.client.name} – {fy}")
        self.resize(1050, 640)
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        if kind == "GSTR9":
            cols = ["Table", "Description", "File – taxable", "File – tax", "Working – taxable", "Working – tax",
                    "Difference (file − working)"]
            kinds = ["text", "text", "money", "money", "money", "money", "money"]
        else:
            cols = ["Table", "Description", "File – amount", "Working – amount", "Difference (file − working)"]
            kinds = ["text", "text", "money", "money", "money"]
        self.model = RowsModel(cols, kinds=kinds, colors=self._color)
        self.table = Table()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.use_btn = QPushButton("Use the file's audited figures in GSTR-9C")
        self.use_btn.setToolTip("Records Tables 5, 7B–7D and 12A–12C of the file as the amounts entered for the "
                                "year (each change is audited; you can still change or clear them)")
        self.use_btn.clicked.connect(lambda: self.use_amounts())
        self.use_btn.setVisible(kind == "GSTR9C")
        row.addWidget(self.use_btn)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def _color(self, row, _col):
        d = self.model.rows[row][-1]
        if d is not None and abs(d) >= 1:
            return QColor("#FFCDD2")
        return None

    def refresh(self) -> None:
        saved = self.svc.saved(self.state.client.id, self.fy, self.kind)
        if saved is None:
            self.info.setText("No file imported for this year.")
            self.model.set_rows([])
            return
        name, af = saved
        try:
            rows = (self.svc.compare_9 if self.kind == "GSTR9" else self.svc.compare_9c)(self.state.client.id, self.fy)
        except ServiceError as exc:
            self.info.setText(str(exc))
            return
        if self.kind == "GSTR9":
            self.model.set_rows([[r.code, r.label[:90], r.file_taxable, r.file_tax, r.ours_taxable, r.ours_tax,
                                  r.diff] for r in rows])
        else:
            self.model.set_rows([[r.code, r.label[:90], r.file_tax, r.ours_tax, r.diff] for r in rows])
        self.rows = rows
        off = sum(1 for r in rows if r.diff is not None and abs(r.diff) >= 1)
        self.info.setText(f"File: <b>{name}</b> · {len(rows)} table row(s) · "
                          + (f"<span style='color:#C62828'><b>{off} differ</b></span>" if off else
                             "<span style='color:#2E7D32'><b>no differences</b></span>")
                          + (f" · {len(af.skipped)} row(s) of the file not compared" if af.skipped else ""))
        self.table.fit(520)

    def use_amounts(self) -> int | None:
        if QMessageBox.question(self, "GSTR-9C", "Record the file's audited figures as the amounts entered for "
                                f"{self.fy}? Figures entered earlier for the same rows are replaced (the change is "
                                "audited).") != QMessageBox.Yes:
            return None
        try:
            n = self.svc.use_9c_amounts(self.state.client.id, self.fy, self.state.session)
        except ServiceError as exc:
            QMessageBox.warning(self, "GSTR-9C", str(exc))
            return None
        self.state.notify()
        self.refresh()
        return n
