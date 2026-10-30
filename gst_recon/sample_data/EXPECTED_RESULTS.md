# Demo dataset – expected reconciliation outcome

Client: Shree Ganesh Traders (27AAPFU0939F1ZV), FY 2025-26, period April 2025.

| # | Scenario | Expected category | Note |
|---|---|---|---|
| 1 | Perfect match 1 | Fully Matched | All fields agree |
| 2 | Perfect match 2 | Fully Matched | All fields agree |
| 3 | Perfect match 3 | Fully Matched | All fields agree |
| 4 | Perfect match 4 | Fully Matched | All fields agree |
| 5 | Perfect match 5 | Fully Matched | All fields agree |
| 6 | Perfect match inter-state 1 | Fully Matched | IGST invoice |
| 7 | Perfect match inter-state 2 | Fully Matched | IGST invoice |
| 8 | Perfect match inter-state 3 | Fully Matched | IGST invoice |
| 9 | Invoice number format | Matched with Invoice Number Variation | Slash vs hyphen |
| 10 | Leading zeros | Matched with Invoice Number Variation | PP-7 vs PP-0007 |
| 11 | Date difference | Matched with Date Difference | 2 days apart |
| 12 | Taxable value difference | Matched with Taxable Value Difference | Taxable differs by 500, tax agrees |
| 13 | IGST difference | Matched with IGST Difference | 18% booked, 12% reported |
| 14 | CGST/SGST difference | Matched with CGST/SGST Difference | CGST and SGST each lower by 200 |
| 15 | Multiple differences | Matched with Multiple Differences | Date and values differ |
| 16 | Rounding within tolerance | Fully Matched | 50 paise differences are within ₹1 tolerance |
| 17 | Missing in GSTR-2B 1 | Available in Books but Missing in GSTR-2B | Supplier has not filed |
| 18 | Missing in GSTR-2B 2 | Available in Books but Missing in GSTR-2B | Supplier has not filed |
| 19 | Missing in books | Available in GSTR-2B but Missing in Books | Invoice not booked |
| 20 | Missing in books (dated March) | Available in GSTR-2B but Missing in Books | Old invoice reported late; not in any books |
| 21 | Duplicate in books | Duplicate in Books | Entered twice in Tally |
| 22 | Credit note matched | Fully Matched | Purchase return (Debit Note voucher in Tally) |
| 23 | Credit note difference | Credit/Debit Note Difference | Credit note value differs |
| 24 | Amended invoice | Amended Invoice | Supplier amended invoice number in B2BA |
| 25 | Probable match (typo) | Probable Match Requiring Review | Digits transposed – review |
| 26 | GSTIN mismatch | Probable Match Requiring Review | Booked under supplier's Karnataka GSTIN; supplier reported from Maharashtra registration |
| 27 | ITC not available | Fully Matched | Matched, but GSTR-2B marks ITC unavailable – at risk |
| 28 | Blocked-credit indicator | Fully Matched | Matched; ITC review flags Section 17(5)(b)(i) food / gifts for the reviewer |
| 29 | Reverse charge (GTA) | Fully Matched | Matched; ITC available only after RCM tax is paid (GSTR-3B 4(A)(3)) |
| 30 | Previous-period invoice | Previous-Period Invoice | Booked in March 2025, reflected in April GSTR-2B |

Rows that must be rejected at import (books):

* LH-55: Unregistered supplier – no GSTIN
* PPK/499: Invalid date 31-04-2025

## ITC module (Phase 3)

* `gstr2b_2025-04.json` also carries an ISD credit (₹1,800) and a bill of entry (IGST ₹1,800).
* `gstr3b_2025-04.json`: 4(A)(5) is ₹2,000 more than GSTR-2B supports → possible statutory discrepancy; 4(B)(1) reverses ₹1,440 for ANC/77 (Section 17(5)).
* `ims_2025-04.json`: GCH-2201 rejected but present in GSTR-2B (recompute GSTR-2B); KTX-2290 kept pending (explains why it is missing in GSTR-2B); OSL/377 accepted but not in books.
* ITC review flags ANC/77 (Section 17(5)(b)(i) food and (h) gifts indicators), SRW-310 (reverse charge), KTX-2301 (GSTR-2B ITC not available) and all books documents not in GSTR-2B (Section 16(2)(aa)).

