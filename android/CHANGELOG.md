# Changelog

## 1.13.0 (versionCode 14)

**New**
- **Excel statements**: import .xlsx files and the HTML files many banks download with an ".xls" name, as well as CSV.
  Dates stored as Excel date cells are read correctly. Old binary .xls files get a clear "save as .xlsx or CSV" message.
- **Learned categories**: when you give an entry added from a statement a category (say "SMS CHARGES INCL GST 0525"
  → Bank charges), Cashbook remembers the wording. Next time a line worded the same way is added, it gets that
  category — shown as "→ Bank charges" before you add it. Review or delete what was learned in
  Settings › Statement categories.

**Fixed**
- Test reliability: UI tests now let background work run while they wait (the cause of the intermittent
  statement-import failures), and Settings tests scroll to rows before tapping them.

**Data**
- Database v9 → v10 adds learned category rules. Backups include them; older backups still restore.

## 1.12.0 (versionCode 13)

**New**
- **Import bank statement (CSV)** on the Bank reconciliation screen. Works with the usual net-banking layouts
  (withdrawal / deposit columns, a signed amount, or amount with Dr/Cr), Indian date and number formats, account details
  above the table and totals below it. The statement date and closing balance are filled in, entries that match
  (same amount, date within 4 days, reference preferred) are ticked, and lines Cashbook doesn't have — bank charges,
  interest, a forgotten payment — are listed with **Add** (saved uncategorised for you to sort later).

**Fixed**
- After finishing a reconciliation the imported statement is cleared, and lines matching entries that were already
  cleared are never offered as missing, so nothing gets added twice. The Add button can't be tapped twice.
- Test reliability: several UI and repository tests waited on the wrong condition or tapped under a message or
  off-screen; they now wait for the exact state they check.

**Data**
- No database change.

## 1.11.0 (versionCode 12)

**New**
- **Bank reconciliation** (Settings › Bank reconciliation): choose the account, enter the statement date and closing
  balance, and tick the entries on the statement. The difference updates as you tick; **Finish** is available when it
  reaches zero and marks those entries cleared. Each side of a transfer is cleared on its own account. History of
  past reconciliations; an entry's detail shows when it was reconciled, with an undo.
- **Cash count** (Settings › Cash count): count notes and coins (₹500 to ₹1) for a cash account and compare with the
  balance in the books. Record the excess or shortage as an entry so the books match the cash drawer. History of counts.
- Editing an entry's amount, type or account un-clears it; changing the description or notes doesn't.

**Fixed**
- Test harness: waiting for data no longer fails intermittently when a check runs before the change has landed.

**Data**
- Database v8 → v9 adds cleared dates on entries, reconciliations and cash counts. Backups include them; older
  backups still restore.

## 1.10.0 (versionCode 11)

**New**
- **Send PDF on WhatsApp** on invoices, quotations, challans, purchase orders and notes when the party has a mobile
  number: WhatsApp (or WhatsApp Business) opens on their chat with the PDF attached and a short caption — amount, and
  for unpaid invoices the balance, due date and your UPI ID. Without WhatsApp the share sheet opens.
- **Notification** when the daily job creates recurring invoices ("Open Cashbook to send them"), if invoice
  notifications are on.

**Faster**
- Invoice balances and note lookups are worked out once per data change instead of on every screen redraw.
- New scale test: a 30,000-entry, 5,000-invoice ledger reloads after an edit in about 0.15 s on the test runner.

**Data**
- No database change.

## 1.9.0 (versionCode 10)

**New**
- **Recurring invoices** (Invoices & bills › ⟳): set up an invoice once — customer, items with GST, how often
  (weekly, monthly, quarterly, yearly, every N), first date, optional end date and payment terms — and the app creates
  it on every date, numbered in your invoice series. Write `{month}` or `{period}` in the description or notes to get
  "November 2026" or the dates covered. Pause, resume or delete at any time; invoices already made are kept. Each
  invoice shows "Created by a recurring invoice".
- **Transport details** on sales invoices and delivery challans: vehicle number, transporter, LR number and
  e-way bill number (12 digits), shown on the invoice and printed in the PDF header. Billing a single challan carries
  them over to the invoice.

**Data**
- Database v7 → v8 adds transport columns, the invoice's schedule link and the `invoice_schedules` table.
  Backups include them; older backups still restore.

## 1.8.0 (versionCode 9)

**New**
- **Delivery challans** (Invoices & bills › Quotes & orders › Delivery challans): list the goods you deliver,
  numbered DC/26-27/001, with a DELIVERY CHALLAN PDF. Stock goes out on the challan date; nothing is owed yet.
- **Bill challans in one invoice**: open any challan, tick that customer's open challans (all are ticked by default)
  and create a single invoice. Items are copied in challan order and the invoice says which challans it covers.
  Stock isn't reduced a second time. Deleting the invoice re-opens the challans; cancelling a challan returns its stock.
- **Overdue collections** (Receivables › Remind overdue customers): every customer with overdue invoices, largest
  amount first, with one WhatsApp (or share) reminder per customer listing all their overdue invoices and the total.
- Purchase order and challan PDFs no longer print your bank / UPI payment details.

**Data**
- No database change (challans use the same document storage and link as quotations).

## 1.7.0 (versionCode 8)

**New**
- **Purchase orders** (Invoices & bills › Quotes & orders › Purchase orders): itemised with GST, numbered
  PO/26-27/001, with an expected-by date and a PURCHASE ORDER PDF addressed to the supplier. **Convert to bill**
  when the goods arrive; stock comes in with the bill. Status Open, Overdue, Billed or Cancelled.
- **Statement of account** report for a customer or supplier: opening balance, invoices, credit/debit notes,
  payments and refunds with a running balance; the closing balance matches what is outstanding. Open it from
  Reports (pick the party) or from the party's screen. PDF and Excel.
- **Payment reminder** on unpaid sales invoices: opens WhatsApp on the customer's mobile with a polite message
  (amount, due date or days overdue, balance, your UPI ID), or the share sheet when there is no mobile number.
- Report tables: party headings span the full width in the preview.

**Data**
- No database change (purchase orders use the 1.6 quotation storage with kind = purchase).

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
