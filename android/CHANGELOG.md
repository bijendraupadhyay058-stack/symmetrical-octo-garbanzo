# Changelog

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
