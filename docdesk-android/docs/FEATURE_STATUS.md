# DocDesk – feature status against the accountant/tax-consultant specification (v1.14.0)

How to read this table:

- **Implemented and tested**: the feature is built and covered by automated tests.
  - **Core tests** are pure-Kotlin unit tests, run on every build.
  - **Engine tests** run Android code under Robolectric in GitHub Actions on generated sample PDFs, Word and Excel files.
  - **Screen tests** check that every screen opens and shows its main content.
  - **Not yet done:** testing on physical phones of different sizes and Android versions. Do it with the manual test plan in [TESTING.md](TESTING.md) before a Play Store release.
- **Partly implemented**: works, with the stated limits.
- **Planned**: not built. Where such a tool exists in the app, it says so; no button pretends to work.

All processing runs on the phone. No feature uploads documents, and none needs a server, a paid SDK or an account. The only exception is the ML Kit document scanner: Google Play services downloads its module once on first use.

## 1. Existing features retained
| Feature | Status |
|---|---|
| View, annotate, PDF ↔ Excel/Word, Word/Excel → PDF, merge/split/organise, scan + OCR (English, Hindi), file management, sharing | Implemented and tested (unchanged; all earlier tests still pass) |

## 2. Bank statement to Excel and analysis
| Item | Status | Notes / limitations |
|---|---|---|
| Single or multiple statements; all pages or page ranges | Implemented and tested | One range applies to every file; pages beyond a file's length are reported as not processed |
| Page type per page (text / scanned-OCR / no text), OCR for scans | Implemented and tested | Shown in the review screen and in the **Processing Report** sheet |
| Preview before conversion; column mapping | Implemented | Columns recognised from headers, with fallback by column type; the mapping used is shown in the Processing Report. Manual column mapping is available in **PDF to Excel**, not yet inside the statement tool |
| Fields: date, value date, description, reference, debit, credit, balance, source page | Implemented and tested | Value date when a second "value date" column exists. References stay text, so leading zeroes are kept |
| Multi-line narrations combined | Implemented and tested | Automatic for wrapped lines; **Combine with next** in review for other cases |
| Original text kept; uncertain values flagged; brackets/minus signs | Implemented and tested | Every row keeps its extracted text. A minus or brackets in a Debit/Credit column is flagged, never silently dropped. Overdraft (Dr) balances are negative |
| Indian number and date formats, user confirmation | Implemented | Chosen before reading. The statement order is confirmed in review when the dates don't show it |
| Manual corrections before export | Implemented and tested | Edit, add, delete, split and combine rows; categories; **Mark reviewed** |
| Reconciliation: opening, total debits/credits, calculated vs statement closing, difference, running balance, duplicates, missing values, failed pages | Implemented and tested | Opening and closing balances start as **derived** values and stay "Incomplete" until the user confirms them. Statement order (oldest/newest first) is detected from the dates or must be confirmed. The workbook states that a matching balance doesn't prove every row is correct |
| Categories (cash, charges, interest, UPI, cheque, customer, supplier, salary, taxes, loan, own transfer, other) | Implemented and tested | Keyword suggestions are labelled **Suggested** until the user changes or confirms them. Customer and supplier categories are never guessed |
| Monthly, category, cash, charges/interest summaries; exceptions report | Implemented and tested | |
| Excel: Transactions, Monthly Summary, Category Summary, Reconciliation, Exceptions, Processing Report; filters, widths, frozen headers, date/number formats | Implemented and tested | The workbook is read back in tests. **PivotTables: not created.** The summaries are ordinary editable tables and are labelled as such |
| CSV and Tally XML exports | Implemented | Unchanged; built from the reviewed rows |

## 3. Review screen
| Item | Status | Notes |
|---|---|---|
| Source page beside the data; side-by-side on wide screens; tabs on phones | Implemented | Side-by-side at ≥ 840 dp width |
| Locate a row on its page | Implemented | The row's band is highlighted on the page image. Rows added or split by hand have no position |
| Source page for every row; uncertain values highlighted | Implemented and tested | |
| Edit, add, delete, split, combine rows | Implemented and tested | |
| Audit trail of corrections | Implemented and tested | Shown in the app and saved in the Processing Report sheet |
| Final confirmation listing warnings and unreviewed exceptions | Implemented | |
| Recovery after Android closes the app | Not provided | For privacy, the review (and any passwords) is held only in memory. It is lost if Android ends the app |

## 4. Invoice / GST extraction
| Item | Status | Notes |
|---|---|---|
| Supplier/customer GSTIN, invoice no., date, taxable value, CGST/SGST/IGST/cess, total, file, page | Implemented and tested | Only labelled values are read; blanks are never filled by calculation |
| Supplier and customer names, invoice type | Implemented and tested | Names are read from the layout and may be incomplete, so they are shown for review |
| Item description and HSN/SAC | Implemented and tested | From tables whose header names an HSN or SAC column |
| Review and correct before export | Implemented | |
| Checks: GSTIN format and check digit; duplicate (same supplier, invoice no. and financial year); taxable + taxes = total; required fields chosen by the user | Implemented and tested | The workbook says that the GSTIN check doesn't confirm registration. Input tax credit eligibility is **not** assessed |
| Excel register | Implemented and tested | Sheets: Invoice register, Line items, Where values came from, About the checks |

## 5. Batch processing
| Item | Status |
|---|---|
| Many PDFs → Excel / Word; compress; password; split by ranges | Implemented (engine paths tested individually) |
| Merge in chosen order | Implemented (Merge tool) |
| Rename pattern ({name}, {n}, {date}, {action}, {part}) | Implemented and tested |
| ZIP export; continue after failures; per-file report (status, pages, warnings, outputs) | Implemented; the report is also saved as a CSV inside the ZIP |

