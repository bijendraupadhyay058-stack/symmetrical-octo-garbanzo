# Cashbook — Android app

An offline-first Android cashbook for recording daily income, expenses, cash / bank / digital-wallet
balances and transfers — for individuals, shopkeepers, freelancers, accountants and small businesses.
Indian Rupee (₹1,25,000.00 grouping), DD-MM-YYYY dates, Indian financial year (1 April – 31 March),
English and Hindi.

| | |
|---|---|
| Package | `com.cashbook.app` (debug build: `com.cashbook.app.debug`, installs side by side) |
| Minimum Android | **8.0 (API 26)** |
| Target / compile SDK | **Android 16 (API 36)** |
| Language / UI | Kotlin 2.2, Jetpack Compose (Material 3) |
| Architecture | MVVM + repository; pure-Kotlin `:core` module for all money/ledger/report logic |
| Storage | Room on **SQLCipher** (encrypted), key wrapped by the Android Keystore; settings in DataStore |
| Background | WorkManager (recycle-bin retention, recurring entries, automatic backup, optional alerts) |
| Widget | Home-screen widget (RemoteViews) with quick add and an opt-in balance |
| Files | Storage Access Framework, Photo Picker, camera intent (no storage/camera permissions) |
| Reports | On-screen preview, A4 **PDF** (Android `PdfDocument`), editable **.xlsx** (built-in writer) |
| Security | PIN (PBKDF2), biometric unlock (AndroidX Biometric), auto-lock, encrypted backups (AES-256-GCM) |

<p>
<img src="docs/screenshots/light_dashboard.jpg" width="180">
<img src="docs/screenshots/05_expense_form.jpg" width="180">
<img src="docs/screenshots/08_transactions.jpg" width="180">
<img src="docs/screenshots/10_report_monthly.jpg" width="180">
<img src="docs/screenshots/dark_dashboard.jpg" width="180">
<img src="docs/screenshots/hindi_dashboard.jpg" width="180">
<img src="docs/screenshots/12_dashboard_due_and_budgets.jpg" width="180">
<img src="docs/screenshots/13_recurring_list.jpg" width="180">
<img src="docs/screenshots/15_budgets.jpg" width="180">
<img src="docs/screenshots/19_invoice_detail_partial.jpg" width="180">
<img src="docs/screenshots/20_invoices_list.jpg" width="180">
<img src="docs/screenshots/21_report_outstanding.jpg" width="180">
<img src="docs/screenshots/25_invoice_items.jpg" width="180">
<img src="docs/screenshots/26_invoice_detail_items.jpg" width="180">
</p>
<p><img src="docs/screenshots/29_invoice_refund_due.jpg" width="180"> <img src="docs/screenshots/28_credit_note_form.jpg" width="180"></p>
<p><img src="docs/screenshots/31_products_list.jpg" width="180"> <img src="docs/screenshots/30_item_form.jpg" width="180"> <img src="docs/screenshots/32_invoice_pick_item.jpg" width="180"> <img src="docs/screenshots/33_dashboard_low_stock.jpg" width="180"></p>
<p><img src="docs/screenshots/37_quotation_form.jpg" width="180"> <img src="docs/screenshots/38_quotation_detail.jpg" width="180"> <img src="docs/screenshots/39_invoice_upi_qr.jpg" width="180"> <img src="docs/screenshots/40_quotations_list.jpg" width="180"></p>
<p><img src="docs/screenshots/45_invoice_reminder.jpg" width="180"> <img src="docs/screenshots/43_purchase_order_detail.jpg" width="180"> <img src="docs/screenshots/44_purchase_orders_list.jpg" width="180"> <img src="docs/screenshots/46_statement_of_account.jpg" width="180"></p>
<p><img src="docs/screenshots/50_challan_detail.jpg" width="180"> <img src="docs/screenshots/51_invoice_from_challans.jpg" width="180"> <img src="docs/screenshots/52_challans_list.jpg" width="180"> <img src="docs/screenshots/48_overdue_collections.jpg" width="180"></p>
<p><img src="docs/screenshots/54_recurring_form.jpg" width="180"> <img src="docs/screenshots/55_recurring_list.jpg" width="180"> <img src="docs/screenshots/56_invoice_transport.jpg" width="180"></p>
<p><img src="docs/screenshots/64_reconciliation_statement.jpg" width="180"> <img src="docs/screenshots/63_category_suggestion.jpg" width="180"> <img src="docs/screenshots/62_excel_statement_rule.jpg" width="180"> <img src="docs/screenshots/60_statement_import.jpg" width="180"> <img src="docs/screenshots/61_statement_matched.jpg" width="180"> <img src="docs/screenshots/57_cash_count.jpg" width="180"> <img src="docs/screenshots/58_bank_reconciliation.jpg" width="180"> <img src="docs/screenshots/59_reconciled.jpg" width="180"></p>
<p><img src="docs/screenshots/35_invoice_pdf_upi_qr.jpg" width="380" alt="Tax invoice PDF with UPI QR code"></p>
<p><img src="docs/screenshots/22_invoice_pdf_p1.jpg" width="380" alt="Tax invoice PDF"> <img src="docs/screenshots/27_credit_note_pdf.jpg" width="380" alt="Credit note PDF with logo and signature"></p>

