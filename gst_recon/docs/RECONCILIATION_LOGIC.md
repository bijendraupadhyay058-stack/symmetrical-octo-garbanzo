# Reconciliation logic

This document describes exactly what the engine (`fintax_gst/engine/matcher.py`) does, so
a reviewer can verify any result in the workbook by hand.

## 1. Inputs

* **Books records** – purchase register documents whose *booking period* falls in the
  reconciliation period. The booking period is the voucher-date month (TallyPrime "Date"
  column) or, if absent, the `--period` given at import, or the invoice-date month.
* **GSTR-2B records** – documents whose GSTR-2B *return period* falls in the period
  (from the JSON `rtnprd`, the Excel "Tax Period" or the `--period` given at import).
* **Prior-period books** – books records of earlier periods that have not been paired in a
  reconciliation of an earlier period. Only used to explain GSTR-2B documents (step 5).

Every record keeps its original invoice number, values, file name and row number.

## 2. Sign convention

Amounts are stored as positive magnitudes plus a document type *from the supplier's point
of view*: Invoice, Credit Note, Debit Note (as in GSTR-2B). Credit notes are negative in
all totals.

* TallyPrime: a **Debit Note** voucher (purchase return) is the supplier's **Credit Note**;
  a **Credit Note** voucher is the supplier's **Debit Note**.
* A document with negative values and no explicit note type is treated as a credit note
  (with a warning). A document with both positive and negative values is rejected.

## 3. Normalisation

| Key | Rule | Example |
|---|---|---|
| GSTIN | upper case, spaces/hyphens removed, format + check digit validated | ` 27aapfu0939f1zv` → `27AAPFU0939F1ZV` |
| Invoice no. (normalised) | upper case; spaces `- / \ . _ , # : ' "` removed | `INV/001/26`, `inv-001-26` → `INV00126` |
| Invoice no. (loose) | normalised, then leading zeros of every digit run removed | `PP-0007`, `PP-7` → `PP7` |

## 4. Passes

Each pass only considers records that are still unpaired. Records are processed in a
fixed sort order (GSTIN, type, normalised number, date, amounts, id), so the output is
identical for identical inputs regardless of file or row order.

0. **Duplicates.** Within one source, records with the same GSTIN, document type,
   normalised number and financial year are all marked *Duplicate in Books / Duplicate in
   GSTR-2B* and excluded from automatic pairing. The other side's copy of that document is
   marked *Probable Match* listing the duplicate entries as candidates.
1. **Exact key** – GSTIN + document type + normalised number. If a key has exactly one
   record on each side, they pair. If a key has several (e.g. the same number in two
   financial years), only pairs that are *mutually unique within the date tolerance* pair.
2. **Loose key** – as 1 with the loose number (reported as an invoice-number variation).
3. **Amendments** – a GSTR-2B amendment (B2BA/CDNRA) whose *original* number equals the
   books number → *Amended Invoice*.
4. **Previous period** – remaining GSTR-2B documents against prior-period books (keys 1
   and 2) → *Previous-Period Invoice*. Those books amounts are not added to this period's
   books totals.
5. **GSTIN mismatch** – same document type and number, taxable value and total GST within
   tolerance, different GSTIN → *Probable Match* (never confirmed automatically). The
   reason states whether the PAN is the same (another registration of the supplier).
6. **Fuzzy invoice number** – within the same GSTIN and document type. Scores:
   number similarity (RapidFuzz ratio), amount agreement, date agreement;
   confidence = 60 % number + 30 % amount + 10 % date. A candidate needs number
   similarity ≥ threshold (default 85), or ≥ 60 when amounts and date agree exactly.
   A pair is *suggested* only if each is the other's best candidate and beats the
   runner-up by the minimum gap (default 5 points); otherwise the record is marked
   ambiguous with all candidates listed. Suggestions are always *Probable Match
   Requiring Review*.
7. **Missing** – books records left → *Available in Books but Missing in GSTR-2B*;
   GSTR-2B records left → *Available in GSTR-2B but Missing in Books* (flagged if dated
   before the period).

