# Roadmap

## Phase 1 – Functional MVP ✅
Project structure, SQLite database with migrations, client master (multiple GSTINs per PAN),
TallyPrime / custom register / GSTR-2B / GSTR-2A import (Excel, CSV, JSON, ZIP) with
automatic layout detection, column mapping and saved templates, import preview with
rejected/duplicate/repeated rows, normalisation, the full matching engine (levels 1–5,
duplicates, credit/debit notes, amendments, previous period, GSTIN mismatch, fuzzy
suggestions), exception status updates with audit trail, 17-sheet Excel workbook, PDF
summary, backup/restore, CLI, demo data, 105 automated tests, benchmark.

## Phase 2 – Professional application ✅
* PySide6 desktop app in navy, white and teal, built on the same services. It has:
  * a client and financial-year selector
  * the 10-step Reconcile page
  * an import preview with documents, issues and the column mapping used
  * a column-mapping screen where you drag or pick columns
  * a progress bar with a safe Cancel
  * a dashboard with 12 cards, 4 charts and a financial-year overview
* Exceptions page:
  * colour-coded category filters and search
  * books and GSTR-2B side by side, with differences
  * status, remarks, assignee and action date for each line
  * confirm, manual match, unmatch and pending-clarification actions
  * evidence attachments (checked by SHA-256) and line history
* Manual decisions stay in force for every re-run (schema v2, `match_decisions`).
* Supplier page: sorting, invoice-level drill-down and a vendor follow-up register.
  Follow-up remarks are carried into the Excel supplier sheet.
* Reconciliation history, re-runs, and a list of open items across periods.
  Remarks follow a document into later periods.
* Windowed PyInstaller build (`FinTaxPro.exe`) with `--smoke-test`.
* Still to do: an installer (e.g. Inno Setup) and a signed executable.

## Phase 3 – Advanced GST features ✅
* GSTR-3B import (portal JSON and template). Table 4 working of GSTR-2B vs books / claim
  register vs filed, with differences classified as statutory, timing or accounting.
* ITC claim register: claim, reverse and reclaim with limits, so nothing is counted twice
  across periods.
* Rule engine with effective dates and statutory references:
  * Section 17(5) indicators, 16(2)(aa), the 16(4) time limit and Rule 36(4) schedule
  * RCM, credit notes, IMS, and Rule 37 (off by default)
  * configurable for all clients or per client, with confirm/dismiss decisions
* ISD credits and imports from GSTR-2B.
* IMS download import and comparison.
* GSTR-9 Table 8 (8A–8D), month-wise ITC and the annual workbook.
* Login with scrypt hashes and lockout, four roles, encrypted backups, automatic backup
  with retention, secure delete and client purge, audit export.
* Inno Setup installer script.

## Phase 4 – second development phase ✅
* Sales register vs GSTR-1 reconciliation, using the same engine with outward source
  types.
* GSTR-1 section totals and the sales register vs GSTR-3B Table 3.1 liability working:
  possible short payment, Rule 88C/88D limits, segment differences.
* Client-wise compliance summary (PDF) and an annual dashboard across all clients (Excel,
  desktop, web).
* Supplier discrepancy letters (Word, PDF, unsent e-mail draft), with a letter register
  and vendor follow-up update.
* Period-wise audit working-paper ZIPs with manifest, integrity check and reviewer sign-off.
* Client-authorised encrypted sync packages through a cloud folder, with conflict and
  replay protection.
* Read-only, mobile-friendly web interface (FastAPI) with login, installable on Android.
* Schema v4.

## Phase 5 ✅
* GSTR-9 Table 8A document details import: 8A on the portal basis, comparison with the
  computed 8A, and a books vs Table 8A reconciliation for the year.
* Returns calendar for monthly and QRMP filers (22nd/24th by state, IFF, PMT-06, GSTR-9),
  with due-date extensions recorded from notifications; upcoming and overdue returns
  across clients.
* PostgreSQL support with snapshot backups, restore, `db-copy` from SQLite, and the full
  test suite run on PostgreSQL.
* Opt-in uploads from the web view (preview, then confirm).
* Authenticode signing step in the Windows build.

## Phase 6 ✅
* Fixed: the `fintax_gst/reports` package had been excluded by `.gitignore`; CI now
  passes on a fresh checkout.
* GSTR-9 working for Tables 4, 5, 6, 7 and 9 from GSTR-1, GSTR-3B and the sales register,
  with amendments resolved against their originals.
* Column mapping in the web view; saved templates are tried automatically everywhere.
* CI: Ubuntu and Windows tests, the PostgreSQL suite, and a Windows job that builds,
  smoke-tests and packages the executables and installer.

## Phase 7 ✅
* GSTR-1 advances (11A/11B) into the GSTR-1 vs GSTR-3B liability and GSTR-9 4F.
* GSTR-3B Table 6.1 payments (cash, ITC, interest, late fee) into GSTR-9 Table 9.
* GSTR-9C reconciliation statement: Tables 5, 7, 9 and 12 with audited figures entered
  per client and year (schema v6), defaults clearly marked, reasons recorded.

## Phase 8 ✅
* GSTR-9 Tables 10–14 from the next year's GSTR-1 and claim register; earlier-year amendments
  excluded from 4K/4L.
* GSTR-9 Table 17 from the GSTR-1 HSN summary (both layouts), checked against the sections.
* GSTR-9C Table 14 with an expense-ledger import (keyword mapping, preview, audited).

## Phase 9 ✅
* HSN / unit / quantity columns in purchase registers; lines merged by rate or HSN (same-rate,
  different-HSN lines are no longer reported as duplicates); GSTR-9 Table 18.
* GSTR-9 Tables 15 and 16 entered, audited, in the workbook, desktop and CLI.

## Phase 10
* ✅ Sales register vs e-invoices (IRP) and vs e-way bills (schema v9): cancelled IRNs and
  e-way bills kept and explained, latest import wins, e-way bill threshold setting, review
  work carried forward within the same comparison only.
* ✅ TDS/TCS credits received (schema v10): import, statement against the sales register and the
  statutory rates, pending acceptance, annual workbook sheet.
* ✅ GSTR-9 draft JSON for the offline tool, with a mapping that marks what is included, what
  the tool computes and what must be entered there (never guessed).
* ✅ Multi-user hardening (schema v11): versioned review lines – concurrent saves refused with
  who/when, never lost; per-user activity; concurrency load test on PostgreSQL in CI.

## Phase 11
* ✅ Interest (section 50) and late fees (section 47): filing register, settlements, DRC-03
  summary (schema v12).
* ✅ Supplier compliance scores: missing, late, mismatched, unavailable and amended documents;
  risk bands, reasons, ITC at risk.
* ✅ GST notices register and Word reply drafts for DRC-01B, DRC-01C and ASMT-10 (schema v13):
  facts from the reconciliations, everything else highlighted for the preparer.

## Phase 12
* ✅ Direct Tally import (XML interface, live or file), with a Tally simulator for testing.
* Batch processing for many clients.
* Firm work dashboard.

## Next
* Sign the Windows build with the firm's code-signing certificate.

## Android / web expansion
1. ✅ Read-only, responsive web view (`fintax_gst/web/`, FastAPI) on the existing
   services, installable on Android from the browser.
2. ✅ Client-authorised synchronisation through encrypted packages; per-client data only.
3. ✅ Uploads through the same import pipeline from the web view (opt-in); PostgreSQL for
   shared deployments, with SQLite kept for the offline desktop.
4. GST data is never sent to external AI services.
