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

## Phase 4 – second development phase (from the specification)
* GSTR-1 vs GSTR-3B and sales register vs GSTR-1 reconciliation (same engine; outward
  source types).
* Annual GST reconciliation dashboard across all clients, and a client-wise compliance
  summary.
* Automated supplier discrepancy letters (Word/PDF from the vendor register).
* Period-wise audit working papers pack.
* Portal Table 8A import (when a stable export exists), to replace the computed 8A.

## Android / web expansion
1. Add `fintax_gst/api/` – FastAPI routers calling the existing services (no engine changes).
2. Swap SQLite for PostgreSQL through SQLAlchemy for multi-user/cloud deployments; keep
   SQLite for the offline desktop.
3. Responsive web dashboard (read-only first: dashboards, reports, pending register),
   installable as a PWA on Android; uploads go through the same import pipeline.
4. Client-authorised synchronisation from desktop to cloud, per-client isolation enforced
   in the service layer; GST data is never sent to external AI services without explicit
   permission.
