# FIN TAX PRO – Smart GST Reconciliation & ITC Management System

*Smart GST Reconciliation. Faster Compliance. Better Accuracy.*

Offline GST reconciliation for Indian accountants, tax consultants and CA firms:
import a TallyPrime purchase register and GSTR-2B, match every invoice, see the exact
differences and ITC exposure, and download an audit-ready Excel workbook.

**Status: Phase 1 (functional MVP) complete** – reconciliation engine, database, imports,
exception tracking, Excel/PDF reports and command-line interface. The PySide6 desktop
interface is Phase 2 and uses the same services (see [docs/ROADMAP.md](docs/ROADMAP.md)).

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

## Everyday workflow

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
python -m pytest              # 105 tests
python scripts/benchmark.py 10000 50000
```

Measured on the 4-core Linux build container used for development (synthetic data:
80 % exact, plus format variations, date/amount differences, missing, duplicates, typos):

| Invoices per side | Import (both files) | Reconcile + save | Excel (17 sheets) + PDF | Total |
|---:|---:|---:|---:|---:|
| 10,000 | 2.8 s | 2.0 s | 14.2 s | 19.0 s |
| 50,000 | 15.7 s | 13.1 s | 80.1 s | 108.9 s |

Timings on an office PC will differ; run the script on the target machine.

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – layers, file structure, database
* [docs/RECONCILIATION_LOGIC.md](docs/RECONCILIATION_LOGIC.md) – exactly how matching works
* [docs/BUILD_WINDOWS.md](docs/BUILD_WINDOWS.md) – Windows executable
* [docs/ROADMAP.md](docs/ROADMAP.md) – Phase 2, Phase 3, Android/web

## Professional note

Categories and "ITC at risk" are indicators for professional review. Appearance in
GSTR-2B does not by itself establish ITC eligibility, and the software does not issue
legal conclusions or perform any action on the GST portal.
