# Testing

## Automated

| Suite | Command | Covers |
|---|---|---|
| Unit / integration (Vitest, IndexedDB via fake-indexeddb) | `npm test` | money parsing/formatting, IST dates & FY, Cash Book example from the spec, back-dated entries, cash vs bank separation, contra, cancellation, negative-cash block (incl. later-day shortfall), payment-mode/account rules, locked periods, opening-balance corrections, duplicate detection & idempotent saves, fee bills/allocations/outstanding, sync (offline capture, retry without duplicates, conflict preservation, voucher collision, pull never overwrites pending edits), all 15 reports' totals, Excel round-trip, PDF text, backup checksum/restore |
| Database (PostgreSQL 15+) | `npm run test:db` | migrations apply cleanly; RLS isolation between users; anonymous access denied; deletes refused; audit append-only; cash-negative, mode/account, contra, voucher renumbering, allocation and books-lock triggers; sync RPC idempotency and version conflicts |
| End-to-end (Playwright, Pixel 7 + desktop) | `npm run build && npm run test:e2e` | setup, opening balance, income, expense, dashboard totals, overspend blocked, UPI not touching cash, Cash Book, offline entry, cancellation with reason, report Excel download, no horizontal scroll on phone, sample-data balances, offline PWA navigation |

## Manual checklist (Android phone, Chrome)

**Authentication & security**
- [ ] Create account → confirmation email → sign in. Wrong password shows an error.
- [ ] Forgot password → email link → choose new password → sign in with it.
- [ ] Leave the app idle beyond the auto-lock time → lock screen; unlock with password; enable fingerprint and unlock with it.
- [ ] Sign out shows a warning if entries are pending upload.
- [ ] A second account cannot see the first account's data.

**Entries & balances**
- [ ] Set opening cash ₹10,000 dated 1 April. Add cash receipt ₹5,000 and cash expense ₹1,500 → Cash Book closing ₹13,500.
- [ ] Add a UPI receipt → cash balance unchanged; Bank/UPI book increases.
- [ ] Try a cash expense larger than cash in hand → refused with the date of shortfall.
- [ ] Add a back-dated entry → later running balances and next month's opening change.
- [ ] Edit an entry → history shows the change. Cancel an entry (reason required) → struck through, excluded from totals, listed in Voucher Register.
- [ ] Double-tap Save → only one entry is created.
- [ ] Contra: cash deposited into bank → cash down, bank up, income/expense unchanged.

**Clients & fees**
- [ ] Add client, raise a fee bill, record a part receipt adjusted to it → outstanding reduces; Fee Register shows Part Paid.
- [ ] Client page: payment history, statement PDF, WhatsApp reminder opens with the text.
- [ ] PAN is masked; viewing it asks for the password.

**Reports & exports**
- [ ] Each report opens; change period/client/category/mode filters.
- [ ] Download PDF and Excel; check totals match the screen and dates are in order; Excel cells are numbers.
- [ ] Print a Cash Book (A4). Share a receipt to WhatsApp (file attached on Android).

**Offline & sync**
- [ ] Turn on airplane mode → add entries → header shows *Offline · n pending*.
- [ ] Turn off airplane mode → badge becomes *Synced*; entries appear on a laptop signed into the same account.
- [ ] Edit the same entry on phone and laptop while one is offline → *Sync Status* shows the conflict with both versions; choose one.

**PWA & UI**
- [ ] Install from Chrome; icon, splash screen and full-screen mode; shortcuts on long-press.
- [ ] Open the app with no network after first use – all screens load.
- [ ] Deploy a new version → *Update* banner appears; data still present after updating.
- [ ] Light/Dark theme; screens usable at 360px width; no sideways scrolling.

**Backup**
- [ ] Download a backup; restore it on another device/account → entries added, nothing overwritten; a modified backup file is rejected.
- [ ] Demo workspace: open, check balances (Cash ₹11,400, Bank ₹58,000, UPI ₹501), reset, exit – real books unaffected.
