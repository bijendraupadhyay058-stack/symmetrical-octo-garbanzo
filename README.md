# FIN TAX PRO – CashBook

A secure, mobile-first **cash income & expense management PWA** for an accounting, GST, TDS, income-tax and audit practice. Built to be installed on an Android phone through Chrome and used every day, with laptop/tablet support.

- Currency **₹ (INR)**, amounts stored as **integer paise** (no rounding errors)
- Financial year **1 April – 31 March**, all dates in **Asia/Kolkata**
- Works **offline**; entries sync to the cloud when the phone reconnects

| | |
|---|---|
| Frontend | Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS 4 |
| Backend | Supabase (PostgreSQL, Auth, Storage) with Row Level Security |
| Offline | IndexedDB (`idb`) + service worker |
| Reports | PDF (`jspdf` + `jspdf-autotable`), Excel (`exceljs`), print |
| Charts | Recharts |
| Tests | Vitest (unit), SQL tests on PostgreSQL, Playwright (Android & desktop) |

## Features

**Daily work** – Dashboard (opening cash, today's cash income/expenses, closing cash, month income/expenses/net, bank & UPI balance, outstanding fees, transaction count, recent five entries, Income-vs-Expense, Monthly Collection and Expense-category charts, date & FY filters) · Add Income · Add Expense · Contra (cash ⇄ bank) · Transactions with search, filters, sorting and swipe-to-edit/cancel · floating Add button.

**Accounting** – Separate **Cash Book** and **Bank/UPI Book**: cash entries affect only cash, UPI/bank entries only their own ledger · Consolidated **Receipts & Payments** · automatic running balances (back-dated entries re-flow every later balance) · auto voucher numbers (`CR/26-27/001` cash receipt, `BR` bank/UPI receipt, `CP` cash payment, `BP` bank/UPI payment, `CT` contra) · edit with audit trail · cancel with reason (never deleted) · **cash can never go negative** because of a payment · opening-balance corrections only with explicit authorisation and a reason · year-end **books lock**.

**Clients & fees** – Client Master (ID, firm, mobile, email, GSTIN, PAN masked + re-auth to view, service type, notes) · client payment history, fees received, outstanding, monthly & yearly collections, downloadable statement · **Professional Fee Register** – fee bills are demands, not income; receipts are *adjusted* against bills so the same fee is never counted twice · WhatsApp payment reminders.

**Reports (15)** – Daily Cash Book, Monthly Cash Book, Bank/UPI Register, Receipt & Payment Statement, Income Register, Expense Register, Voucher Register, Professional Fee Register, Monthly Income & Expense Summary, Service-wise Income, Expense Category-wise, Financial Year Summary, Client-wise Income, Client Outstanding, Client Statement. Filters: custom range, current/previous month, current/previous FY, client, category, payment method, account. **PDF, Excel, Print, Share**. Cash-basis statements carry a note distinguishing them from an accrual P&L.

**More** – Recurring expense templates · receipt/bill photo attachments (private storage) · WhatsApp sharing of receipts & statements via Android's share sheet (fallback: download + wa.me) · export all transactions · manual backup & checksum-verified restore (merge, never overwrites) · automatic weekly on-device snapshots · business profile & logo · light/dark theme · auto-lock with password or fingerprint · sample-data workspace kept completely separate from real books.

## Quick start

```bash
npm install
cp .env.example .env.local      # fill in Supabase URL + anon key (or leave blank for device-only mode)
npm run dev                     # http://localhost:3000
```

Without Supabase variables the app runs in **device-only mode** (data in the browser's IndexedDB) – useful for trying it out. Tap **Explore with sample data** on the sign-in screen to see a demo practice.

Full instructions: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** (Supabase setup, environment variables, Vercel, custom domain `fintaxprojsr.in`, HTTPS, installing on Android, safe updates).

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Development server |
| `npm run build` / `npm start` | Production build (also generates the versioned service worker) |
| `npm run typecheck` | TypeScript check |
| `npm test` | Unit/integration tests (accounting, validation, fees, sync, reports, PDF/Excel, backup) |
| `npm run test:db` | Applies the Supabase migrations to a throw-away PostgreSQL and runs the SQL tests (RLS, rules, sync RPC) |
| `npm run test:e2e` | Playwright tests on a Pixel 7 profile and desktop Chrome (run `npm run build` first) |
| `npm run icons` | Regenerates PWA icons |

See **[docs/TESTING.md](docs/TESTING.md)** for the manual test checklist and **[docs/ACCOUNTING.md](docs/ACCOUNTING.md)** for the accounting rules and the sample-data walk-through.

## Project layout

```
src/app/                 Next.js routes (login, dashboard, add/*, transactions, cashbook, clients, fees, reports, settings/*, …)
src/components/          App shell, forms, report viewer, charts, UI kit
src/lib/accounting/      Ledger, running balances, validation, vouchers, fees, dashboard maths (pure functions)
src/lib/reports/         Report generators (one data model → screen, PDF, Excel)
src/lib/export/          PDF and Excel writers
src/lib/store/           IndexedDB store and domain operations (create/edit/cancel + audit)
src/lib/sync/            Offline-first sync engine and Supabase adapter
supabase/migrations/     Database schema, RLS, triggers, sync RPC, storage bucket
supabase/tests/          SQL tests
tests/  e2e/             Vitest and Playwright suites
scripts/                 Service-worker build, icon generator, DB test runner
```

## Security summary

- Only the Supabase **anon** key is used in the browser; every table is protected by **Row Level Security** – users can only reach rows of businesses they belong to. The service-role key is never needed by the app.
- Deletes are refused for all accounting tables (database trigger); audit log is append-only.
- Database triggers re-validate the key accounting rules (cash not negative, payment mode ↔ account, contra shape, books lock, voucher uniqueness, fee allocation limits) so a modified client cannot corrupt the books.
- Attachments are stored in a **private** bucket, reachable only by members via short-lived signed URLs.
- HTTPS + HSTS and security headers in production; auto-lock after inactivity; biometric unlock via WebAuthn.
- The data model has a `business_members` table with roles (`owner`, `accountant`, `viewer`) so staff users can be added later.

## GST Reconciliation desktop/CLI application (Python)

The `gst_recon/` folder contains **FIN TAX PRO – Smart GST Reconciliation & ITC Management
System**, an offline Python application that reconciles TallyPrime/custom purchase registers
with GSTR-2B/2A and produces an audit-ready Excel workbook. See
[gst_recon/README.md](gst_recon/README.md).
