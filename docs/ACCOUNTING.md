# Accounting Rules

## Money, dates and financial years
- All amounts are integer **paise** in the app and `BIGINT` paise in PostgreSQL – never floating point. Rupees are produced only for display, charts and Excel cells.
- Dates are calendar dates in **Asia/Kolkata** (`YYYY-MM-DD`). "Today" is computed in IST even if the device is set to another time zone.
- Financial year = 1 April to 31 March. Voucher and fee-bill numbers restart each FY.

## Ledgers
| Entry | Payment mode | Ledger affected | Income/Expense? |
|---|---|---|---|
| Receipt | Cash | Cash Book (+) | Income |
| Receipt | UPI / Bank transfer / NEFT-RTGS / Cheque / Other | that Bank or UPI book (+) | Income |
| Payment | Cash | Cash Book (−) | Expense |
| Payment | UPI / Bank / … | that Bank or UPI book (−) | Expense |
| Contra (cash deposit / withdrawal / UPI → bank) | – | − from one account, + to the other | **Neither** |

A cash payment method can only post to a cash account and a non-cash method can never post to cash (enforced in the app *and* by a database trigger).

**Running balance:** Opening balance + all receipts − all payments up to the day. The opening of any period = opening balance + every movement before the period, so a back-dated entry automatically changes every later balance and the next year's opening. *Opening + Receipts − Payments = Closing* holds for every report.

**Negative cash is prevented:** a cash payment (or editing/cancelling an entry) is refused if the end-of-day cash balance on *any* date would fall below zero. The authorised way to correct cash is an **opening-balance correction**, which requires a reason and explicit confirmation and is kept as history (the earlier value is never overwritten).

## Vouchers
`CR` cash receipt · `BR` bank/UPI receipt · `CP` cash payment · `BP` bank/UPI payment · `CT` contra, e.g. `CR/26-27/014`. Numbers are never re-used; cancelled vouchers keep their number and appear in the Voucher Register. If two offline devices pick the same number, the server renumbers the later one and both devices receive the final number.

## Edits, cancellations and audit
- Records have immutable UUIDs. Nothing is deleted: transactions and fee bills are **cancelled** with a reason; clients, categories and accounts are deactivated.
- Every create/edit/cancel/reinstate writes an audit entry with before/after values (app side, including offline edits) and the database writes its own tamper-proof audit rows.
- *Settings → Security → Lock books* prevents any change on or before a date (year-end closing).

## Fee billing vs collection
A **fee bill** is a demand on a client (memorandum, accrual view). It is **not income**. Income is recognised only when a **receipt** is recorded. A receipt can be *adjusted* against one or more bills (oldest first is suggested); the bill's outstanding = fees charged − receipts adjusted. Receipts not adjusted to any bill are shown as *on account*. Cancelling a receipt automatically restores the bill's outstanding.

## Cash basis vs accrual
Cash Book, Bank Book, Receipts & Payments, registers and the monthly summary are **cash-basis** statements of money actually received and paid. They are labelled as such and are not a Profit & Loss account. The Financial Year Summary shows fees billed vs collected separately as a memorandum accrual view.

## Sample data walk-through
Opening: Cash ₹10,000 · Bank ₹50,000 · UPI ₹0. Fee bills: Sharma ₹4,000, Verma ₹8,000, Gupta ₹2,500.

| # | Entry | Mode | Voucher | Cash | Bank | UPI | Income | Expense |
|---|---|---|---|---|---|---|---|---|
| 1 | GST Return Filing Fees (Sharma) | Cash | CR/…/001 | +2,500 | | | 2,500 | |
| 2 | Income Tax Return Fees (Gupta) | UPI | BR/…/001 | | | +1,500 | 1,500 | |
| 3 | Accounting Fees (Verma) | Bank | BR/…/002 | | +8,000 | | 8,000 | |
| 4 | Office Stationery | Cash | CP/…/001 | −750 | | | | 750 |
| 5 | Internet | UPI | BP/…/001 | | | −999 | | 999 |
| 6 | Travelling | Cash | CP/…/002 | −350 | | | | 350 |
| | **Closing** | | | **11,400** | **58,000** | **501** | **12,000** | **2,099** |

Net cash movement = 12,000 − 2,099 = ₹9,901. Outstanding fees = (4,000 − 2,500) + (8,000 − 8,000) + (2,500 − 1,500) = **₹2,500**. These figures are asserted by `tests/reports.test.ts` and `e2e/cashbook.spec.ts`.

The demo lives in a separate on-device database (`fintaxpro-demo`) that is never synced; *Settings → Sample Data* can reset it without touching real books.
