# Changelog

## 1.6.0 (versionCode 7)

**New**
- **Quotations / estimates** (Invoices & bills › Quotations): itemised with GST like invoices, numbered
  QT/26-27/001, with a valid-until date and their own QUOTATION PDF. Status Open, Expired, Declined or Converted.
  They never change balances, receivables, stock or GST reports.
- **Convert to invoice** in one tap: the customer, place of supply, items (with their saved-item links),
  description and notes are copied into a new invoice. The invoice shows "From quotation …"; deleting it re-opens
  the quotation.
- **UPI payment QR code** for unpaid sales invoices: shown on the invoice screen and printed on the invoice PDF.
  Any UPI app opens it with your UPI ID, the balance due and the invoice number filled in.
- The UPI ID in the business profile is now checked (name@bank); shared invoice text includes "Pay by UPI".

**Data**
- Database v6 → v7 adds the converted-invoice link. Backups include quotations; older backups still restore.

## 1.5.0 (versionCode 6)

**New**
- **Products & services** (Settings › Products & services): name, goods or service, HSN/SAC, unit, sale and
  purchase rate, GST rate, opening stock and reorder level. Search, "Low stock only" filter, archive.
- On an invoice or bill line, **pick an item** to fill description, HSN/SAC, unit, rate and GST rate. The line
  shows stock in hand and warns when a sale is more than you have.
- **Stock on hand** derived from purchase bills (+), sales (−), credit notes (back in) and **stock adjustments**
  (damage, counting differences). Debit notes and cancelled documents don't move stock.
- **Low stock** card on the dashboard.
- Reports: **Stock summary** (opening, in, out, closing, value) and **Item-wise sales** (quantity, taxable
  value, GST), with PDF and Excel export.

**Data**
- Database v5 → v6 adds `catalog_items`, `stock_adjustments` and an optional item link on invoice lines.
  Backups include items and adjustments; older backups still restore.

## 1.4.0 (versionCode 5)

**New**
- **Credit notes and debit notes** against an invoice or bill: open the invoice and tap Credit note (goods
  returned, discount, overcharge) or Debit note (amount charged short, extra charge). Itemised with GST like
  invoices — a credit note starts from the invoice's items so you just reduce quantities. Numbered per
  financial year (CN/26-27/001, DN/26-27/001). Notes adjust what is owed and the GST summary, never balances.
- **Refunds**: when a credit note leaves more paid than owed, the invoice shows **Refund due**; Record refund
  creates the money-out entry (or money-in, for a supplier refund) and links it.
- **CREDIT NOTE / DEBIT NOTE PDF** showing the original invoice number and date, labelled "Note no." / "Note date".
- **Logo and signature** images (Business profile) printed on invoices and notes; included in backups.

**Data**
- Database v4 → v5 adds document type and original-invoice link to `invoices`. Backups include notes and
  branding images; older backups still restore.

## 1.3.0 (versionCode 4)

**New**
- **Business profile** (Settings): name, address, GSTIN, state, phone, email, bank and UPI details, invoice
  terms and signatory — printed on invoices. The state fills in automatically from the GSTIN.
- **Itemised GST invoices and bills**: lines with HSN/SAC, quantity (up to 3 decimals), unit, rate, discount %
  and GST rate (0, 0.25, 3, 5, 12, 18, 28 or 40 %). CGST + SGST within the seller's state, IGST for other states,
  based on the **place of supply** (defaults to the party's state). Optional round-off to the nearest rupee.
  Live totals while editing. Invoices entered as a single amount still work.
- **Tax invoice PDF** — save or share an A4 tax invoice with seller and buyer GSTIN/state, items (headings
  repeated on every page), GST summary by rate, totals, round-off, paid and balance due, amount in words
  (Indian system: lakh, crore), bank/UPI details, terms and signatory.
- **GST Summary report** — output tax on sales invoices vs input tax on purchase bills, by rate, split into
  CGST, SGST and IGST, with net tax.
- **GSTIN validation** with the official check digit (business profile and parties); party **state** field.

**Data**
- Database v3 → v4 adds `invoice_items`, place of supply, round-off and party state (filled from existing
  GSTINs). Backups include items, party states and the business profile; older backups still restore.

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
