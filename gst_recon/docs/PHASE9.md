# Phase 9 – GSTR-9 Tables 15, 16 and 18; HSN lines in purchase registers

With this phase the GSTR-9 working covers Tables 4 to 18.

| Table | Source |
|---|---|
| 4–7, 9 | GSTR-1, GSTR-3B and the registers |
| 8 | GSTR-2B or the portal Table 8A file |
| 10–14 | the next year's GSTR-1 and the claim register |
| 15–16 | entered by the preparer (this phase) |
| 17 | GSTR-1 HSN summary |
| 18 | HSN lines of the purchase register (this phase) |

## 1. HSN in purchase registers and GSTR-9 Table 18

Registers with **HSN / SAC**, **unit (UQC)** and **quantity** columns, for example an
item-wise purchase register, are now read.

* Common headings are recognised automatically: *HSN/SAC*, *HSN Code*, *UOM*, *Unit*,
  *Qty*, *Billed Qty* and others. They can also be mapped on the mapping screen.
* Each document keeps its HSN lines: HSN, unit, quantity, taxable value and tax. They are
  stored as `invoices.hsn_json` (schema v8).

**Merging lines – a correction.** Before, lines of one invoice were merged only when their
tax rates differed. Two lines at the same rate with different HSN were therefore reported
as a *duplicate*. Lines are now merged when they differ by rate **or** HSN, and the HSN
lines are kept. The same HSN at the same rate twice is still flagged as a repeat.

**Table 18** adds up the purchase register's HSN lines for the year by HSN and unit:
quantity, taxable value and tax, with credit notes deducted. Documents imported without
HSN are counted, their value is shown, and the notes name them. Table 18 is never
presented as complete when it isn't.

Sample: `sample_data/purchase_register_itemwise_2025-04.csv`.

## 2. Tables 15 and 16 – entered figures

Neither table can be derived from returns or registers, so the preparer enters them. They
are stored, noted and audited like the GSTR-9C figures.

| Item | Meaning |
|---|---|
| `15A`–`15G` × `C S I X N P L` | refunds claimed / sanctioned / rejected / pending; demands, taxes paid against them, demands pending – by central, state/UT, integrated tax, cess, interest, penalty, late fee/others |
| `16A-T` | supplies received from composition taxpayers (value) |
| `16B` / `16C` × `T C S I X` | deemed supply under section 143 (job work); goods sent on approval and not returned |

How to enter them:

```bash
fintax-gst gstr9 set --client 1 --fy 2025-26 --item 15E-I --amount 25000 --note "DRC-07 dated 12-01-2026"
fintax-gst gstr9 set --client 1 --fy 2025-26 --item 16A-T --amount 45000 --note "Composition suppliers"
```

* Desktop: the item list on the *GSTR-9C* tab includes the Table 15 and 16 items.
* The figures appear in the GSTR-9 tab and on the *GSTR-9 Tables 15-16* sheet of the
  annual workbook.

## 3. Schema v8

| Change | Purpose |
|---|---|
| `invoices.hsn_json` | HSN lines of each imported document |
