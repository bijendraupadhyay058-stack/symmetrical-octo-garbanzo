# Changelog

## 1.2.0 (versionCode 3)

**New**
- **Invoices & bills** — record sales invoices (what customers owe you) and purchase bills (what you owe),
  with automatic numbering per financial year (INV/26-27/001, BILL/26-27/001), invoice and due dates
  (on receipt / 7 / 15 / 30 / 45 / 60 days) and status: open, partly paid, overdue by n days, paid,
  cancelled. Invoices never change account balances; **Record receipt / Record payment** creates the
  income or expense entry and applies it in one step, or apply part of an entry you already recorded.
  One entry can settle several invoices.
- **Outstanding & Ageing report** (PDF/Excel) as at any date: party-wise unpaid amounts and an ageing
  table (not due, 1–30, 31–60, 61–90, 90+ days overdue).
- Dashboard **Receivables & payables** card, outstanding per party, and invoices linked from entries.
- **Alerts** (opt-in, Settings › General & financial): daily notification for overdue or due-soon
  invoices; budget notifications at 80 % and when exceeded (once per level per month). Saving an entry
  that crosses a budget level also shows an immediate message.
- **Home-screen widget** with Income / Expense / Transfer buttons. The balance is shown only if you
  turn it on in Settings › Security, and never while the app lock is on.

**Improved**
- Recording a payment opens a full screen form instead of a dialog.
- Choices inside dialogs (parent category, party type, move entries to) expand in place.
- Widget buttons and notifications open the right screen even when the app is already running.

**Data**
- Database v2 → v3 adds `invoices` and `allocations` (verified by `MigrationTest`). Backups include
  them; 1.0 and 1.1 backups still restore.

## 1.1.0 (versionCode 2)

**New**
- **Recurring entries** for rent, salary, subscriptions and regular transfers: daily, weekly, monthly,
  quarterly or yearly, every N periods, optional end date, pause/resume. Each schedule either posts
  automatically (also catching up dates missed while the app was closed) or waits on the dashboard
  for **Post / Skip** — useful when the amount varies. Start one from any entry with **Make recurring**.
  Month-end dates never drift (31 Jan → 28 Feb → 31 Mar).
- **Monthly budgets** per expense category and cashbook, with progress on the dashboard and a
  Budgets screen (previous / next month). Sub-category spending counts towards its parent.
- **Automatic backups** into a folder chosen once with the system picker (phone, SD card or a cloud
  drive), daily or weekly, keeping the latest 3/5/10/30 copies. The password is kept in the
  Keystore-encrypted store; failures are shown on the Backup screen.
- **Release signing** with your own key via `keystore.properties` (see README).

**Improved**
- Entries created by a schedule show a repeat icon and link back to it.
- Progress bars put long category names and amounts on separate lines.
- Backups now include schedules and budgets; 1.0 backups still restore.

**Data**
- Database v1 → v2 migration adds `recurring`, `budgets` and `transactions.recurring_id`; existing
  data is untouched (verified by `MigrationTest`).

## 1.0.0 (versionCode 1)

First release: cashbooks, accounts, income/expense/transfer entries with attachments, dashboard,
history with search and filters, 10 reports with PDF/Excel export, encrypted backup & restore,
PIN/biometric lock, recycle bin, English and Hindi, sample data.
