# FIN TAX PRO – Architecture

## Layers

```
            ┌───────────────────────────────────────────────────────────┐
 Phase 1 →  │ cli.py (argparse)            Phase 2 → ui/ (PySide6)       │  presentation
            │                              Future  → api/ (FastAPI)      │
            ├───────────────────────────────────────────────────────────┤
            │ services/  clients · imports · reconciliation · reports    │  use-cases, transactions, audit
            ├───────────────┬───────────────────────┬───────────────────┤
            │ importers/    │ engine/                │ reports/          │
            │ readers       │ matcher (pure)         │ excel_report      │
            │ column_mapping│ summary (pure)         │ pdf_report        │
            │ validation    │                        │                   │
            │ gstn_json     │                        │                   │
            │ pipeline      │                        │                   │
            ├───────────────┴───────────────────────┴───────────────────┤
            │ core/  models (InvoiceRecord, ReconLine, enums) · money ·  │  domain, no I/O
            │        gstin · invoice_no                                  │
            ├───────────────────────────────────────────────────────────┤
            │ db/  SQLAlchemy models · versioned migrations · backup     │  persistence (SQLite)
            └───────────────────────────────────────────────────────────┘
```

Rules that keep the design open for a web/mobile front-end:

* `core/` and `engine/` import nothing from `db/`, `services/`, the UI or any web framework.
  The engine is a pure function `reconcile(books, gstr2b, settings, prior_books, period_start)`.
* `services/` owns every transaction. A FastAPI router or a PySide6 window calls the same
  service methods; nothing is duplicated.
* Long operations accept `progress(pct, message)` and a `CancelToken`. All writes of an
  operation happen inside one transaction, so cancelling never leaves partial data.

## File structure

```
gst_recon/
├── fintax_gst/
│   ├── __init__.py            product name, version
│   ├── __main__.py            python -m fintax_gst
│   ├── cli.py                 command-line interface (Phase 1 UI)
│   ├── samples.py             demo datasets + expected outcomes
│   ├── core/
│   │   ├── models.py          InvoiceRecord, ReconLine, Category, Flag, statuses, settings
│   │   ├── money.py           Decimal parsing/rounding/Indian formatting
│   │   ├── gstin.py           GSTIN format + check digit, state codes
│   │   └── invoice_no.py      invoice-number normalisation
│   ├── importers/
│   │   ├── readers.py         Excel / CSV / JSON / ZIP readers
│   │   ├── column_mapping.py  heading synonyms, auto-mapping, templates
│   │   ├── parsing.py         dates, periods, document types, Tally voucher types
│   │   ├── validation.py      row → InvoiceRecord with errors/warnings
│   │   ├── gstn_json.py       GSTR-2B / GSTR-2A portal JSON
│   │   └── pipeline.py        layout detection, header detection, preview
│   ├── engine/
│   │   ├── matcher.py         reconciliation passes and integrity checks
│   │   └── summary.py         dashboard, category, supplier, month summaries
│   ├── db/
│   │   ├── models.py          ORM tables (Decimal stored as exact text)
│   │   └── database.py        engine, migrations, backup/restore
│   ├── services/
│   │   ├── clients.py         client master
│   │   ├── imports.py         preview/commit, repeated-import protection, templates
│   │   ├── reconciliation.py  runs, reload, carry-forward, exception updates
│   │   ├── reports.py         export Excel + PDF for a run
│   │   └── common.py          audit log, conversions
│   └── reports/
│       ├── excel_report.py    17-sheet workbook
│       └── pdf_report.py      PDF summary
├── tests/                     pytest suite
├── sample_data/               generated demo files + EXPECTED_RESULTS.md
├── scripts/benchmark.py       performance measurement
├── packaging/                 PyInstaller spec + Windows build script
└── docs/                      this documentation
```

## Database

| Table | Purpose |
|---|---|
| `clients` | client master; unique GSTIN, PAN indexed (several GSTINs per PAN) |
| `source_files` | every import: file name, path, SHA-256, layout, period, counts, mapping used |
| `invoices` | imported documents, one row per document, original values kept, `identity_hash` for repeated-import detection |
| `import_issues` | rejected rows (with original cell values), warnings, duplicates, skipped-existing |
| `import_templates` | saved column mappings |
| `recon_runs` | each run: client, period, settings, input fingerprint, engine version, summary |
| `recon_lines` | result lines; links to books/GSTR-2B invoices; status, remarks, assignee, action date |
| `audit_log` | every create/update/import/delete/reconcile/export with user and before/after values |

Money columns are stored as decimal text (`DecimalText`) – no binary floating point anywhere.
Migrations are ordered in `db/database.py::MIGRATIONS`; an automatic backup is taken before
a pending migration is applied to an existing database.
