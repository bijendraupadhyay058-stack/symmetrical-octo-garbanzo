# Phase 10 – e-invoice and e-way bill reconciliation

## 1. Sales register vs e-invoices (IRP) and e-way bills

Two more comparisons for the sales register, next to GSTR-1. They use the same matching
engine, review screens, reports and audit trail.

| Comparison | Right-hand side | Documents compared |
|---|---|---|
| `SALES_VS_EINV` | e-invoice report from the e-invoice portal (one row per IRN) | B2B, SEZ and export documents; B2C, nil/exempt and non-GST supplies are not e-invoiced and are left out |
| `SALES_VS_EWB` | report of e-way bills generated, from the e-way bill portal | every sales document |

### Importing the reports

Download the reports as Excel or CSV from the portals and import them as **e-Invoice
report** or **e-Way bill report**. The usual headings are recognised automatically, and
anything else can be mapped on the mapping screen:

* *Ack No*, *IRN*, *Doc No / Date / Type*, *Buyer GSTIN* and *Status* on the e-invoice
  report;
* *EWB No*, *Supply Type*, *Doc No / Date / Type*, *Other Party* / *To GSTIN*, *Assessable
  Value* and *Status* on the e-way bill report.

How rows are read:

* **Month.** Each document belongs to the month of its document date. No return period is
  asked for.
* **Recipient GSTIN.** *URP* (unregistered, exports) is read as a blank GSTIN, as in the
  sales register.
* **Cancelled IRN / e-way bill** (*CNL*, *Cancelled*). The row is imported with its status
  and a warning. It is not counted as reporting the document.
* **Rows that are not compared**, listed as *ignored* in the import log with the reason:
  * inward e-way bills (goods received);
  * e-way bills for delivery challans, bills of entry and *others*.
* **One row per IRN / e-way bill.** Rows are never merged. When the same invoice has a
  cancelled and a regenerated e-way bill, both are kept and are not reported as
  duplicates.
* **Latest import wins.** When the same IRN or e-way bill number is imported again, for
  example from a later report that shows it cancelled, the latest import is used.

### What the run explains

Lines keep their category. Explanations are added to the line's *reasons*; your remarks
stay yours.

| Situation | Explanation | Status |
|---|---|---|
| Sale in the register, its IRN / e-way bill cancelled | the IRN / e-way bill number was cancelled, the sale is still in the register: confirm whether it was made | Client clarification |
| B2B / export sale without an IRN | not a valid tax invoice for a taxpayer required to e-invoice | Pending review |
| Sale without an e-way bill, value ≥ threshold | needed if goods worth more than the threshold moved | Pending review |
| Sale without an e-way bill, value below the threshold | below the e-way bill threshold | No action (automatic) |
| Credit / debit note, or SAC 99 services only, without an e-way bill | no e-way bill needed | No action (automatic) |
| IRN / e-way bill without a sale in the register | record the sale, or confirm that it was cancelled | Pending review |

**Threshold.** The threshold is the setting `ewb_threshold`, ₹50,000 by default. Some
states use a different limit for movement within the state; set it per firm:

```bash
fintax-gst setting set ewb_threshold 100000
```

**Re-runs.** A status set automatically is re-applied on a re-run, so a changed threshold
takes effect. A status you set yourself is kept.

```bash
fintax-gst import --client 1 --source einv --file einvoice_report_2025-04.csv
fintax-gst import --client 1 --source ewb --file ewaybill_report_2025-04.csv
fintax-gst reconcile --client 1 --from 2025-04 --compare einv
fintax-gst reconcile --client 1 --from 2025-04 --compare ewb
```

On the desktop, use *Sales & GSTR-1*: *Import e-invoice report…*, *Import e-way bill
report…*, then *Sales register vs* (GSTR-1 / e-Invoice (IRP) / e-Way bill) and
*Reconcile*. The web view accepts both reports as uploads.

Sample files: `sample_data/einvoice_report_2025-04.csv` and
`sample_data/ewaybill_report_2025-04.csv`. The expected results are in
`EXPECTED_RESULTS.md`.

### A correction: review work stays with its comparison

A re-run carries the earlier status, remarks and assignee forward. Before, it took them
from the latest run of the period, whatever that run compared. A books vs GSTR-2A run
could therefore inherit statuses from a books vs GSTR-2B run. Now only runs of the same
comparison are used.

The GSTR-1 liability sheets are added only to sales vs GSTR-1 reports.

### Schema v9

| Change | Purpose |
|---|---|
| `invoices.irn` | e-invoice IRN |
| `invoices.ref_no` | e-invoice acknowledgement number / e-way bill number |
| `invoices.ref_status` | ACTIVE or CANCELLED |
