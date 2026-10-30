# FIN TAX PRO – Architecture

## Layers

```
            ┌───────────────────────────────────────────────────────────┐
            │ cli.py (argparse)   ui/ (PySide6 desktop)   web/ (FastAPI) │  presentation
            │                                                            │
            ├───────────────────────────────────────────────────────────┤
            │ services/  clients · imports · reconciliation · reports ·  │  use-cases, transactions, audit
            │   outward · compliance · letters · papers · sync · auth    │
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
│   ├── cli.py                 command-line interface (+ cli_phase3.py, cli_phase4.py, cli_phase5.py)
│   ├── samples.py             demo datasets + expected outcomes (samples_outward.py: sales/GSTR-1)
│   ├── outward/liability.py   GSTR-1 sections → GSTR-3B Table 3.1, liability working (pure)
│   ├── compliance/summary.py  month status (RAG), client compliance (pure)
│   ├── compliance/calendar.py due dates: monthly, QRMP, annual, recorded extensions (pure)
│   ├── gstr9/working.py       GSTR-9 Tables 4–7 and 9 from GSTR-1, GSTR-3B and books (pure)
│   ├── gstr9/reconciliation_9c.py  GSTR-9C Tables 5, 7, 9, 12, 14 (pure)
│   ├── gstr9/expenses.py      expense-ledger import for GSTR-9C Table 14
│   ├── gstr9/entered.py       GSTR-9 Tables 15 and 16 (entered figures)
│   ├── letters/               supplier letter content (pure) and Word/PDF/e-mail rendering
│   ├── web/                   read-only FastAPI app and templates
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
│   │                          history + open items, clients, imports, settings, itc, returns,
│   │                          security, phase4 (sales & GSTR-1, compliance, letters, sync)
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
│   │   ├── reports.py         export Excel + PDF for a run (inward or outward)
│   │   ├── outward.py         GSTR-1 summaries, sales documents, liability working
│   │   ├── compliance.py      client summary, annual dashboard
│   │   ├── letters.py         supplier letters and letter register
│   │   ├── papers.py          working-paper packages, review sign-off, verification
│   │   ├── sync.py            client authorisation, encrypted sync packages
│   │   ├── calendar.py        due-date extensions, upcoming returns across clients
│   │   ├── gstr9.py           GSTR-9 working for a client and year
│   │   ├── gstr9c.py          GSTR-9C inputs (audited figures, reasons) and statement
│   │   └── common.py          audit log, conversions
│   └── reports/
│       ├── excel_report.py    17-sheet workbook
│       ├── pdf_report.py      PDF summary
│       ├── outward_sheets.py  GSTR-1 vs GSTR-3B and GSTR-1 section sheets
│       ├── compliance_report.py  annual dashboard workbook, client compliance PDF
│       └── gstr9_sheets.py    GSTR-9 Tables 4–7, 9 and amendments sheets
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
| `invoices.supply_type`, `gstr3b_entries.taxable`, `gstr1_summary` (v4) | outward supply type; Table 3.1 taxable values; GSTR-1 section totals |
| `letters`, `working_papers` (v4) | letter register; working-paper packages with SHA-256 and sign-off |
| `sync_authorizations`, `sync_state` (v4) | client consent for sync; last export/import sequence and origin |
| `due_date_overrides` (v5) | due-date extensions recorded from CBIC notifications |
| `gstr9c_inputs` (v6) | GSTR-9C figures per audited accounts and reasons, per client and year |
| `gstr1_hsn` (v7) | GSTR-1 Table 12 HSN summary lines (GSTR-9 Table 17) |
| `invoices.hsn_json` (v8) | HSN lines of imported documents (GSTR-9 Table 18) |
| `invoices.irn`, `ref_no`, `ref_status` (v9) | e-invoice IRN / acknowledgement number, e-way bill number, ACTIVE or CANCELLED |

**Database engines.** `Database` opens a SQLite file (default) or a server URL such as
`postgresql+psycopg://user@host/db` (`--db`, `FINTAX_DB_URL`). Attachments, uploads and
backups live in `Database.data_dir`. Backups are always SQLite files: SQLite's online
backup API, or a repeatable-read snapshot of a server database. `copy_database` moves
data between engines with ids kept.

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