## 5. Classifying a pair

For a pair from passes 1–4 the engine compares, books minus GSTR-2B, signed:

* invoice number text (case/whitespace ignored) → number variation
* invoice date → date difference; **beyond the date tolerance the pair is demoted to a
  Probable Match** (same reference but far-apart dates may be different documents)
* taxable value, IGST, CGST, SGST, cess – each separately; a difference larger than the
  amount tolerance (default ₹1.00 per component) is reported; smaller ones are noted as
  rounding
* IGST vs CGST/SGST with equal total GST → "charged under a different head"

| Differences found | Category |
|---|---|
| none | Fully Matched |
| only number format | Matched with Invoice Number Variation |
| only date | Matched with Date Difference |
| only taxable value | Matched with Taxable Value Difference |
| only IGST | Matched with IGST Difference |
| only CGST and/or SGST | Matched with CGST/SGST Difference |
| only cess | Matched with Cess Difference |
| two or more of the above | Matched with Multiple Differences |
| any difference on a credit/debit note | Credit/Debit Note Difference |
| GSTR-2B record is an amendment | Amended Invoice |
| matched to a prior-period booking | Previous-Period Invoice |

Match level: 1 perfect, 2 number variation, 3 date difference, 4 amount difference,
5 probable. Every individual difference is also listed in *Reasons* and *Flags*.

GSTR-2B "ITC availability = No" and reverse-charge supplies are flagged on any line.

## 6. Totals and integrity

* Each books record (current period) and each GSTR-2B record appears in **exactly one**
  line; the engine raises an error otherwise. A record is never paired twice.
* Books totals are summed over books records, GSTR-2B totals over GSTR-2B records.
  A matched pair therefore contributes once to each side – never double-counted.
* The engine checks that line totals equal input totals before returning.
* The workbook's Executive Summary recomputes each category with `COUNTIF`/`SUMIFS`
  against the Complete Reconciliation sheet and shows **OK/CHECK**.

**ITC at risk** (indicator, not a legal conclusion): positive books ITC on lines with no
confirmed GSTR-2B document (missing, duplicate, probable), plus, for paired lines, the
excess of books ITC over GSTR-2B ITC, or the full books ITC where GSTR-2B shows ITC as not
available.

## 7. Repeatability

The run stores the settings, engine version and a SHA-256 fingerprint of all inputs.
The same inputs and settings always produce the same lines (tested, including with
shuffled input order). Re-running a period carries forward status, remarks, assignee and
action date of lines that pair the same documents in the same category.

## 8. Manual decisions

The reviewer can **confirm** a suggested pair, **pair** a books-only line with a
GSTR-2B-only line, **unmatch** any pair, or mark a line **Pending Client or Supplier
Clarification**. Each action is applied to the open run at once and audited.

Confirmations and pairs are stored as `MATCH` decisions, unmatches as `REJECT` decisions
(table `match_decisions`). Every later run of the client applies them:

* `MATCH` pairs are applied **before** all automatic passes and classified exactly like
  other pairs, under the category *Manually Matched* (differences are still listed).
  A manual match whose only difference is the invoice-number text is set to *Resolved*.
* `REJECT` pairs are never formed by any automatic pass (key, amendment, previous period,
  GSTIN mismatch or fuzzy).
* A new decision on the same pair replaces the old one. A new `MATCH` for a document
  replaces its earlier `MATCH`.
* Documents must have the same document type. A credit note is never paired with an invoice.
* *Pending Clarification* is kept when the period is re-run, unless the documents are
  now fully matched.

After any change the run's summary is recalculated. Every document still appears exactly
once, so the totals do not change.

## 9. What the engine never does

* It never confirms a fuzzy, GSTIN-mismatch or out-of-tolerance date match.
* It never alters, merges or deletes a source value (rate-wise lines of one document in
  one file are summed into one document and this is reported in the import preview).
* It does not decide legal ITC eligibility; flags are for professional review.
