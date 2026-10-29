# FIN TAX PRO – Architecture

## Layers

```
            ┌───────────────────────────────────────────────────────────┐
            │ cli.py (argparse)            ui/ (PySide6 desktop)         │  presentation
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
│   ├── itc/                   ITC module (pure logic, no database)
│   │   ├── rules.py           effective-dated rules with statutory references
│   │   ├── deadlines.py       Section 16(4) time limit
│   │   ├── review.py          document flags, claim state, ITC buckets
│   │   ├── table4.py          GSTR-3B Table 4 working, classified differences
│   │   ├── annual.py          GSTR-9 Table 8 (8A–8D)
│   │   └── ims.py             IMS vs books vs GSTR-2B
│   ├── engine/
│   │   ├── matcher.py         reconciliation passes and integrity checks
│   │   └── summary.py         dashboard, category, supplier, month summaries
│   ├── db/
│   │   ├── models.py          ORM tables (Decimal stored as exact text)
│   │   └── database.py        engine, migrations, backup/restore
│   ├── ui/                    PySide6 desktop app
│   │   ├── app.py             main window, header (client/FY), navigation, entry point
│   │   ├── state.py           shared state: services, current client/FY/run, run cache
│   │   ├── workers.py         QThread runner with progress dialog and safe Cancel
│   │   ├── import_flow.py     preview → re-map → confirm → save
│   │   ├── widgets.py         KPI cards, table models, filters, lazy pages
│   │   ├── charts.py          Qt Charts for the dashboard
│   │   ├── theme.py           colours and stylesheet
│   │   ├── dialogs/           import preview, column mapping, client form
│   │   └── pages/             dashboard, workflow, exceptions, suppliers,
│   │                          history + open items, clients, imports, settings
│   ├── services/
│   │   ├── followup.py        vendor follow-up register, evidence attachments
│   │   ├── itc.py             rules, reviews, claim register, IMS, Table 4, annual
│   │   ├── gstr3b.py          GSTR-3B import (supersede, never overwrite)
│   │   ├── auth.py            users, scrypt passwords, lockout, roles, permissions
│   │   ├── security.py        encrypted backups, auto-backup/retention, purge, audit export
│   │   ├── tracking.py        open items, document history, FY overview, period scope
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
| `match_decisions` (v2) | user MATCH / REJECT decisions applied to every later run |
| `vendors` (v2) | supplier contacts and follow-up status per client |
| `attachments` (v2) | evidence files, copied into `attachments/` and verified by SHA-256 |
| `users`, `app_settings` (v3) | login accounts (scrypt hashes, lockout) and application settings |
| `itc_rules`, `itc_reviews`, `itc_claims` (v3) | rule overrides, reviewer decisions, claim/reverse/reclaim register |
| `gstr3b_entries`, `itc_other` (v3) | GSTR-3B Table 4 values (superseded, never overwritten); ISD credits and bills of entry |
| `invoices.description`, `invoices.ims_action` (v3) | narration for rules; IMS action for IMS records |

**Desktop threading.** Imports, reconciliation and export run on a `QThread` behind a
progress dialog. Services check the `CancelToken` between batches and write inside one
transaction, so Cancel saves nothing. SQLite connections may move between threads
(`check_same_thread=False`), but a session is never shared.

**UI performance.** All pages share one copy of the loaded run (`AppState.run_context`).
Hidden pages refresh only when they are shown. Saving a review updates the line in memory
instead of reloading the run. Column widths are worked out from a sample of 150 rows.
At 50,000 lines, saving a review takes 0.2 s and opening a page for the first time takes up to 2.7 s.

Money columns are stored as decimal text (`DecimalText`) – no binary floating point anywhere.
Migrations are ordered in `db/database.py::MIGRATIONS`; an automatic backup is taken before
a pending migration is applied to an existing database.