**What's new in 1.14** — a **bank reconciliation statement** report (balance per books, deposits not yet credited,
payments not yet debited, balance per bank; PDF / Excel) and **category suggestions** in the entry form from the
wording you've used before.
**1.13** — statements from **Excel (.xlsx)** and the **HTML ".xls"** files many banks download, and
**learned categories**: categorise an imported line once and the same wording comes in categorised next time.
**1.12** — **import a bank statement (CSV)** into a reconciliation: the statement date and closing
balance are filled in, matching entries are ticked, and lines Cashbook doesn't have (bank charges, interest) can be
added with one tap.
**1.11** — **bank reconciliation** (tick entries against the bank statement until the difference is
zero; each side of a transfer clears on its own account) and **cash count** (notes and coins by denomination against
the book balance, with the excess or shortage recorded as an entry).
**1.10** — **Send PDF on WhatsApp**: an invoice, quotation, challan or purchase order PDF goes
straight into the customer's (or supplier's) chat with a short caption; a **notification** when recurring invoices are
created in the background; and a **scale check** — a 30,000-entry / 5,000-invoice ledger stays quick (see Testing).
**1.9** — **recurring invoices** (rent, retainers, AMC, subscriptions): set an invoice up once and it
is created on every date with its items, GST and your numbering, with `{month}` / `{period}` filled in; and
**transport details** (vehicle, transporter, LR, e-way bill) on invoices and challans, printed on the PDF.
**1.8** — **delivery challans**: record goods as you deliver them (stock goes out on the challan),
then bill several challans of a customer in **one invoice**; and **overdue collections**: every customer with overdue
invoices on one screen with a one-tap WhatsApp reminder listing all of them.
**1.7** — **purchase orders** to suppliers (itemised with GST, own PDF) converted into a bill in
one tap, a **statement of account** report per customer or supplier (invoices, notes and payments with a running
balance, PDF/Excel), and **payment reminders** that open WhatsApp on the customer's number with the amount, due
date and your UPI ID filled in.
**1.6** — **quotations / estimates** (itemised with GST, own PDF, valid-until date) that you
turn into an invoice with one tap, and a **UPI payment QR code** for unpaid sales invoices, in the app and printed
on the invoice PDF (any UPI app opens it with the amount and invoice number filled in).
**1.5** — a **products & services** list (HSN/SAC, unit, sale/purchase rate, GST rate) that you
pick from on invoice lines, **stock on hand** worked out from your sales, purchase bills, credit notes and
adjustments, a **low-stock** dashboard card, and **Stock summary** and **Item-wise sales** reports.
**1.4** — credit and debit notes (itemised with GST, own PDF), refunds when a credit note
follows payment, and your logo and signature on invoices and notes.
**1.3** — business profile, itemised GST invoices (CGST/SGST or IGST by place of supply),
printable tax-invoice PDF, GST summary report and GSTIN check-digit validation.
**1.2** — invoices & bills with outstanding balances and an ageing report, invoice and
budget alerts, and a home-screen widget. **1.1** added recurring entries, budgets, automatic backups and
release signing. See [CHANGELOG.md](CHANGELOG.md).

