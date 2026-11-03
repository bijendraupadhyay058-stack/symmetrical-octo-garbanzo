# ITC module – review, claims, GSTR-3B, GSTR-9 and IMS

The ITC module adds statutory review on top of the reconciliation. Every output is a **flag
or working paper for a professional**. The software does not decide eligibility and does
not perform any action on the GST portal.

## 1. Rule engine (`fintax_gst/itc/rules.py`)

Each rule has:

* a code, a title and a **statutory reference**
* a severity (`high`, `medium`, `info`)
* an **effective-from / effective-to date**, checked against the document date (or, for
  period rules, the tax period)
* parameters, keywords or supplier GSTINs
* guidance text shown to the reviewer

You can enable, disable or edit any rule for **all clients** or for **one client** (the
client setting wins). You can also add custom keyword rules (`CUSTOM_…`). Every change is
recorded in the audit log.

| Code | What is flagged | Reference | Dates |
|---|---|---|---|
| `S16_2_AA` | Books document not matched to GSTR-2B | Section 16(2)(aa) | from 01-01-2022 |
| `ITC_NA_2B` | GSTR-2B marks ITC "not available" | GSTR-2B / 16(4) / PoS | – |
| `S16_4` | Unclaimed ITC past, or within 60 days of, the time limit | Section 16(4) | see §2 |
| `RCM` | Reverse-charge supply (ITC only after paying the tax) | 9(3)/9(4), 31(3)(f) | – |
| `CN_2B_NOT_BOOKED` | Supplier credit note in GSTR-2B, not in books | Section 34 | – |
| `IMS_REJECTED` / `IMS_PENDING` | Document rejected / kept pending in IMS | IMS | from 01-10-2024 |
| `RULE_37_180` *(off by default)* | Claimed invoice older than 180 days – verify payment | 16(2) 2nd proviso, Rule 37 | – |
| `S17_5_*` | Blocked-credit indicators from supplier name and narration: motor vehicles; food and catering; beauty/health; insurance; cab hire; clubs and fitness; employee travel; construction / works contract; personal use; gifts and samples | Section 17(5)(a)–(h) | – |
| `CLIENT_BLOCKED_GSTIN` | Suppliers the client never claims credit from | client-specific | – |
| `R36_4` | Provisional-credit limit by period: 20% / 10% / 5% | Rule 36(4) | 09-10-2019 to 31-12-2021 |

Keyword rules match whole words only, so "cab" does not match "Cabinet". Narration is read
from columns such as *Narration*, *Description* or *Expense head*.

## 2. Section 16(4) time limit (`itc/deadlines.py`)

* **FY 2021-22 onwards:** 30 November following the end of the financial year (Finance
  Act 2022, w.e.f. 01-10-2022).
* **Earlier years:** due date of the September GSTR-3B following the year (20 October).
  Section 16(5) gives relief for FY 2017-18 to 2020-21.

In both cases the annual return date applies if it is earlier. A debit note counts from
its own date.

## 3. Reviewer decisions

Each flag can be **confirmed** or **dismissed**. Dismissing requires a reason. Decisions
are stored per document and rule (`itc_reviews`), audited, and kept across re-runs.
Dismissed flags remain visible in the review and in the workbook.

## 4. Claim register (`itc_claims`)

| Action | Rule enforced |
|---|---|
| `CLAIM` | once per document. A second claim in any period is refused, so ITC is never counted twice across periods. Only books documents can be claimed. |
| `REVERSE` | up to the net ITC claimed, per tax head. A reason is required. Optional rule reference (e.g. `RULE_37_180`, `S17_5_…`). |
| `RECLAIM` | up to the amount reversed and not yet reclaimed. A reason is required. |

*Claim eligible documents of a run* claims every books document that GSTR-2B confirms and
that has no open high or medium flag. Everything else is left for the reviewer.

## 5. ITC summary buckets

The summary shows:

* ITC as per books, ITC in GSTR-2B and ITC claimed in GSTR-3B 4(A)
* from the claim register: claimed, reversed and reclaimed
* ITC not yet claimed, and ITC claimed that still needs verification
* ITC carried forward (not yet in GSTR-2B)
* potentially blocked under 17(5), and time-limit exposure under 16(4)
* credit-note adjustments, and credit notes in GSTR-2B not in books
* reverse charge, ISD credits and imports

These are views over documents, so one document can appear in more than one bucket.

## 6. GSTR-3B Table 4 working (`itc/table4.py`)

For each period there are three columns:

* **GSTR-2B (auto).** B2B/CDNR goes to 4(A)(5), RCM to 4(A)(3), ISD to 4(A)(4), bills of
  entry to 4(A)(1), and ITC marked not available to 4(D)(2).
* **Books / review.** Taken from the claim register for the period. Reversals with a
  17(5) or Rule 38/42/43 reference go to 4(B)(1), others to 4(B)(2), and reclaims to
  4(D)(1). If the register has no entries for the period, matched books documents less
  open blocked flags are used.
* **GSTR-3B as filed.** Imported from the portal JSON (`itc_elg`) or the CSV/Excel template.

Differences are classified as:

* **Statutory**
  * 4(A)(5) is above GSTR-2B. Above 2022 this checks Section 16(2)(aa); for 2019–2021
    periods the Rule 36(4) allowance applies.
  * GSTR-2B ITC marked not available is not fully reported in 4(D)(2).
  * Claims on documents with open 17(5) flags, or on documents rejected in IMS.
* **Timing:** books ITC not yet in GSTR-2B, earlier bookings now reflected, IMS pending.
* **Accounting:** value differences on matched documents, duplicates in books, GSTR-2B
  documents not booked.

## 7. GSTR-9 Table 8 (`itc/annual.py`)

* **8A:** GSTR-2B (B2B, B2BA, CDNR) for documents dated in the year. Reverse charge, ISD,
  imports and "not available" ITC are excluded. GSTR-2B periods from April to a cut-off
  (default November of the next year) are included.
* **8B:** GSTR-3B 4(A)(5) of the year.
* **8C:** the year's documents claimed in the next year's periods, from the claim register.
* **8D** = 8A − (8B + 8C).

The portal's Table 8A is authoritative. Set the cut-off to match its basis, and enter the
portal figure to compare. The annual workbook contains Table 8, month-wise ITC, 8A
documents not in books, books documents not in 8A, the claim register, and the rules in
force.

## 8. IMS comparison (`itc/ims.py`)

Each IMS document (Accepted, Rejected, Pending, No action / deemed accepted) is matched to
books and GSTR-2B. It is flagged when:

* it is **rejected** but recorded in books, or still present in GSTR-2B (recompute
  GSTR-2B on the portal)
* it is **pending** but already in GSTR-2B
* it is **accepted** but not in books, or not in GSTR-2B
* a credit note is accepted but not recorded
* its values differ from books
* it is an amendment

A note appears for periods before October 2024. Nothing is ever sent to the portal.
