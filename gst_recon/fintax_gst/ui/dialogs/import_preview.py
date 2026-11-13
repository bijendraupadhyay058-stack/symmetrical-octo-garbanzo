"""Import preview: what will be saved, rejected, skipped – before anything is written."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout,
)

from ...importers.column_mapping import FIELD_LABELS
from ...importers.pipeline import ImportPreview
from ..theme import money
from ..widgets import RowsModel, Table, sortable

SEVERITY_ORDER = {"error": 0, "duplicate": 1, "existing": 2, "warning": 3, "ignored": 4, "info": 5}


class ImportPreviewDialog(QDialog):
    REMAP = 2  # dialog result: user wants to change the column mapping

    def __init__(self, parent, preview: ImportPreview):
        super().__init__(parent)
        self.preview = preview
        self.setWindowTitle(f"Import preview – {preview.file_name}")
        self.resize(1100, 680)
        lay = QVBoxLayout(self)
        s = preview.summary()
        grid = QGridLayout()
        facts = [
            ("File", preview.file_name), ("Detected layout", preview.layout_label),
            ("Source", preview.source.value), ("Period", preview.period or "from voucher/invoice dates"),
            ("Rows read", s["rows_read"]), ("Valid documents", s["valid_documents"]),
            ("New documents to save", s["new_documents"]), ("Already imported (skipped)", s["already_imported_documents"]),
            ("Rejected rows", s["rejected_rows"]), ("Duplicate rows in file", s["duplicate_rows_in_file"]),
            ("Ignored total rows", s["ignored_rows"]), ("Rows with warnings", s["rows_with_warnings"]),
            ("Taxable value", money(s["taxable_total"], True)), ("ITC", money(s["itc_total"], True)),
        ]
        for i, (k, v) in enumerate(facts):
            grid.addWidget(QLabel(f"<span style='color:#5C6B80'>{k}</span>"), i // 4, (i % 4) * 2)
            val = QLabel(f"<b>{v}</b>")
            if k == "Rejected rows" and s["rejected_rows"]:
                val.setObjectName("Error")
            grid.addWidget(val, i // 4, (i % 4) * 2 + 1)
        lay.addLayout(grid)
        if preview.already_imported_file_id:
            warn = QLabel(f"This exact file was already imported (import #{preview.already_imported_file_id}). "
                          "It cannot be imported again.")
            warn.setObjectName("Error")
            lay.addWidget(warn)
        for w in preview.file_warnings:
            lbl = QLabel("⚠ " + w)
            lbl.setObjectName("Warn")
            lay.addWidget(lbl)

        tabs = QTabWidget()
        docs = RowsModel(
            ["Supplier GSTIN", "Supplier", "Type", "Invoice No", "Date", "Period", "Taxable", "IGST", "CGST", "SGST",
             "Cess", "Source rows", "Status"],
            [[r.supplier_gstin, r.supplier_name, r.doc_type.label, r.invoice_no, r.invoice_date, r.period,
              r.signed("taxable"), r.signed("igst"), r.signed("cgst"), r.signed("sgst"), r.signed("cess"),
              r.source_rows, "Already imported" if r.identity_hash() in preview.existing_record_hashes else "New"]
             for r in preview.records],
            ["text", "text", "text", "text", "date", "text", "money", "money", "money", "money", "money", "text",
             "text"])
        t1 = Table()
        t1.setModel(sortable(docs))
        t1.fit()
        tabs.addTab(t1, f"Documents ({len(preview.records)})")
        issues = sorted(preview.issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.sheet, i.row))
        imodel = RowsModel(["Severity", "Sheet", "Row", "Message", "Original values"],
                           [[i.severity.upper(), i.sheet, i.row, i.message,
                             "; ".join(f"{k}={v}" for k, v in i.raw.items() if v)] for i in issues])
        t2 = Table()
        t2.setModel(sortable(imodel))
        t2.fit(420)
        tabs.addTab(t2, f"Issues ({len([i for i in issues if i.severity != 'info'])})")
        mrows = [[sheet, FIELD_LABELS.get(f, f), " + ".join(cols)]
                 for sheet, m in preview.mappings.items() for f, cols in m.fields.items()]
        mrows += [[sheet, "note", n] for sheet, m in preview.mappings.items() for n in m.notes]
        t3 = Table()
        t3.setModel(sortable(RowsModel(["Sheet", "Field", "Column(s)"], mrows)))
        t3.fit(420)
        tabs.addTab(t3, "Column mapping")
        lay.addWidget(tabs, 1)

        buttons = QDialogButtonBox()
        self.import_btn = QPushButton(f"Import {len(preview.new_records)} document(s)")
        self.import_btn.setObjectName("Primary")
        self.import_btn.setEnabled(not preview.already_imported_file_id and bool(preview.records or preview.issues))
        self.remap_btn = QPushButton("Change column mapping…")
        self.remap_btn.setEnabled(bool(preview.columns))
        buttons.addButton(self.import_btn, QDialogButtonBox.AcceptRole)
        buttons.addButton(self.remap_btn, QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        self.import_btn.clicked.connect(self.accept)
        self.remap_btn.clicked.connect(lambda: self.done(self.REMAP))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
