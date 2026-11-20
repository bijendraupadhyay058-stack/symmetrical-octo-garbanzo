# Testing plan, results and known limitations

## 1. What has been verified so far

The app was built in a cloud container **without an Android device or emulator** (no hardware virtualisation available). Verification therefore covers everything that can run on a JVM plus static checks. **On-device testing of the UI flows is still required** before release (section 3).

| Check | Result |
|---|---|
| `:core` unit tests (34, incl. text selection, label templates and PDF comparison) – page ranges, Indian amounts, dates, Excel number formats, page rotation maths, table extraction, wrapped rows, OCR flags, financial checks, XLSX/DOCX round trips | ✅ all pass |
| `:core` real-document tests (5) on `samples/out` using desktop Apache PDFBox (same API as PdfBox-Android) | ✅ all pass |
| `:app:compileDebugKotlin`, `:app:assembleDebug` | ✅ builds |
| `:app:assembleRelease` with R8 shrinking | ✅ builds (unsigned without keystore) |
| Android Lint (`:app:lintDebug`) | ✅ 0 errors; remaining warnings are newer-version notices and style suggestions |
| API checks against downloaded artefacts | ✅ `Text.Element.getConfidence()` (ML Kit 16.0.1), PdfBox `LosslessFactory/JPEGFactory(Bitmap)`, `setRenderingMode`, `setHorizontalScaling`, `PDAnnotationText` exist |

### Real-document results (from `SamplesIT`)

| Sample | Result |
|---|---|
| `bank_statement_text.pdf` (3 pages, 55 transactions, wrapped narrations, Indian numbers) | 3 tables detected, combined into **55/55 rows**; columns typed Date/Text/Text/Amount/Amount/Amount; wrapped narrations joined; leading-zero references kept as text; **54/54 running balances reconcile**; opening + credits − debits = printed closing balance; debit total matches the printed total |
| `invoice.pdf` | Header `S.No/Description/HSN/Qty/Rate/Amount`, 4 items + sub-total/CGST/SGST/Total rows; total `31,249.35` kept exactly; label cells in the amount column flagged for review |
| `report_mixed_text_and_scan.pdf` page 1 → Word | Title heading, "1. Summary" as a heading (not a list), three-line paragraph joined into one, three bullets |
| `workbook_multi_sheet.xlsx` | Indian lakh format `4,32,438.24`; brackets `(1,830,000.00)`; `23.5%`; hidden sheet detected; formula without saved result **warned**; print area respected (40 rows) |
| `word_tables_images.docx` | Title + headings, 3 bullets and 1./2./3. numbering from list *styles*, bold run inside a paragraph, 3×4 table, image, page break, Hindi paragraph intact, header and footer |

Digital signatures were additionally verified on a JVM by running the same signing code against desktop Apache PDFBox 2.0.32 and Bouncy Castle 1.72: personal certificate created; signature valid and covering the whole file; a second signature keeps the first intact; a modified file is reported invalid; a wrong certificate password gives a clear message.

Bugs found by these tests and fixed: list styles in Word files were ignored; empty formula values were not flagged; PDF→Word split paragraphs at normal line spacing and treated numbered headings as list items.

## 2. Sample files

Generate with `python3 samples/make_samples.py` (needs `reportlab pypdf pillow openpyxl python-docx`). Pre-generated copies are in `samples/out/`. All data is fictitious.

| File | Use it to test |
|---|---|
| `bank_statement_text.pdf` | PDF→Excel (financial checks, wrapped rows, multi-page tables, Indian numbers), PDF→Word tables, viewer search ("SALARY") |
| `bank_statement_scanned.pdf` | OCR path of PDF→Excel/Word, low-confidence flags, searchable PDF, *Never use OCR* warning |
| `invoice.pdf` | PDF→Excel on invoices, merge/split with a 1-page file |
| `report_mixed_text_and_scan.pdf` | Mixed-document detection, PDF→Word with images, OCR of page 2 |
| `large_100_pages.pdf` | Performance: viewer scrolling, thumbnails, split every page, merge large files, cancel mid-way |
| `protected_password_test1234.pdf` | Password prompt (password `test1234`), wrong password message, protection kept after editing |
| `restricted_no_copy.pdf` | Opens without password but conversions/editing are **refused** (permissions respected) |
| `damaged_truncated.pdf`, `not_a_pdf.pdf` | Error messages for damaged/unsupported files |
| `workbook_multi_sheet.xlsx` | Excel→PDF: sheet selection, hidden sheet, print area, merged title, Indian format, wide sheet (scaling/landscape), formula warning |
| `word_tables_images.docx` | Word→PDF: headings, lists, table, image, page break, header/footer, Hindi shaping |

Also test with your own (non-confidential or anonymised) documents: real bank statements from 2–3 banks, a GST invoice, a scanned Hindi document, a password-protected statement, an `.xls` and a `.doc` (should show the "save as .xlsx/.docx" message).

## 3. On-device test plan