## 6. Client workspace
| Item | Status | Notes |
|---|---|---|
| Create, rename, search, archive clients | Implemented and tested | |
| Subfolders: FY, AY, categories (GST, Income Tax, Bank Statements, Audit, TDS, MCA, Other), free folders | Implemented and tested | |
| Tags, private notes, statuses (Pending review / Reviewed / Completed) | Implemented and tested | |
| Search by client, file name, type, date added, tags, notes, status | Implemented | For text inside PDFs, use Search in Files |
| Recent activity per client | Implemented and tested | |
| Local storage; missing or moved files handled | Implemented and tested | Files are linked, not copied, using Android's persistent read permission. A file that can't be opened shows as unavailable |

## 7. Secure redaction
| Item | Status | Notes |
|---|---|---|
| Search/select PAN, Aadhaar, account numbers, mobile, GSTIN, IFSC, e-mail, cards, custom text; manual boxes for addresses, signatures and images | Implemented and tested | |
| True removal | Implemented and tested | Each redacted page is rebuilt as an image, so its text, fonts and hidden layers are removed. A test confirms that text extraction finds nothing on the redacted page and that the file no longer contains the text. Safety fix in this version: if a page can't be drawn, redaction now stops with an error instead of leaving that page unredacted. The page is no longer searchable |
| Separate copy, warning that automatic detection can miss items, review before sharing | Implemented | |

## 8. Signatures
| Item | Status |
|---|---|
| Visual signature (draw/image, position, resize), labelled as visual | Implemented |
| Certificate-based signature (.pfx/.p12 or a self-made certificate), validation, "changed after signing" detection | Implemented and tested. Tokens on USB/NFC and Aadhaar eSign/DSC services are **not** supported; they need vendor SDKs or a server |

## 9. Compare PDFs
| Item | Status | Notes |
|---|---|---|
| Choose original and revised PDF; compare text; highlight added, removed and changed text | Implemented and tested | Highlighted copies of both PDFs, plus a report listing each change with its page |
| Move between changes | Partly | Through the report's page references and the viewer; there is no next/previous-change button yet |
| Scanned documents | Partly | Make them searchable first with Scan & OCR › Extract text › Create searchable PDF. Automatic OCR inside Compare is **planned** |
| Limits | Stated | Layout changes, OCR errors, images and tables reported as text may hide or add differences; the report says it may not find every change |

## 10. Forms and checklists
| Item | Status |
|---|---|
| Text fields, checkboxes, radio buttons, dropdowns; save a copy | Implemented and tested |
| Reusable checklists (ITR, GST registration, tax audit, company annual filing, client document collection) with add/edit/tick/remove | Implemented and tested (per client, from templates or blank). Client details are never auto-filled into forms |

## 11. Presentation tools
Implemented with previews:
- Page numbers, headers and footers, Bates numbering.
- Text watermarks. Image watermarks are not a separate option; place an image with Edit.
- Bookmarks.
- Cover page, contents page with links, blank pages.
- Page size (A4/Letter/Legal/A3) and orientation.
- Compression with sizes shown, or to a target size.
- Pages to JPG/PNG.
- Printing.

All of these save a new file.

## 12. Search, backup and recovery
| Item | Status | Notes |
|---|---|---|
| Search file names and tags; text inside PDFs, Word, Excel and OCR'd output in My Files with page numbers | Implemented | |
| Local backup and restore | Implemented and tested | A JSON file with clients, folders, document links, tags, notes, statuses, checklists, activity and settings. **Documents are not included**, and the app says so. Restoring on another phone keeps entries, but linked files must be added again |
| Cloud backup | Implemented and tested | Only when the user starts it. The backup is encrypted with the user's password (PBKDF2-HMAC-SHA256 + AES-256-GCM, tamper-evident) and saved through Android's file picker to any installed cloud app (Google Drive, OneDrive, Dropbox…) or the phone. DocDesk makes no internet connection; the cloud app uploads the file. Documents in My Files can be included. Optional daily or weekly automatic backup to the same file: only a derived key is kept, wrapped by a non-exportable Android Keystore key, never the password. Restore needs the password; a forgotten password can't be recovered. A direct Google Drive API connection (sign-in inside DocDesk) is **not** used: it would need the app registered with Google under its final app ID |
| Recovery of unfinished work | Partly | Edit sessions keep undo history while open. Statement and invoice reviews are memory-only (see above) |
| Recycle bin | Implemented and tested | My Files deletions are kept for 30 days |

## 13. Privacy and security
Implemented:
- Processing on the phone; no network permission is used for documents.
- Passwords are held only in memory and never logged.
- Problem reports are sanitised.
- Temporary files are cleaned daily.
- History and temporary files can be cleared.
- Originals are never overwritten.
- PDF permissions are respected.
- The system file picker is used, with no storage permission.
- Optional app lock and screen-capture blocking.

## 14. Interface
Implemented:
- Light and dark themes.
- Large touch targets and accessible labels.
- Progress with cancel.
- History screen.
- Errors with retry advice.
- Main sections: Home (tools by category), Files, Clients, History, Settings.

## 15–17. Priority, testing, deliverables
- The source code and docs are in this repository.
- Build and signing: [BUILD.md](BUILD.md). Test plan and results: [TESTING.md](TESTING.md). Licences: [FEASIBILITY.md](FEASIBILITY.md) §2. Store listing: [PLAY_STORE.md](PLAY_STORE.md).

**Paid components:** none.

**Needs a server or third party:**
- Aadhaar eSign.
- Live GSTIN status lookup.
- Hardware-token DSC signing.
