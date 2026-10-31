# Phase 12 – direct Tally import

## 1. Purchase and sales registers straight from Tally

No Excel export is needed any more. FIN TAX PRO can read vouchers from TallyPrime (or
Tally.ERP 9):

* **live**, over Tally's XML interface; or
* from an **XML file** exported from Tally.

### In Tally (once)

1. Open *F1 Help → Settings → Connectivity* and set *TallyPrime acts as* to **Server**
   (or *Both*). The port is **9000** by default.
2. Keep the client's company open in Tally while importing.

Tally answers only on the PC it runs on, or on the office network. FIN TAX PRO talks to
it directly and never through an internet proxy.

### Importing

* **Desktop.** Use *Reconcile → Import from Tally…* for purchases, or *Sales & GSTR-1 →
  Sales from Tally…* for sales. Give the Tally address (setting `tally_url`, by default
  `http://localhost:9000`) and pick the company. The vouchers of the selected months are
  fetched, then shown in the usual import preview before anything is saved.
* **Command line:**

  ```bash
  fintax-gst tally companies
  fintax-gst tally import --client 1 --company "Shree Ganesh Traders" --from 2025-04 --to 2025-06
  fintax-gst tally import --client 1 --company "Shree Ganesh Traders" --from 2025-04 --source sales --preview
  ```

* **Traceability.** Each fetch is saved under the data folder (`tally/<GSTIN>_<from>_<to>_<time>.xml`)
  and audited. The import record points to that file, like any other import.
* **XML files.** A file exported from Tally (*Export → XML* of the Day Book or a voucher
  register) can be imported like an Excel register, from the desktop, the CLI or the web
  upload.

### How a voucher is read

| Field | Source |
|---|---|
| Party, GSTIN | `PARTYLEDGERNAME`, `PARTYGSTIN` |
| Invoice number | purchases: the supplier's bill number (*Reference*); if there is none, the voucher number, with a warning. Sales: the voucher number |
| Dates | voucher date (booking month); supplier's bill date (*Reference date*) as the invoice date |
| Document type | voucher type: *Purchase* / *Sales* → invoice; a *Debit Note* voucher (purchase return) → the supplier's credit note; and so on, as for the Excel register |
| Tax | GST duty ledgers. They are identified by the duty head in the ledger master, which a live fetch reads; otherwise by name (CGST / SGST / UTGST / IGST / Cess, or *Central / State / Integrated Tax*) |
| Invoice value | the party ledger's amount |
| Taxable value | the other ledgers, or in item-invoice mode the items' accounting allocations; round-off is excluded |
| HSN | the item's HSN, when a voucher has a single item line |

Vouchers that are not imported are listed as *ignored* in the import log, with the reason:

* cancelled and optional (memorandum) vouchers;
* other voucher types, such as payments and journals.

The data then goes through the same validation, duplicate checks and preview as any
other register.

### Tested against a simulation, not real Tally

TallyPrime is not available in the development environment. The import follows Tally's
documented XML format, and is tested against a **simulated Tally server**
(`scripts/tally_simulator.py`) and the sample `sample_data/tally_purchase_vouchers_2025-04.xml`.
That sample gives exactly the same 28 documents as the TallyPrime Excel register sample.

**Before relying on it for a client, import one month both ways (Excel register and direct)
and compare the totals.** Ledger names, voucher types and TDL customisations differ
between companies.

To try the screens without Tally:

```bash
python scripts/tally_simulator.py sample_data/tally_purchase_vouchers_2025-04.xml
```

Then import from `http://localhost:9000`, company *Shree Ganesh Traders*.

### Also fixed

The import progress bar showed more than 100% (and a very long bar on the command line)
when a file had fewer documents than one save batch.