Run on at least: one Android 8/9 phone (or emulator), one Android 14–16 phone, one small screen (≤ 5.5"), one tablet, with system font size at largest, with TalkBack, and in dark mode.

| Area | Steps | Expected |
|---|---|---|
| Home & navigation | Open each tool card; switch tabs; rotate the phone | No crashes; state kept on rotation in conversion screens |
| Viewer | Open 100-page PDF; pinch zoom; zoom buttons; thumbnails; go to page; search | Smooth scrolling; correct page counter; highlights on matches; scanned PDF search shows the OCR hint |
| Password | Open `protected_password_test1234.pdf` with wrong then right password | Clear error, then opens; password not remembered after leaving |
| Permissions | PDF→Excel on `restricted_no_copy.pdf` | Refused with explanation |
| Merge | 3 files incl. protected; reorder by drag and by arrows; ranges `1-2`; preview | Output order/pages exactly as previewed; note that output is unprotected |
| Split | Every page; ranges `1-5, 6-10`; split after selected; extract selected | Correct number of files and pages; names show ranges |
| Organise | Rotate, delete, duplicate, insert from another PDF, drag, undo/redo, extract, save | Saved PDF matches the grid |
| PDF→Excel (text) | Bank statement; Indian/DMY; one sheet / per page / per table | 55 rows; checks reconcile; yellow flagged cells; *Source text* and *Review* sheets; opens in Excel/Sheets/WPS |
| PDF→Excel (scan) | Scanned statement with OCR | Tables found; low-confidence cells flagged; nothing invented |
| PDF→Excel area | Manual table area on page 1 | Only rows inside area exported |
| PDF→Word | Both modes, with/without images, scanned with Hindi | Opens in Word/Docs; headings/lists/tables present; failed pages listed |
| Word→PDF / Excel→PDF | Sample files; landscape, fit to width, custom % | Preview correct; warnings for formula/fonts |
| Scan | Camera scan 3 pages; reorder; rotate; B&W; brightness; searchable PDF | PDF pages in chosen order; search finds English words |
| Edit | Every tool; rotate-page PDF; Hindi text box; signature draw + reuse; move/resize; undo/redo | Positions in saved PDF match the screen (also on rotated pages); notes visible as comments in other readers |
| Files | Sort, search, rename, delete, share, open with, save to device, add password | All actions work; protected copy needs password |
| History & settings | Turn history off, run an operation, clear history, delete temp files, switch theme | No entry recorded when off; temp size drops |
| Interruptions | Cancel during PDF→Excel on 100 pages; press Home during conversion; low storage | Partial result marked *Cancelled*; no half-written files; storage error message |
| Accessibility | TalkBack through Home, a conversion, Result | All buttons announced meaningfully; selection states read out |
| Digital signature (v1.2) | Create personal certificate; sign invoice with visible box; open the result in Adobe Acrobat Reader; sign again; edit the signed file in another app and re-check | Acrobat shows valid integrity (identity unknown for personal cert); both signatures valid after second signing; edited file reported as changed/invalid |
| Compare (v1.2) | Agreement v1 vs v2 with a changed amount, a removed clause and a new clause | Amount word highlighted orange with comment, clause green, removed clause struck red in original; report lists all three |
| PDF→JPG/PNG (v1.2) | 100-page PDF at 150 dpi as ZIP; extract images from mixed report | ZIP with 100 images; extracted chart image |
| Viewer (v1.2) | Bookmarks on a PDF with outline; long-press select across lines and copy into Notes | Jumps to the right page; copied text matches |
| Editor (v1.1) | Pinch zoom then draw; highlight across 2 lines; Edit text on invoice total; stamp PAID; redact account number; save with *editable* on | Highlights hug the words; edited line matches position; open output in Acrobat Reader: highlights/shapes selectable & deletable; redacted page has no selectable text under the box |
| Create PDF (v1.1) | Word + Excel + 3 photos, combined and separate; Share 2 files from WhatsApp to DocDesk | One PDF in the shown order / separate PDFs; shared files appear in Create PDF |
| Fill form (v1.1) | A government/bank PDF form with text fields and checkboxes; flatten on/off | Values visible in other readers; flattened form not editable |
| Watermark / numbers / compress (v1.1) | `CONFIDENTIAL` 20%; `INV-{n:4}` bottom right; compress the scanned statement | Correct on rotated pages too; numbering correct; size reduced and report shows saving |

## 4. Known limitations

- **Table extraction** relies on aligned columns. Free-form layouts, tables without whitespace corridors, rotated text and multi-line header rows may need the manual area, column-type changes or cell edits. Merged header cells are exported as separate cells.
- **Wrapped text** is joined only when the continuation line is below the main line and contains text in text columns only.
- **Scanned PDFs**: OCR quality depends on resolution, skew, contrast and fonts. Handwriting is not supported. Rupee symbols may be read as "₹", "Rs" or "2" – values with letters are kept as text and flagged.
- **PDF→Word** approximates layout: multi-column pages, text boxes, vector graphics, form fields and exact fonts are not reproduced; images on rotated pages are skipped (reported).
- **Word→PDF / Excel→PDF** use the phone's fonts and layout engine – line/page breaks can differ from Office. Not drawn: charts, SmartArt, text boxes/shapes, floating image positions, footnotes, conditional formatting, cell images. Formulas show their last saved value only. `.doc` and `.xls` are not supported.
- **Searchable PDFs**: Hindi text cannot be embedded in the invisible text layer (PdfBox 2 has no complex-script shaping); it is still available via *Extract text*.
- **Edit text** replaces whole lines with a standard font and does not reflow paragraphs; the original text remains underneath unless redacted. *Cover (white-out)* is visual only – use **Redact**.
- **Redaction** converts affected pages to images (no searchable text on those pages).
- **Forms**: digital certificate signatures and JavaScript calculations are not supported; Hindi input depends on the form font.
- **Compress** only recompresses images; text-only PDFs rarely get smaller.
- **Viewer** renders a decrypted temporary copy for password-protected PDFs (private cache, deleted on close).
- **Process death** during a conversion loses that conversion (results are in memory until saved); completed saves are never half-written.
- **Very large files** (hundreds of MB / thousands of pages) can exhaust memory on low-end phones; use page ranges.
- History and the result list are per-device; there is no sync or cloud backup (by design).
