# DocDesk user guide

Every tool follows the same steps: **choose a file → choose options → convert → preview the result and report → save or share.** Your original file is never changed.

## Home
- **Select a file** opens your phone's file picker (phone storage, SD card, Google Drive, etc.). DocDesk suggests what to do with the file.
- Tap a **tool** card to start a specific task. **Search recent files** finds files saved in My Files.
- While an operation runs, a progress card shows the current step and a **Cancel** button.

## Viewing a PDF
Pinch to zoom or use the − / + buttons. Tap the grid icon for page thumbnails, the menu for *Go to page*, *Edit*, *Organise* or *Convert*, and the magnifier to search text. Scanned PDFs have no searchable text – use *Scan & OCR* to make a searchable copy.

## Merge, split and organise
- **Merge**: add PDFs, drag the handle (or use the arrows) to set the order, optionally enter pages per file (e.g. `1-3, 5`), check *Preview final page order*, then *Merge*.
- **Split**: every page, custom ranges (`1-5, 6-10`), split after selected pages, or extract selected pages.
- **Organise pages**: tap pages to select; long-press and drag to move; use the bottom bar to rotate, move, duplicate, delete, extract, insert pages from another PDF, undo/redo and save as a new PDF.

## PDF to Excel
1. Choose the PDF and the pages.
2. Confirm the **number format** (Indian 1,23,456.78 is the default) and **date order** (Day/Month/Year default).
3. For scanned PDFs keep OCR on and choose the language.
4. If the wrong area is picked up, switch on *Select table area manually* and drag across the table.
5. **Review**: yellow cells need checking (low OCR confidence, joined lines, or a value that could not be read as a number/date). Tap a cell to correct it. Tap the column label to change its type (Text/Date/Amount).
6. Choose the sheet layout and export. The workbook includes a **Source text** sheet with exactly what was read and a **Review** sheet listing the report, checks and flagged cells.

Financial checks (debit/credit totals, running balance, opening/closing balance) help you find mistakes but do not guarantee the extraction is complete – always compare important figures with the PDF.

## PDF to Word
Choose *Editable text* (best for editing) or *Layout-focused* (closer look, harder to edit). Scanned pages are read with OCR in the language you choose. Pages that could not be converted are listed in the report.

## Word to PDF / Excel to PDF
Choose a `.docx` or `.xlsx` file. For Excel, select the sheets and page setup (orientation, paper, margins, scaling, gridlines, sheet names, page numbers). Check the preview for page breaks before saving. Older `.doc`/`.xls` files must first be saved as `.docx`/`.xlsx` in Word, Excel, Google Docs/Sheets or WPS.

## Scan & OCR
*Scan with camera* finds the page edges automatically; you can crop, straighten and rotate each page. Then reorder pages and adjust brightness, contrast and colour (Colour, Grayscale, Black & white). *Create PDF* can add an invisible text layer so you can search and copy (English). *Extract text only* creates a `.txt` file (English and Hindi). For an existing PDF use *Extract text (OCR)* from the Home menu.

OCR works best with sharp, well-lit, straight pages. Handwriting, faint print and complex layouts reduce accuracy.

## Create PDF (Word, Excel, photos)
Tap **Create PDF**, choose one or more Word (.docx), Excel (.xlsx), photo or PDF files, arrange the order and choose *Combine into one PDF* or *A separate PDF for each file*. You can also send files straight to DocDesk from WhatsApp, Gmail or Files: **Share › DocDesk**. For detailed Excel page setup use **Excel to PDF**; for Word page options use **Word to PDF**.

## Fill forms, watermark, page numbers, compress
- **Fill Form**: type into the form's fields, tick boxes, choose options; optionally *flatten* so answers can't be changed.
- **Watermark**: e.g. CONFIDENTIAL or DRAFT across pages, with size and transparency.
- **Page Numbers**: formats like `Page {n} of {total}`, Bates numbers `INV-{n:4}` → INV-0001, plus header/footer text with `{date}` or `{file}`.
- **Compress PDF**: makes scanned and photo-heavy PDFs smaller; the report shows the size before and after.

## Digital signature
A digital signature proves who signed and that the PDF hasn't changed since. Open **Digital Signature**, choose a PDF, then:
1. **Import .pfx/.p12** (your certificate file) or **Create personal** certificate (name, password – remember it!).
2. Enter a reason and location; keep *Show a signature box* on to print "Digitally signed by…" on the first or last page.
3. Tap **Sign digitally** and enter the certificate password.
Opening any signed PDF here shows its signatures: ✓ unchanged, ✓ intact but updated later, or ✗ invalid (altered). Personal certificates show as "identity unknown" in Adobe Acrobat until the recipient trusts them; for legally recognised signatures use a DSC from a licensed Certifying Authority.

## Compare PDFs
Choose the original and the new version. DocDesk produces the new version with green highlights for new text and orange for changed words (tap the comment to see the old wording), the original with removed text struck through in red, and a text report of all changes. Only text is compared.

## PDF to JPG / PNG
Save pages as pictures (96, 150 or 300 dpi) or extract the photos inside a PDF. Many images can be packed into one ZIP.

## Viewer extras
Tap the list icon for the document's **contents** (bookmarks). **Long-press** on text and drag to select it, then tap **Copy**.

## Edit PDF (annotate and sign)
Pick a tool, a colour and thickness, then drag or tap on the page. Pinch with two fingers to zoom in for precise work. Highlight, underline and strikethrough snap to the words you drag across. Use *Select / move* to move, resize (round handle) or delete items. Undo/redo are at the top. *Save as new PDF* keeps the original unchanged. With *Keep markups editable in Acrobat* on, highlights, shapes and lines stay editable in other PDF apps.

- **Edit text**: tap a line of text, type the correction, choose size/bold. The old line is covered and the new text is placed in the same spot (standard font; the original still exists underneath unless you also redact).
- **Stamp**: PAID, APPROVED, RECEIVED, VERIFIED… or your own text, with today's date.
- **Redact (secure)**: drag black boxes over confidential details. When you save, those pages are rebuilt as images so the information is really gone (those pages are no longer searchable).
- **Cover (white-out)** only hides content visually – use Redact for sensitive information.

## My Files, History and Settings
- **My Files**: files you saved in DocDesk (stored privately in the app). Sort, search, open, share, rename, *Save to device*, *Add password* (AES-256) and delete.
- **History**: what you did and whether it succeeded – only file names, dates and results are stored. Clear it any time or turn it off in Settings.
- **Settings**: theme, default OCR language, default number/date format, privacy (history, delete temporary files).

## Privacy
All processing happens on your phone. DocDesk does not upload documents, has no analytics and never stores passwords. Files are excluded from cloud backup. Unsaved results and temporary files are deleted automatically within a day. The camera scanner is provided by Google Play services, which may download its scanning module the first time.
