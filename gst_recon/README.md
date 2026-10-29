# FIN TAX PRO – Smart GST Reconciliation & ITC Management System

*Smart GST Reconciliation. Faster Compliance. Better Accuracy.*

Offline GST reconciliation for Indian accountants, tax consultants and CA firms:
import a TallyPrime purchase register and GSTR-2B, match every invoice, see the exact
differences and ITC exposure, and download an audit-ready Excel workbook.

**Status: Phases 1 and 2 are complete.** The release includes:

* the reconciliation engine, database and imports
* exception management with manual match and unmatch
* the vendor follow-up register and cross-period tracking
* Excel and PDF reports
* a **PySide6 desktop application** and a command-line tool

Phase 3 (GSTR-3B/IMS, the ITC rule engine, security) is next.
See [docs/ROADMAP.md](docs/ROADMAP.md).

![Dashboard](docs/screenshots/dashboard.png)

## What it does

* **Clients** – client master with GSTIN validation (check digit), several GSTINs per PAN,
  data and history fully separated per client.
* **Imports** – TallyPrime purchase register (title rows, ledger-wise tax columns such as
  "Input CGST 9%" summed automatically, Debit Note vouchers), custom registers (Excel/CSV),
  GSTR-2B portal Excel (B2B, B2BA, B2B-CDNR, B2B-CDNRA) and JSON, GSTR-2A JSON/Excel, ZIP.
  Layout and heading row are detected automatically; headings are mapped by synonyms
  ("Bill No", "Supplier Invoice No.", "Integrated Tax", "State/UT Tax" …). Unknown layouts
  ask for a mapping, which can be saved as a template.
* **Import preview** – valid documents, rejected rows with reasons and original values,
  duplicate rows, rows already imported, warnings. Nothing is silently dropped or changed.
  The same file cannot be imported twice; documents already in the database are skipped
  and logged.
* **Matching** – exact, invoice-number variations (`INV/001/26` = `INV-001-26`, `PP-7` =
  `PP-0007`), date differences within a configurable tolerance, per-component amount
  differences, credit/debit notes matched separately with correct signs, amendments,
  previous-period invoices, GSTIN mismatches and fuzzy suggestions with confidence and
  reasons (never auto-confirmed). Duplicates and ambiguous candidates go to review.
  Results are deterministic and every document appears exactly once.
* **17 reconciliation categories**, exception status/remarks/assignee/action date with a
  full audit trail, carried forward when a period is re-run.
* **Reports** – one Excel workbook with 17 sheets (executive summary with formula
  cross-checks, complete reconciliation, category sheets, supplier-wise and month-wise
  summaries with charts, GSTR-3B working, pending action register with status drop-down,
  source files and settings) plus a PDF summary.
* **Safety** – local SQLite database, exact decimal money, transactional imports and runs
  (cancel = nothing saved), backups before migrations, backup/restore commands, audit log.
  No GST portal credentials are needed and no data leaves the computer.

## Install

```bash
cd gst_recon
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # provides the `fintax-gst` command
```

Python 3.12+ is required. To build a Windows `.exe` see [docs/BUILD_WINDOWS.md](docs/BUILD_WINDOWS.md).

## Try the demo (2 minutes)

```bash
fintax-gst demo --out demo_output
```

This creates a fresh database, generates the sample files, imports March and April books
and April GSTR-2B, reconciles April 2025 and writes the Excel and PDF reports into
`demo_output/reports/`. The sample files and the expected category of every scenario are
in [sample_data/](sample_data/) ([EXPECTED_RESULTS.md](sample_data/EXPECTED_RESULTS.md)).

## Desktop application

```bash
python -m fintax_gst.ui            # or: fintax-gst-gui     (Windows: FinTaxPro.exe)
```

The header has selectors for the **client** and the **financial year**.
The navigation on the left opens these pages:

| Page | What you do there |
|---|---|
| **Dashboard** | 12 cards: invoices, taxable value, ITC (books and GSTR-2B), fully and partially matched, missing on each side, ITC difference, ITC at risk, duplicates, pending. 4 charts: monthly ITC, matching %, top supplier differences, ITC at risk by category. A financial-year overview by month. |
| **Reconcile** | The 10-step journey. Pick the client and the period (month, quarter, FY or custom range). Import the purchase register and GSTR-2B (plus earlier books or GSTR-2A, optional). Validate the imported files, set tolerances, start the reconciliation, review the summary, go to exceptions, export Excel and PDF. Long steps show a progress bar with **Cancel**; cancelling saves nothing. |
| **Exceptions** | Colour-coded category filters with counts, search, and a status filter. Books and GSTR-2B side by side with every difference and reason. Set status, assignee, action date and remarks. **Confirm match**, **Manual match** (Ctrl+click two lines), **Unmatch**, **Pending clarification**. Attach evidence. Line history. |
| **Suppliers** | Supplier summary with all sort options and drill-down to invoices. Vendor follow-up register (contact, status, next follow-up date, remarks); due follow-ups are flagged. |
| **Open items** | Every document without a confirmed counterpart, across all periods, listed once. Double-click for its history across runs. |
| **History** | All runs with their summaries. Open a run, or re-run a period: review work and manual decisions carry forward. Lists the active manual decisions. |
| **Imports** | Imported files with SHA-256, counts and the full import log (including rejected rows). Import a file here, or remove an import no run has used. |
| **Clients** | Client master (GSTIN validated, PAN and state derived). |
| **Settings** | Default tolerances, backup now, restore, data folder. |

