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

## Phase 3 – Advanced GST features
* GSTR-3B import, Table 4 working, GSTR-2B vs 3B vs books; ITC reversed/reclaimed tracking.
* ITC rule engine with effective dates and source references (Section 17(5) blocked credit
  indicators, Section 16(4) time-limit exposure, RCM, ISD, imports) – flags for review only.
* IMS export import and comparison (Accepted / Rejected / Pending / Deemed accepted).
* GSTR-9 Table 8A and annual dashboard.
* Login, roles and permissions, encrypted backups, retention and secure deletion.

## Android / web expansion
1. Add `fintax_gst/api/` – FastAPI routers calling the existing services (no engine changes).
2. Swap SQLite for PostgreSQL through SQLAlchemy for multi-user/cloud deployments; keep
   SQLite for the offline desktop.
3. Responsive web dashboard (read-only first: dashboards, reports, pending register),
   installable as a PWA on Android; uploads go through the same import pipeline.
4. Client-authorised synchronisation from desktop to cloud, per-client isolation enforced
   in the service layer; GST data is never sent to external AI services without explicit
   permission.
