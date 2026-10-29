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

## Next
* Import GSTR-1 advance tables (11A/11B) for GSTR-9 4F, and GSTR-3B Table 6.1 payments
  for Table 9 "paid".
* GSTR-9C reconciliation statement (books turnover and tax vs GSTR-9).
* Sign the Windows build with the firm's code-signing certificate.

## Android / web expansion
1. ✅ Read-only, responsive web view (`fintax_gst/web/`, FastAPI) on the existing
   services, installable on Android from the browser.
2. ✅ Client-authorised synchronisation through encrypted packages; per-client data only.
3. ✅ Uploads through the same import pipeline from the web view (opt-in); PostgreSQL for
   shared deployments, with SQLite kept for the offline desktop.
4. GST data is never sent to external AI services.