## Outward supplies (Phase 4)

* `tally_sales_register_2025-04.xlsx` vs `gstr1_2025-04.json`: 5 perfect B2B matches, one invoice not in GSTR-1, one in GSTR-1 only, a taxable-value difference, a wrong customer GSTIN (probable), a credit note and an SEZ supply; B2C, export and exempt sales are compared at summary level.
* GSTR-1 B2CS leaves out ₹1,000 taxable value; GSTR-3B 3.1(a) tax is ₹3,600 lower than GSTR-1 → possible short payment in the liability working.

## GSTR-9 Table 8A (Phase 5)

* `gstr9_table8a_2025-26.json` holds the April GSTR-2B documents (excluding reverse charge), KTX-2290 (missing in April GSTR-2B, filed late by the supplier) and OSL/412 dated May 2025, which is not in the books.
* Books vs Table 8A for FY 2025-26: KTX-2290 matches; OSL/412 and OSL/377 are in 8A but not in the books; KTX-2301 (ITC not available) stays out of the 8A total.

## GSTR-9 and GSTR-9C (Phases 6–7)

* `gstr1_2025-05.json`: a new B2B invoice (SGT/25-26/0021), a B2BA reducing SGT/25-26/0013 from 66,000 to 60,000 (GSTR-9 4L), a B2CSA revising April's B2C total (listed for manual entry) and an advance of 50,000 received (Table 11A → GSTR-9 4F, GSTR-3B 3.1(a)).
* `gstr3b_2025-04.json` Table 6.1: the whole April liability set off from ITC, and 120 of interest paid in cash (GSTR-9 Table 9).
* GSTR-9C: 5A defaults to the sales-register turnover (761,000) until the audited figure is entered; 5Q is GSTR-9 5N.

## GSTR-9 Tables 10–17 and GSTR-9C Table 14 (Phase 8)

* `gstr1_2026-04.json` (next year): B2BA raising SGT/25-26/0005 from 65,000 to 70,000 and SGT/25-26/0099 of 30-03-2026 reported late → GSTR-9 2025-26 Table 10 = 13,000; SGT/26-27/0001 belongs to 2026-27.
* GSTR-1 HSN summaries (Table 12): April includes the 1,000 B2C sale left out of B2CS, so Table 17 exceeds the GSTR-1 sections by 1,000.
* `expense_ledger_2025-26.csv`: ledger heads placed in GSTR-9C Table 14 rows by keyword (salaries and staff welfare in 14H, repairs to machinery in 14M, the computer in 14O, audit fees in 14N).

## GSTR-9 Tables 15, 16 and 18 (Phase 9)

* `purchase_register_itemwise_2025-04.csv`: the first five April invoices, each in two lines at the same rate with different HSN (7208, 7318) – merged into one document each; GSTR-9 Table 18 shows both HSN.
* Tables 15 and 16 are entered (items such as 15E-I, 16A-T).

## e-Invoice and e-way bill (Phase 10)

* `einvoice_report_2025-04.csv` vs the sales register: 9 documents match (B2B, credit note, SEZ, export); the IRN of SGT/25-26/0011 is cancelled although the sale is still in the register (client clarification); SGT/25-26/0014 has no IRN; SGT/25-26/0012 has an IRN but is not in the register. B2C and exempt sales are not e-invoiced and are left out.
* `ewaybill_report_2025-04.csv`: 7 documents match (SGT/25-26/0002 through its regenerated e-way bill); SGT/25-26/0005 (₹76,700) has none; 12 documents below ₹50,000 or credit notes need none (no action); SGT/25-26/0018 has an e-way bill but is not in the register; a delivery challan and an inward e-way bill are not compared.
