# Phase 7 – advances, tax payments and the GSTR-9C reconciliation statement

## 1. GSTR-1 advances (Tables 11A / 11B)

The GSTR-1 JSON sections `at` (advances received) and `txpd` (advances adjusted against
invoices) are now imported as section totals. Their amendments (`ata`, `txpda`) are
imported too. Before, these sections were reported as "not compared".

* **GSTR-1 vs GSTR-3B liability.** Tax on advances received, less advances adjusted, is
  part of GSTR-3B 3.1(a), so it is included there. It is not compared with the sales
  register, which has no advances.
* **GSTR-9 4F** is the net of advances received and adjusted in the year. Without these
  sections, 4F is nil and the working says so.
* Amendments of advances are listed for manual entry, like the other summary-level
  amendments.

## 2. GSTR-3B Table 6.1 – payment of tax

GSTR-3B imports now also read Table 6.1:

| Code | Meaning |
|---|---|
| `61CASH` | tax paid in cash |
| `61ITC` | tax paid through ITC (by the tax head of the liability) |
| `61INT` | interest paid in cash |
| `61FEE` | late fee paid in cash |

* **Portal JSON.** The `tx_pmt` block is read: `pdcash` for cash, interest and late fee,
  and `pditc` for ITC. For ITC, `x_pdy` is taken as credit of tax *x* used for the
  liability of tax *y*. The preview asks you to check the totals against the return as
  filed, because the layout of this block is not documented publicly.
* **Template (CSV/Excel).** Use the table codes above, e.g. `6.1 cash` or `61ITC`, in the
  *Table* column.

**GSTR-9 Table 9** now shows, for each tax head:

* tax payable per Table 4N;
* tax declared in GSTR-3B 3.1(a)+(b)+(d);
* tax paid in cash and through ITC, and the total paid;
* *payable − paid*.

Interest and late fee paid are listed too. Months without Table 6.1 data are named in the
notes.

## 3. GSTR-9C reconciliation statement

Prepared with the GSTR-9 working: *GSTR-3B & annual → GSTR-9C*, `fintax-gst gstr9c`, and
the *GSTR-9C Reconciliation* and *GSTR-9C Table 9* sheets of the annual workbook (also
downloadable from the web view).

| Table | Content | Sources |
|---|---|---|
| 5 | Turnover per audited financial statements (5A), adjustments 5B–5O, adjusted turnover 5P, turnover per GSTR-9 (5Q = GSTR-9 5N), un-reconciled 5R = Q − P | 5A–5O entered; **5A defaults to the sales-register turnover** |
| 7 | 5P less exempt/nil/non-GST (7B), zero-rated without payment (7C) and reverse-charge supplies (7D) = 7E; taxable turnover per GSTR-9 (7F = 4N − 4G); un-reconciled 7G = F − E | 7B–7D default from the sales register, can be entered |
| 9 | Tax by rate per books (sales register, classified into the GST slabs by the document's effective rate; notes shown separately) vs tax paid per GSTR-9 Table 9; interest, late fee, penalty and others entered | sales register, GSTR-3B 6.1 |
| 12 | ITC per audited accounts or books (12A), ITC of earlier years claimed (12B), ITC to be claimed later (12C), 12D = A + B − C, ITC per GSTR-9 (12E = 7J), un-reconciled 12F = E − D | 12A defaults to the purchase register; 12B/12C entered |
| 6, 8, 10, 13 | Reasons for un-reconciled differences | entered text |

**Entered figures** are stored per client and financial year (`gstr9c_inputs`, schema v6):

* each entry holds an amount, a note and who changed it;
* every change is audited with its before and after values;
* entering an item requires the *review* permission;
* clearing an item brings the default back.

```bash
fintax-gst gstr9c set --client 1 --fy 2025-26 --item 5A --amount 785000 --note "AFS note 21"
fintax-gst gstr9c set --client 1 --fy 2025-26 --item R6 --note "Advance received in May 2025"
fintax-gst gstr9c --client 1 --fy 2025-26 --out reports/
```

**Defaults** are always marked *default – …*, highlighted on the desktop, and named in
the notes, which ask for them to be replaced by the audited figures before certifying. A
note also flags any un-reconciled difference that has no reason recorded.

Entered GSTR-9C figures travel with the client's encrypted sync packages and are removed
by a client purge.

**Out of scope:**

* Table 14 (ITC on expenses), which needs expense ledgers;
* the self-certification of the statement, which is the taxpayer's.

![GSTR-9C](screenshots/gstr9c.png)