Every import opens a **preview** first, with tabs for documents, issues and the column
mapping. If headings aren't recognised, or you choose *Change column mapping…*, the
**mapping screen** opens. Drag file columns onto fields, or select a field and
double-click a column. You can save the mapping as a template.

Manual decisions are applied to the open run straight away and stored. Every later run
re-applies them (see [docs/RECONCILIATION_LOGIC.md](docs/RECONCILIATION_LOGIC.md) §8).

| Reconcile | Exceptions |
|---|---|
| ![Reconcile](docs/screenshots/workflow.png) | ![Exceptions](docs/screenshots/exceptions.png) |
| **Suppliers** | **Import preview** |
| ![Suppliers](docs/screenshots/suppliers.png) | ![Import preview](docs/screenshots/import_preview.png) |

## Everyday workflow from the command line

```bash
# 1. Client (once)
fintax-gst client add --gstin 27AAPFU0939F1ZV --name "Shree Ganesh Traders" --fy 2025-26

# 2-3. Purchase register – preview first, then import
fintax-gst import --client 27AAPFU0939F1ZV --source books --file "Purchase Register Apr.xlsx" --preview
fintax-gst import --client 27AAPFU0939F1ZV --source books --file "Purchase Register Apr.xlsx"

# 4. GSTR-2B (period read from the file; give --period 2025-04 if it cannot be detected)
fintax-gst import --client 27AAPFU0939F1ZV --source gstr2b --file returns_R2B_042025.zip

# 5-8. Reconcile and export
fintax-gst reconcile --client 27AAPFU0939F1ZV --from 2025-04 --export reports/
#      quarter: --from 2025-04 --to 2025-06     full year: --fy 2025-26
#      options: --date-tolerance 3|7|15  --amount-tolerance 1.00  --no-fuzzy

# 9. Work the exceptions
fintax-gst show --run 1 --pending --reasons
fintax-gst update-line --run 1 --line 12 --status "Supplier Follow-up Required" \
    --remarks "Mailed on 20-May" --assign Asha --action-date 2025-05-20

# 10. Re-export after updates
fintax-gst export --run 1 --out reports/
```

Manual decisions, vendors, evidence and open items:

```bash
fintax-gst match confirm --run 1 --line 2 --remarks "Supplier confirmed typo"
fintax-gst match pair    --run 1 --line 11 --with 22 --remarks "Same purchase"
fintax-gst match unmatch --run 1 --line 27 --remarks "Different consignment"
fintax-gst match clarify --run 1 --line 10 --remarks "Asked client for invoice copy"
fintax-gst vendor --client 1 --gstin 27AABCM1234K1ZM --status "Mail sent" --next 2025-05-10
fintax-gst attach --run 1 --line 11 --file supplier_reply.pdf --description "Supplier reply"
fintax-gst open-items --client 1
```

Other commands: `client list [--pan]`, `imports --client X [--remove ID]`, `runs --client X`,
`backup [--to file]`, `restore file`, `sample-data --out dir`. Use `--db path` to work with
a specific database file.

### When headings are not recognised

The import stops and lists the columns it found. Create a mapping file:

```json
{"fields": {"supplier_gstin": ["Party GSTIN"], "invoice_no": ["Bill Ref"],
            "invoice_date": ["Bill Dt"], "taxable_value": ["Basic"],
            "igst": ["IGST"], "cgst": ["CGST"], "sgst": ["SGST"]}}
```

and import with `--mapping mapping.json --save-template "Client X register"`; next time use
`--template "Client X register"`. Several columns may be listed for one amount field; they
are added together.

## Tests and benchmark

```bash
python -m pytest              # engine, importers, services, reports, CLI and desktop UI (offscreen)
python scripts/benchmark.py 10000 50000
```

Measured on the 4-core Linux build container used for development (synthetic data:
80 % exact, plus format variations, date/amount differences, missing, duplicates, typos):

| Invoices per side | Import (both files) | Reconcile + save | Excel (17 sheets) + PDF | Total |
|---:|---:|---:|---:|---:|
| 10,000 | 2.8 s | 2.0 s | 14.2 s | 19.0 s |
| 50,000 | 15.7 s | 13.1 s | 80.1 s | 108.9 s |

These Phase 1 measurements cover the engine and the reports.

Desktop app, measured on the same machine:

| Lines in the run | Start | Switch page | Save a review | Search filter |
|---:|---:|---:|---:|---:|
| 10,000 | 1.4 s | ≤ 0.8 s | 0.1 s | 0.1 s |
| 50,000 | 7.0 s | ≤ 2.7 s (first visit) | 0.2 s | 0.4 s |

Timings on an office PC will differ. Run the script on the target machine.

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – layers, file structure, database
* [docs/RECONCILIATION_LOGIC.md](docs/RECONCILIATION_LOGIC.md) – exactly how matching works
* [docs/BUILD_WINDOWS.md](docs/BUILD_WINDOWS.md) – Windows executables (desktop and CLI)
* [docs/ROADMAP.md](docs/ROADMAP.md) – Phase 2, Phase 3, Android/web

## Professional note

Categories and "ITC at risk" are indicators for professional review. Appearance in
GSTR-2B does not by itself establish ITC eligibility, and the software does not issue
legal conclusions or perform any action on the GST portal.