*(Screenshots are rendered by the automated UI tests — see [Testing](#testing).)*

---

## 1. Install the test APK

`dist/Cashbook-1.14.0-test.apk` is a ready-to-install release build (minified, signed with the
**test key** committed in `app/cashbook-test.keystore`). SHA-256 is in the `.sha256` file next to it.

1. Copy the APK to the phone (USB, email, Drive…) or run `adb install dist/Cashbook-1.14.0-test.apk`.
   Installing it over any earlier version keeps your data (the database upgrades automatically to v10).
2. On the phone, allow *Install unknown apps* for the app you open it with.
3. Open **Cashbook** and follow the 7-step setup.

> The test key is public. To sign with your own key, create one and copy `keystore.properties.example`
> to `keystore.properties` (git-ignored); `assembleRelease` then uses it automatically:
> ```bash
> keytool -genkeypair -v -keystore upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000
> cp keystore.properties.example keystore.properties   # then edit the passwords
> ```
> Android only installs an update signed with the same key, so moving from the test-signed build to
> your own key means uninstalling first — take a **backup** before you do, then restore it.

## 2. Build from source

Requirements: JDK 17+ (21 recommended), Android SDK with platform 36 and build-tools 36
(Android Studio Narwhal or newer installs these automatically).

```bash
cd android
echo "sdk.dir=/path/to/Android/sdk" > local.properties   # Android Studio does this for you
./gradlew test                      # all JVM tests (core + Robolectric app/UI tests)
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:assembleRelease      # app/build/outputs/apk/release/app-release.apk (test-signed)
./gradlew :app:installDebug         # install on a connected phone/emulator
```

Open the `android/` folder in Android Studio to run and debug. GitHub Actions
(`.github/workflows/android.yml`) runs the tests and uploads both APKs, the test reports and the
UI screenshots as build artifacts on every push that touches `android/`.

## 3. Project structure

```
android/
├── core/                         Pure Kotlin/JVM — no Android dependency, fully unit-tested
│   └── com/cashbook/core/
│       ├── Money.kt              Paise (Long) parsing/validation, Indian formatting, percentages
│       ├── Dates.kt              Date formats, Indian financial year, period presets
│       ├── Model.kt              Cashbook, Account, Category, Party, Txn (one row per transfer)
│       ├── Ledger.kt             THE balance rules: effects, balances, totals, running balance, negative check
│       ├── Filter.kt             Search, filters, sorting
│       ├── ReportModel.kt / ReportEngine.kt   All 10 reports → one ReportDocument model
│       ├── Recurrence.kt         Recurring rules: drift-free schedule, catch-up, end dates
│       ├── Budget.kt             Monthly budgets and progress (sub-categories count to the parent)
│       ├── Invoices.kt           Invoice/bill balances, status, ageing buckets, allocation rules, numbering
│       ├── Catalog.kt            Products/services, stock moves, on-hand, stock value, low stock, item-wise sales
│       ├── Upi.kt                UPI ID check, upi://pay links, QR encoding (ZXing core)
│       ├── Gst.kt                GST rates, state codes, GSTIN check digit, line/tax totals, round-off, amount in words
│       ├── Xlsx.kt               Dependency-free .xlsx writer (numeric cells, Indian number format)
│       └── backup/               Backup DTOs, streaming AES-GCM encryption, archive codec + validation
└── app/                          Android app
    └── com/cashbook/app/
        ├── CashbookApp.kt        Application + manual DI container (opens the encrypted DB)
        ├── MainActivity.kt       Single activity, lock-on-background, FLAG_SECURE option
        ├── data/                 Room entities/DAOs, LedgerRepository, SettingsRepository,
        │                         SecureStore (Keystore), AttachmentStore, BackupManager, defaults
        ├── export/               PdfReportWriter (A4 reports), InvoicePdfWriter (tax invoice), Exporter (save/share)
        ├── work/                 DailyWorker (retention, recurring entries, automatic backup, reminders) + Alerts
        ├── widget/               Home-screen widget (quick add, opt-in balance)
        └── ui/                   Compose screens: onboarding, lock, dashboard, transactions (list,
                                  form, detail, filters), reports, settings, backup, recycle bin,
                                  management (cashbooks, accounts, categories, parties), theme
```

Business calculations never live in UI code: every screen, report and export calls `Ledger` /
`ReportEngine` in `:core`, so the dashboard, transaction list, PDF and Excel always agree.

## 4. Data model

| Entity (table) | Key fields |
|---|---|
| Cashbook (`cashbooks`) | name, description, opening date, currency, created/updated, archived, is_sample |
| Account (`accounts`) | cashbook, name, type (CASH/BANK/WALLET/OTHER), opening balance (paise), opening date, bank name, last 4 digits, description, archived |
| Category (`categories`) | kind (INCOME/EXPENSE), name, parent (sub-category), icon, archived |
| Party (`parties`) | name, type, mobile, email, address, GSTIN, notes, archived |
| Transaction (`transactions`) | cashbook, type (INCOME/EXPENSE/TRANSFER), date, amount (paise), account, **to_account (transfers)**, category, party, payment mode, description, reference, notes, tags, created/updated, **deleted_at (recycle bin)**, **cleared_on / to_cleared_on** (bank reconciliation per side, v9) |
| Attachment (`attachments`) | transaction, file name, MIME type, size, private stored file name |
| Recurring (`recurring`, v2) | cashbook, type, amount, account(s), category, party, mode, description, reference, frequency (daily/weekly/monthly/quarterly/yearly) × interval, start date, optional end date, next occurrence index, auto-post or confirm, active |
| Budget (`budgets`, v2) | cashbook, expense category (unique per cashbook), monthly amount |
| Invoice (`invoices`, v3) | cashbook, kind (SALE = receivable / PURCHASE = payable), **doc type** (INVOICE / CREDIT_NOTE / DEBIT_NOTE, v5; QUOTATION, v7; CHALLAN, 1.8; TEMPLATE, v8), **transport** (vehicle no., transporter, LR no., e-way bill no., v8), **schedule** (invoices made by a recurring schedule, v8), **ref invoice** (for notes, v5), **converted invoice** (for quotations, v7), number (unique per cashbook + kind + doc type), party, issue date, due date, amount, place of supply, round-off, description, notes, cancelled |
| InvoiceItem (`invoice_items`, v4) | invoice, position, description, HSN/SAC, quantity (thousandths), unit, rate (paise), discount and GST rate (basis points), **catalogue item** (optional, v6) |
| CatalogItem (`catalog_items`, v6) | name (unique, case-insensitive), kind (GOODS/SERVICE), HSN/SAC, unit, sale rate, purchase rate, GST rate, description, opening stock + date, reorder level, archived |
| CategoryRule (`category_rules`, v10) | narration key (first three letter-words, upper-case; unique), category |
| Reconciliation (`reconciliations`, v9) | account, statement date, statement closing balance, entries cleared |
| CashCount (`cash_counts`, v9) | account, date, counted, book balance, denominations ("500x10,200x3"), adjustment entry, note |
| InvoiceSchedule (`invoice_schedules`, v8) | template document (unique), frequency × interval, start date, optional end date, next index, due days, active |
| StockAdjustment (`stock_adjustments`, v6) | item, date, quantity change (thousandths, + or −), reason |
| Allocation (`allocations`, v3) | invoice, payment entry, amount applied (one row per invoice + entry) |
| BackupHistory (`backup_history`) | time, backup/restore, file name, attachments included, size, success |
| UserSettings | Jetpack DataStore (language, theme, date format, defaults, week start, negative-balance policy, lock, reminders, retention…) — PIN hash and DB key live in the encrypted `SecureStore` |

* **Transfers are one row** (source `account_id`, destination `to_account_id`). Editing, deleting or
  restoring a transfer therefore always moves both sides together; the "Transfer" entity of the
  specification is this row type.
* Foreign keys: deleting a cashbook cascades to its accounts, entries and attachments (only after the
  confirmation that shows the counts). Categories and parties are `RESTRICT`: they can only be deleted
  when unused (categories may be reassigned first); otherwise they are archived. Renaming keeps the id,
  so history shows the new name. Accounts with entries cannot be deleted — only archived.
* Transactions created by a schedule carry `recurring_id` (v2) so they can be traced back to it.
* **Invoices and bills never change balances.** A payment is an ordinary income (sale) or expense
  (purchase) entry, linked through `allocations`. Outstanding = invoice amount − allocations whose entry
  is live, so moving a payment to the recycle bin re-opens the invoice and restoring it settles it again.
  An entry can be split across several invoices; it can't be edited below the amount applied.
* The Room schema is exported to `app/schemas/`. **Migrations** live in `data/db/Migrations.kt` and are
  verified by `MigrationTest` against those exported schemas (v1 → v2 adds `recurring`, `budgets` and
  `transactions.recurring_id`; v2 → v3 adds `invoices` and `allocations`; v3 → v4 adds `invoice_items`, `invoices.place_of_supply`, `invoices.round_off`
  and `parties.state_code`, filling party states from existing GSTINs; v4 → v5 adds `invoices.doc_type` and
  `invoices.ref_invoice_id` and widens number uniqueness to include the doc type; v5 → v6 adds `catalog_items`, `stock_adjustments` and
  `invoice_items.item_id`; v6 → v7 adds `invoices.converted_invoice_id` for quotations; v7 → v8 adds the transport columns, `invoices.schedule_id` and `invoice_schedules`; v8 → v9 adds `transactions.cleared_on` / `to_cleared_on`, `reconciliations` and `cash_counts`; v9 → v10 adds `category_rules`; existing rows are untouched).
* **Quotations and purchase orders** are rows in `invoices` with `doc_type = QUOTATION` — kind SALE is a quotation
  (series QT/26-27/001), kind PURCHASE a purchase order (PO/26-27/001); the due date is "valid until" / "expected by". The snapshot keeps them in a separate list, so balances, receivables, alerts, stock and every report
  ignore them; the GST and item-wise reports also exclude them directly. Status is derived: converted, declined
  (cancelled), expired (past valid-until) or open. Converting copies party, place of supply, items (with their
  catalogue links), description and notes into a new invoice dated today and due in 15 days, and stores its id on the
  quotation; deleting that invoice re-opens the quotation.
* **Delivery challans** are rows in `invoices` with `doc_type = CHALLAN` (always SALE, series DC/26-27/001, due date =
  challan date). They sit in their own snapshot list: balances, receivables and reports ignore them, but stock counts
  them (out on the challan date). Billing links one or more open challans of the same customer to a new invoice via
  `converted_invoice_id`; `Stock.moves` skips invoices billed from challans so goods leave stock only once. Deleting
  the invoice re-opens its challans; cancelling a challan returns its stock.
* **Recurring invoices**: a `TEMPLATE` document (off the books like quotations) plus an `invoice_schedules` row. On app
  start and in the daily job, each due date (drift-free, from the start date; at most 24 per run) becomes a normal
  invoice: items copied, numbered in the INV series, due after the schedule's days, `{month}` / `{period}` filled in,
  `schedule_id` set. A date that already has an invoice from the schedule is never created again. Pausing skips the
  dates while paused; editing changes future invoices only; deleting keeps the invoices already made.
* **Reconciliation**: cleared balance = opening balance + entries cleared on that account; finishing requires the
  statement balance to equal it plus the ticked entries (difference zero). Editing an entry's type, amount or account
  un-clears that side; editing words keeps it. **Cash count**: book balance = account balance at the end of the date;
  recording the difference adds a "Cash excess" income or "Cash shortage" expense (categories created when missing).
* **Statement import** (`core/StatementImport.kt`): finds the header row by its column names (date; narration /
  description; reference; withdrawal + deposit, or a signed amount, or amount + Dr/Cr; balance), skips account-detail
  and totals rows, reads Indian number and date formats, and orders newest-first files by date. Matching pairs each line
  with an uncleared entry of exactly the same signed amount within ±4 days (closest date, a matching reference wins);
  lines that match an already cleared entry are ignored so nothing is added twice.
* **Statement files** (`core/StatementFiles.kt`): recognised by content — .xlsx (zip; first sheet; shared and inline
  strings; date-formatted numbers become dates), HTML tables saved as ".xls", or CSV / tab / semicolon text (UTF-8,
  UTF-16 with BOM, Windows-1252). Old binary .xls is reported with a "save as .xlsx or CSV" message.
* **Bank reconciliation statement** (report): per bank / wallet account at the report date — balance per books, less
  uncleared deposits, add uncleared payments = balance per bank; an entry counts as cleared only if cleared on or before
  that date, so past dates reproduce. Last reconciliation shown.
* **Learned categories**: words of the description (letters only, no month names). New categorised entries teach a
  rule unless one exists; giving an uncategorised entry a category stores / replaces it. A rule matches when its words
  begin the description's (longest wins). Earlier rule: giving an uncategorised entry a category stores its narration key → category (latest wins);
  statement lines added later with the same key get that category if its kind (income / expense) fits and it isn't
  archived. Rules can be reviewed and deleted in Settings › Statement categories.
* **UPI QR**: for a sales invoice with a balance and a valid UPI ID in the business profile, the app shows and the PDF
  prints a QR code for `upi://pay?pa=…&pn=…&am=<balance>&cu=INR&tn=<invoice no.>` (error correction M).
* **Stock** is never stored, it is derived (`core/Catalog.kt`): opening stock (from its date) + purchase bill
  lines − sale invoice lines + sale credit-note lines − purchase credit-note lines ± adjustments. Debit notes and
  cancelled documents don't move stock. Services have no stock. Stock value uses the purchase rate. Items used on
  invoices or adjustments can only be archived, not deleted; editing an item never changes saved invoices.
* **Credit / debit notes** are rows in `invoices` with `doc_type` and `ref_invoice_id`, so numbering
  (CN/…, DN/…), line items, GST, PDF and backup reuse the invoice code. A note takes the original's cashbook,
  kind, party and place of supply. Net owed = amount + debit notes − credit notes; credit notes can't exceed
  amount + debit notes. Payments minus **refunds** (an entry of the opposite type linked to the invoice) give
  "paid"; when paid exceeds the net amount the invoice is **Refund due**. Invoices with notes can't be cancelled
  or deleted until the notes are removed. In the GST summary, credit notes reduce and debit notes add tax.
* **GST calculation** (`core/Gst.kt`): line taxable = qty × rate − discount, each rounded to the paisa; tax per
  line at the GST rate — CGST and SGST each at half the rate when the place of supply is the seller's state,
  otherwise IGST; optional round-off of the grand total to the nearest rupee. An itemised invoice's amount is
  always this grand total. The business profile (name, GSTIN, state, bank/UPI, terms) is kept in DataStore
  and included in backups.

## 5. Calculation rules

* Money is stored as **integer paise** (`Long`); parsing uses `BigDecimal` with exactly 0–2 decimals.
  No floating point is ever used for money.
* `Closing = Opening + Income − Expenses + Transfers received − Transfers sent` per account.
* An account's opening balance takes effect **on its opening date**; entries cannot be dated before it.
* A report's opening balance = everything before the period start (opening balances + entries);
  accounts opened inside the period show their opening balance as a separate line.
* Transfers are never income or expense. For a set of accounts, a transfer between two accounts of the
  set nets to zero; a transfer leaving the set counts as *transfer out*.
* Entries on the same date are ordered by creation time, then id.
* Saving an entry that would push any affected account below zero **at any point from that date on**
  shows a warning (“Save anyway”) — or is blocked if *Allow negative balances* is off in Settings.
* Balances are derived, never stored, so add / edit / delete / restore always recalculate. The UI
  snapshot re-reads all tables inside **one database transaction** after every change, so screens
  never see a half-updated state.

## 6. Feature checklist (spec → implementation)

| Area | Where |
|---|---|
| First-run setup (welcome, language, theme, cashbook, accounts + opening balances, optional PIN, optional sample data; skippable steps) | `ui/onboarding` |
| Multiple cashbooks: create, edit, switch, default, archive/restore, export, delete with impact counts + type-name confirmation, combined view | `ui/manage/CashbookScreens.kt`, cashbook switcher in the title bar |
| Accounts: types, opening balance/date, bank name, last 4 digits only, archive, balance "as of" date, account vs payment mode explained | `ui/manage/AccountScreens.kt` |
| Dashboard: today / month totals, net for selected period, total + cash/bank/wallet, quick actions, 6/12-month chart, top expense categories, account balances, recent entries, backup status; filters: cashbook, account, today/week/month/FY/custom | `ui/dashboard` |
| Income / Expense / Transfer forms with all fields, inline category/party creation, attachments, *Save and add another*, draft survives process death | `ui/transactions/TransactionForm*` |
| Transaction history: search (description, party, category, amount, reference, notes, tags), all filters, 4 sort orders, running balance for one account, filtered banner + Clear filters, detail / edit / duplicate / delete / share | `ui/transactions` |
| Categories with sub-categories and icons, archive, rename, delete-with-reassign | `ui/manage/CategoryScreens.kt` |
| Parties: types, mobile, email, address, GSTIN, search, linked entries, party-wise export, archive | `ui/manage/PartyScreens.kt` |
| 10 reports (daily, monthly, yearly, FY, category, party, account, income & expense, transfers, custom) with header, filters, opening/closing balances and cash-basis notes | `core/ReportEngine.kt`, `ui/reports` |
| PDF (A4, repeated table headings, page x of y, aligned amounts, landscape for wide tables) and Excel (summary sheet, one sheet per table, standard *Transactions* sheet, numeric cells) — save via file picker or share | `export/`, `core/Xlsx.kt` |
| Attachments: camera, gallery (photo picker), file picker; JPG/PNG/PDF; preview (incl. PDF first page), size, replace, remove, open in viewer; 10 MB limit, large photos downscaled | `data/AttachmentStore.kt`, `ui/components/Attachments.kt` |
| Encrypted backup to any SAF location (device, SD, cloud drive), attachments optional, last-backup time, history, reminders; restore with full validation, summary, replace warning + confirmation, atomic restore that preserves data on failure | `data/BackupManager.kt`, `core/backup`, `ui/settings/BackupScreen.kt` |
| PIN lock, biometric, auto-lock timeout, brute-force delay, hide-in-recents/screenshot blocking, privacy policy | `ui/lock`, `ui/settings/SecuritySettingsScreen.kt` |
| Recycle bin: restore, delete permanently, empty, deletion date, retention (off/30/90 days) | `ui/settings/RecycleBinScreen.kt`, `work/` |
| Settings: language, date format, theme, default cashbook/account, week start, currency display, negative balances, security, data, guide, privacy, about, version, feedback | `ui/settings` |
| Sample data (Office Cashbook) — add / remove any time | Settings › Data |
| **1.1** Recurring entries: daily → yearly with intervals, end date, pause, auto-post or confirm (Post / Skip on the dashboard, amount can vary), "Make recurring" from any entry, catch-up after the app was closed | `core/Recurrence.kt`, `ui/recurring`, `LedgerRepository.postDueRecurring` |
| **1.1** Monthly budgets per expense category with dashboard progress (OK / ≥ 80 % / over) | `core/Budget.kt`, `ui/manage/BudgetsScreen.kt` |
| **1.14** Bank reconciliation statement report (PDF / Excel), opened from the reconciliation screen with the account preselected; category suggestion chip in the entry form; rules learned from typed entries, month names ignored, prefix matching | `core/ReportEngine.bankReconciliation`, `CategoryRules`, `TransactionFormScreen` |
| **1.13** Excel (.xlsx) and HTML ".xls" statements; learned narration → category rules applied when adding statement lines, shown on the line before adding, managed in Settings | `core/StatementFiles.kt`, `LedgerRepository.ruleCategory`, `CategoryRulesScreen` |
| **1.12** Import a bank statement CSV into the reconciliation: date and closing balance filled in, matches auto-ticked, missing lines added (uncategorised) with one tap; overlapping statements don't re-offer cleared lines | `core/StatementImport.kt`, `ui/manage/ReconcileScreens.kt`, `LedgerRepository.addStatementLine` |
| **1.11** Bank reconciliation: account, statement date and closing balance (zero or overdrawn allowed), tick entries, live difference, finish only at zero, history, undo per entry from its detail | `core/Reconcile.kt`, `ui/manage/ReconcileScreens.kt`, `LedgerRepository.reconcile` |
| **1.11** Cash count by denomination (₹500 … ₹1) against the book balance, excess / shortage recorded as an entry, history | `core/Reconcile.kt` (`CashCount`), `LedgerRepository.saveCashCount` |
| **1.10** Send a document PDF into the party's WhatsApp / WhatsApp Business chat with a caption (amount; balance, due date and UPI ID for unpaid invoices), falling back to the share sheet; notification when recurring invoices are created by the daily job | `Exporter.sendToWhatsApp`, `pdfCaption`, `work/Workers.kt` |
| **1.9** Recurring sales invoices: weekly / monthly / quarterly / yearly × every N, first date, optional end, payment terms; items and GST; {month} / {period} placeholders; created automatically (catch-up capped); pause / resume / delete; list with next date and count; link from each invoice | `core/Invoices.kt` (`InvoiceSchedules`), `LedgerRepository.postDueInvoiceSchedules`, `ui/invoices/RecurringInvoicesScreen.kt` |
| **1.9** Transport details on sales invoices and challans (vehicle no. normalised, transporter, LR no., 12-digit e-way bill), shown on screen and in the PDF header; copied when one challan is billed | `core/Invoices.kt` (`Transport`), `export/InvoicePdfWriter.kt` |
| **1.8** Delivery challans: itemised, stock out on the challan date, DELIVERY CHALLAN PDF ("Deliver to", no payment block), not billed / billed / cancelled; bill several open challans of a customer in one invoice (items copied in order, stock not moved twice); links both ways | `core/Catalog.kt` (`Stock.moves`), `ui/invoices/ChallanScreens.kt`, `LedgerRepository.convertChallans` |
| **1.8** Overdue collections: customers with overdue sales invoices (largest first, oldest days, invoice list) with one WhatsApp / share reminder per customer listing every overdue invoice and the total; reachable from Receivables | `ui/invoices/CollectionsScreen.kt` |
| **1.7** Purchase orders: itemised with GST, expected-by date, PURCHASE ORDER PDF addressed to the supplier, open / overdue / billed / cancelled, one-tap conversion to a bill (stock comes in with the bill) | `ui/invoices/QuotationScreens.kt`, `LedgerRepository.convertQuotation` |
| **1.7** Statement of account: per customer/supplier, opening balance, invoices, notes, linked payments and refunds with running balance, closing = outstanding; unlinked entries totalled; party picker; from the party screen; PDF/Excel | `core/ReportEngine.partyStatement`, `ui/reports/ReportViewScreen.kt` |
| **1.7** Payment reminder for unpaid sales invoices: WhatsApp click-to-chat on the customer's mobile (Indian numbers normalised to +91), or the share sheet; overdue / due wording, balance, UPI ID | `core/Upi.kt` (`Reminders`), `reminderText` |
| **1.6** Quotations / estimates: itemised with GST, valid-until date, QUOTATION PDF, open / expired / declined / converted, one-tap conversion to an invoice (items, party and place of supply copied), link back from the invoice | `core/Invoices.kt` (`Quotations`), `ui/invoices/QuotationScreens.kt`, `LedgerRepository.convertQuotation` |
| **1.6** UPI payment QR for unpaid sales invoices, on screen and on the PDF (amount = balance due, note = invoice number); UPI ID validated in the business profile; "Pay by UPI" line in the shared text | `core/Upi.kt`, `export/InvoicePdfWriter.kt`, `UpiQrCard` |
| **1.5** Products & services list with search, low-stock filter, archive; pick an item on an invoice line to fill description, HSN/SAC, unit, rate and GST (stock shown, warning when a sale exceeds it) | `core/Catalog.kt`, `ui/manage/CatalogScreens.kt`, `ui/invoices/InvoiceItemsEditor.kt` |
| **1.5** Stock on hand, stock adjustments with reason, low-stock dashboard card; Stock summary and Item-wise sales reports (PDF/Excel) | `core/Catalog.kt`, `core/ReportEngine.kt`, `ui/dashboard` |
| **1.4** Credit and debit notes (itemised with GST, starting from the invoice's items), refunds, invoice status "Refund due", notes in the GST summary; CREDIT NOTE / DEBIT NOTE PDF referring to the original invoice | `core/Invoices.kt`, `ui/invoices` |
| **1.4** Logo and signature images on invoices and notes (gallery picker, scaled, included in backups) | `AttachmentStore.importBrand`, `BusinessProfileScreen` |
| **1.3** Business profile; itemised invoices/bills with HSN/SAC, qty, unit, rate, discount, GST rate (0, 0.25, 3, 5, 12, 18, 28, 40 %); place of supply; live totals | `ui/settings/BusinessProfileScreen.kt`, `ui/invoices/InvoiceItemsEditor.kt` |
| **1.3** Tax invoice PDF (A4): seller/buyer GSTIN and state, items with repeated headings, GST summary by rate, totals, round-off, paid/balance, amount in words (Indian system), bank/UPI, terms, signatory | `export/InvoicePdfWriter.kt` |
| **1.3** GST Summary report (output vs input tax by rate, CGST/SGST/IGST) and GSTIN check-digit validation with state auto-fill | `ReportEngine.gstSummary()`, `core/Gst.kt` |
| **1.2** Invoices & bills: numbering per financial year (INV/26-27/001, BILL/…), due-date presets, status (open / partly paid / overdue n days / paid / cancelled), record receipt or payment (creates the entry), apply existing entries, unlink, cancel, share; dashboard and party outstanding | `core/Invoices.kt`, `ui/invoices` |
| **1.2** Outstanding & Ageing report (as at a date; not due, 1–30, 31–60, 61–90, 90+ days) in PDF/Excel | `ReportEngine.outstanding()` |
| **1.2** Alerts: overdue / due-soon invoices and budget 80 % / over notifications (opt-in, once per level per month), plus an immediate in-app warning when an entry crosses a budget level | `work/Alerts.kt` |
| **1.2** Home-screen widget with Income / Expense / Transfer buttons; balance only when allowed and never while the app lock is on | `widget/CashbookWidget.kt` |
| **1.1** Automatic backups to a chosen folder (incl. cloud drives) daily or weekly, keeping the latest N copies; password kept in the encrypted store | `data/AutoBackup.kt`, Backup screen |

## 7. Security & privacy

* **No `INTERNET` permission.** Requested permissions: notifications (only for backup reminders,
  asked at runtime) and biometrics. WorkManager adds wake-lock/boot-completed for its scheduler.
* Database: SQLCipher with a random 256-bit key; the key is stored in `SecureStore`, a file encrypted
  with a non-exportable AES-GCM key in the **Android Keystore**.
* PIN: PBKDF2-HMAC-SHA256 (60 000 iterations, random salt), 30-second lock-out after 5 wrong tries.
* Android auto-backup is disabled (the Keystore key cannot move devices); use the app's backup.
* Backup file (`.cbk`): `"CBKP"` header, PBKDF2-HMAC-SHA256 (150 000 iterations) → AES-256-GCM in
  64 KiB authenticated chunks (detects wrong password, tampering, reordering and truncation). Inside:
  a zip with `manifest.json`, `data.json` and `attachments/`. **A lost password cannot be recovered.**
* Never asks for bank passwords, UPI/card PINs, OTPs or net-banking credentials; no bank integration.

## 8. Testing

```bash
./gradlew test
```

193 automated tests, all passing (`./gradlew test` also runs the release unit-test variant, where
the migration test is skipped because schemas are packaged only into debug assets):

| Suite | What it checks |
|---|---|
| `core` `MoneyTest`, `DatesTest` | Parsing rejects empty/zero/negative/3-decimal/non-numeric/huge amounts; Indian grouping; FY boundaries; period presets; DD-MM-YYYY |
| `core` `LedgerTest` | Spec sample: Office Cash **₹13,500**, SBI **₹59,000**, total **₹72,500**; income/expense effects; transfer keeps total and is excluded from income/expense; edit/delete recalculation; report opening balances; same-date ordering; negative-balance detection incl. back-dated entries and edits |
| `core` `ReportEngineTest`, `FilterTest`, `XlsxTest` | Report totals match entries; opening/closing; daily running balance; category %; transfers excluded from I&E; custom filters; FY month breakdown; search/filter/sort; .xlsx structure, numeric amounts and real date cells |
| `core` `BackupCodecTest` | Encrypted round trip (multi-chunk attachment); wrong password; damaged, truncated and foreign files rejected; weak password refused; referential validation |
| `app` `RepositoryTest` (Robolectric + real Room schema) | Sample balances; add/edit/delete/restore; transfer delete/restore moves both sides; category rename/reassign/delete rules; party and account delete protection; archive keeps history; cashbook delete impact + cascade; sample removal keeps user data; recycle-bin purge removes files |
| `app` `BackupRestoreTest` | Backup → wipe → restore reproduces data and attachment bytes; restore without attachments; wrong password / damaged / truncated / non-backup files fail **and current data is untouched** |
| `core` `RecurrenceTest`, `BudgetTest` | Month-end schedules don't drift (31 Jan → 28 Feb → 31 Mar), all frequencies/intervals, catch-up with end dates and cap, budget progress incl. sub-categories and thresholds |
| `core` `InvoicesTest` | Status transitions incl. a payment moved to the recycle bin, ageing buckets, allocation limits, FY numbering, outstanding report as at past dates |
| `core` `StatementFilesTest` | .xlsx written by the app's own writer; a bank-style .xlsx with shared strings, a custom date format and skipped cells/rows; an HTML ".xls" with entities; UTF-16 and Windows-1252 text; old .xls refused; narration keys and rule lookup |
| `core` `StatementImportTest` | Three bank layouts (debit/credit columns with account rows and totals; signed amount newest-first with ₹ and times; amount + Dr/Cr with an overdrawn balance), amount/date parsing, quoted CSV, matching by amount, date window and reference, already-cleared lines not offered again |
| `core` `ReconcileTest` | Cleared balance, uncleared list, transfer sides, difference to zero; cash count totals, encoding/decoding, sign of the difference |
| `core` `ScheduleTest` | Month-end dates don't drift, catch-up cap, end date, pause, resume index, quarterly × 2, {month}/{period} placeholders, templates off the books, REC numbering, transport normalisation and e-way validation, backup validation of schedules |
| `core` `ChallanTest` | Stock leaves on the challan and only once (billed invoice and cancelled challan don't move it), challans owe nothing and never expire, DC numbering, billing rules (open, same customer), reports ignore challans |
| `core` `StatementTest` | Customer statement from opening to closing (invoices, credit notes, payments with mode/reference; cancelled, quotations and binned payments ignored; closing = outstanding), supplier side, unlinked receipts, WhatsApp number normalisation and link, PO numbering |
| `core` `QuotationUpiTest` | Quotation status (open / expired / declined / converted), QT numbering, quotations owe nothing and move no stock; UPI ID validation, link format and UTF-8 encoding; QR encode → decode round trip |
| `core` `StockTest` | Stock from purchases, sales, credit notes, adjustments and opening stock (by date); debit notes and cancelled documents ignored; services excluded; stock value and low-stock flag; item-wise sales net of credit notes; Stock summary report |
| `core` `GstTest` | GSTIN check digit (GST-portal sample), rate labels, CGST/SGST vs IGST per line, paisa rounding, round-off both ways, amount in words up to crores, exact quantity/percent parsing, GST summary report |
| `app` `MigrationTest` | v1 → v2, v1 → v3, v3 → v4, v4 → v5, v5 → v6, v6 → v7, v7 → v8, v8 → v9 and v9 → v10 upgrades keep every row, fill party states from GSTINs, and match Room's expected schema exactly |
| `app` `Phase15Test` | Typed entries teach rules without overriding, month names ignored, uncategorised entries teach nothing; reconciliation statement on real data with an uncleared cheque (books, bank, last reconciliation) |
| `app` `Phase14Test` | A categorised imported line teaches a rule; the next month's line comes in categorised; kind mismatch ignored; only uncategorised → categorised edits learn; rules survive backup; deleted rule stops applying |
| `app` `Phase13Test` | Statement built from the sample bank account plus charges and interest: all entries matched, the two missing lines added and matched, reconciled at the statement's closing balance |
| `app` `Phase12Test` | Reconciling with an uncleared cheque (difference refused, then finished), transfer cleared on the bank side only, no double clearing, edits keep or reset clearing, undo; cash shortage and excess entries and categories, count without recording, backup of counts, reconciliations and cleared dates |
| `app` `ScaleTest` | 30,000 entries, 300 parties, 5,000 invoices / 10,000 lines / 3,000 payment links, 200 products: snapshot reload after an edit, invoice balances, account balances, stock, overdue list and every report stay within generous bounds (JVM: reload ≈ 0.15 s, balances ≈ 10 ms, slowest report ≈ 0.25 s; timings printed) |
| `app` `Phase11Test` | PDF sent to WhatsApp with the customer's chat id, file and caption; exact caption text; cached balances |
| `app` `Phase10Test` | Schedule creates Jan 31 / Feb 28 / Mar 31 invoices once, with filled placeholders, due dates and numbering; pause/resume; deleting keeps invoices; end date; editing affects only future invoices; transport normalised, copied from a challan, printed; backup keeps schedules, templates, links and transport without re-creating invoices |
| `app` `Phase9Test` | Challans forced to sales with no due date; stock by date; two challans billed in one invoice (amount, items in order, description, links); mixed customers, re-billing and cancelled challans refused; deleting the invoice re-opens them; backup; challan PDF without QR; overdue customers ordering and exact customer reminder text |
| `app` `Phase8Test` | Purchase order stays out of payables and stock, converts to a bill (stock in), prints as PURCHASE ORDER without a QR, survives backup; statement built from real repository data agrees with outstanding; exact reminder text (overdue and due) |
| `app` `Phase7Test` | Quotation stays out of receivables and stock and refuses payments/notes; conversion copies items and links; can't convert twice or when declined; deleting the invoice re-opens it; own number series; backups keep quotations and links; invoice PDF QR read back from the rendered page; no QR when paid, on quotations or with an invalid UPI ID |
| `app` `Phase6Test` | Item names unique; picking an item on a sale lowers stock and a purchase bill raises it; credit note returns stock; adjustments; items in use can't be deleted, only archived; backups include items, adjustments and invoice-line links |
| `app` `Phase5Test` | Credit note lowers outstanding and inherits party/place of supply; debit note raises it; FY note numbering; credit can't exceed invoice; invoices with notes can't be deleted or cancelled; notes can't reference notes; credit after full payment → refund due → refund recorded as an expense → paid; invoice can't drop below what stays paid; backups carry notes and logo images; credit-note PDF with logo and signature rendered |
| `app` `Phase4Test` | Item totals become the invoice amount for intra- and inter-state supply; editing replaces items and simple mode clears them; totals can't drop below paid or to zero; backups include items, party state and business profile; tax-invoice pages rendered (incl. a 45-line invoice over two pages) |
| `app` `Phase3Test` | Invoices don't touch balances until paid; recording payments; delete/restore payment re-opens/settles; duplicate numbers, amount below paid, cancel/delete with payments and editing an applied entry are refused; split allocations and their limits; backups include invoices; alert digest and once-per-level budget alerts; widget hides amounts when locked or not allowed |
| `app` `Phase2Test` | Auto-posting catches up once and is idempotent; manual Post/Skip; paused/ended rules; schedule edits don't repost; rules protect accounts and follow category reassignment; budgets set/update/remove; backups include schedules and budgets; auto-backup retention |
| `app` `UiFlowTest` (Robolectric + Compose) | Full first-run setup through the UI, adding an expense and a transfer through the real forms (balances verified), validation messages, confirming a due recurring entry from the dashboard, creating a schedule through its form, the budgets
screen, creating a simple invoice and recording a receipt against it, filling the business profile and creating an
itemised GST invoice (IGST for another state), issuing a credit note from a paid invoice and recording the
refund, adding a product through its form and picking it on an invoice (stock shown, low-stock card on the dashboard), creating a quotation and converting it to an invoice with its UPI QR card, the WhatsApp reminder button, creating a purchase order and converting it to a bill, the statement of account for one party, the overdue collections screen, creating a delivery challan and billing two challans in one invoice, creating a monthly recurring invoice through its form (today's invoice created), transport details on an invoice, a cash count with a shortage entry, a bank reconciliation to zero, importing a statement and adding its missing lines, an Excel statement whose new line shows and gets its learned category, the category suggestion chip, the reconciliation statement opened from the reconciliation screen, the Outstanding report, deleting an entry
through its confirmation dialog, and screenshots in light, dark, Hindi and a small 360 dp phone (`app/build/screenshots/`) |

Not automated here (please check on a device): writing the PDF file itself (Android's native `PdfDocument`
is unavailable on the JVM runner; the same layout and drawing code is rendered to images in tests), dialogs that contain a text field (new category/party
inside the entry form, budget amount, applying an existing entry to an invoice) — under the JVM test
runner these never reach an idle state, so they are covered by repository tests only; the home-screen
widget on a launcher; notifications; automatic backup into a real folder / cloud provider
(folder permission handling), WorkManager timing, camera capture, biometric prompt, Android share sheet,
opening the generated PDF in a viewer, notifications, and choosing a cloud drive in the file picker.

## 9. Known limitations / next phases

The string tables for both languages live in `tools/strings/` (`strings1-3.py`); run
`python3 tools/strings/gen.py app/src/main/res <keys-file>` to regenerate `values/` and `values-hi/`.


* Records cash movements plus invoices, notes and stock; it is not a full accounting (double-entry) or
  GST-filing system. Stock is a simple quantity count valued at the purchase rate (no FIFO/weighted cost,
  batches, serial numbers, multiple godowns or units conversion).
* Combined (all-cashbooks) view sums balances; reports for a combined view use all active cashbooks.
* Automatic backups are file copies into a folder you choose, not live two-way sync between devices.
* Recurring entries post on the day they fall due when the app is opened or the daily background job
  runs (Android decides the exact time, usually within a day); auto-posted entries skip the
  negative-balance warning.
* GST support covers tax invoices, credit/debit notes and a review summary. Not included: e-invoicing (IRN/QR
  from the IRP), e-way bills, reverse charge, cess, composition-scheme bills of supply, TDS/TCS, or filing GSTR
  returns. The amount in words is in English. A credit note is tied to one invoice (no unlinked/advance credits).
* When editing an existing sale, the stock warning on an invoice line still counts that invoice's own lines.
* Quotations and purchase orders convert in full (no partial conversion), and the converted
  invoice is due in 15 days (edit it afterwards). The UPI QR is a static "pay this amount" link: the app does not
  learn when the customer pays — record the receipt as usual.
* The statement covers invoice-linked activity; payments not applied to an invoice are only totalled. Reminders
  are sent by you from WhatsApp (nothing is sent automatically).
* A challan is billed in full (no partial billing of a challan). Editing an invoice that was billed from challans
  doesn't change stock — stock follows the challans; edit or cancel the challan instead.
* Recurring invoices are created when the app opens or the daily job runs (Android picks the time, usually within a
  day). The app records transport details; it does not generate e-way bills on the government portal.
* WhatsApp is opened with the PDF and caption ready; you still tap send (Android doesn't let apps send messages for
  you). The direct-to-chat link uses WhatsApp's widely used but undocumented `jid` extra; if a WhatsApp update ignores
  it, WhatsApp asks you to pick the chat. ScaleTest timings come from the JVM test runner; a phone with an encrypted
  database will be several times slower.
* Statement import reads CSV / tab / semicolon text, Excel .xlsx and HTML ".xls". Old binary .xls and PDF statements
  need to be saved as .xlsx or CSV first. Lines without a learned category are added uncategorised.
* Suggested next phases: multi-currency, and an instrumented test pass on
  physical devices.
