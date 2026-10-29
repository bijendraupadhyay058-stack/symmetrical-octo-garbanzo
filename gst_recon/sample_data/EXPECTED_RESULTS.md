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
| 28 | Previous-period invoice | Previous-Period Invoice | Booked in March 2025, reflected in April GSTR-2B |

Rows that must be rejected at import (books):

* LH-55: Unregistered supplier – no GSTIN
* PPK/499: Invalid date 31-04-2025
