# Roadmap

## Phase 1 – Functional MVP (this release) ✅
Project structure, SQLite database with migrations, client master (multiple GSTINs per PAN),
TallyPrime / custom register / GSTR-2B / GSTR-2A import (Excel, CSV, JSON, ZIP) with
automatic layout detection, column mapping and saved templates, import preview with
rejected/duplicate/repeated rows, normalisation, the full matching engine (levels 1–5,
duplicates, credit/debit notes, amendments, previous period, GSTIN mismatch, fuzzy
suggestions), exception status updates with audit trail, 17-sheet Excel workbook, PDF
summary, backup/restore, CLI, demo data, 105 automated tests, benchmark.

## Phase 2 – Professional application
* PySide6 desktop app (navy/white/teal) on the same services: client selector, 10-step
  workflow wizard, import preview grid, drag-and-select column mapping, progress bar with
  Cancel (QThread + `CancelToken`), dashboard cards and charts (monthly ITC, match %,
  vendor mismatches, unmatched exposure), colour-coded category filters.
* Exception workspace: inline status/remarks/assignee/action date, evidence attachments,
  manual match / unmatch / correction with audit history (category *Manually Matched*).
* Vendor follow-up register and supplier-wise drill-down; reconciliation history browser;
  cross-period tracking of unresolved items.
* Windows GUI executable (PyInstaller, windowed) and installer.

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
