# DocDesk – PDF & document tools for Android

DocDesk converts, edits, combines, splits and organises PDF files on an Android phone or tablet. It is designed for people who handle bank statements, invoices, financial statements, tax documents, agreements and reports, and **processes every file on the device** – nothing is uploaded.

| | |
|---|---|
| Version | 1.5.0 (Phase 9) |
| Platform | Android 8.0+ (minSdk 26), phones and tablets, target/compile SDK 36 |
| Language / UI | Kotlin, Jetpack Compose (Material 3), light & dark themes |
| Architecture | Single-activity Compose app, screen state in ViewModels/state holders, pure-Kotlin `:core` engine |
| PDF | PdfBox-Android (Apache 2.0) for reading/writing; Android `PdfRenderer` for display |
| OCR / scanning | Google ML Kit Text Recognition v2 (Latin + Devanagari, bundled, offline); ML Kit Document Scanner |
| Office files | Own dependency-free OOXML reader/writer for .docx and .xlsx (in `:core`) |
| Storage | Storage Access Framework + app-private "My Files", Room (history), DataStore (settings) |
| Background | App-wide job runner on coroutines (progress + cancel), WorkManager for temp-file cleanup |

## What works today

| Tool | Status | Notes |
|---|---|---|
| Home, Files, History, Settings, light/dark | ✅ | Search recent files, progress card with Cancel, recent activity |
| PDF viewer | ✅ | Pinch zoom + zoom buttons, page jump, thumbnails, text search with highlights, password PDFs |
| Merge PDFs | ✅ | Drag-and-drop order, page ranges per file, page-order preview |
| Split PDF | ✅ | Every page, custom ranges, split after selected pages, extract selected |
| Organise pages | ✅ | Drag to reorder, rotate 90/180/270, delete, duplicate, extract, insert from another PDF, undo/redo, save as new |
| PDF → Excel | ✅ | Text PDFs and OCR; auto or manual table area; editable review grid; Indian number & date formats; raw text kept; flagged cells; financial checks; 3 sheet layouts |
| PDF → Word | ✅ | Editable-text and layout-focused modes; headings, bold/italic, lists, tables, images, page breaks, repeated header/footer; OCR for scans |
| Word → PDF | ✅ (.docx, .doc) | .docx: text, runs, headings, lists, tables, images, page breaks, header/footer, Hindi shaping. .doc (Word 97–2003): text, paragraphs, tables, hard page breaks (no formatting) |
| Excel → PDF | ✅ (.xlsx, .xls) | Sheet selection, print area, orientation, paper, margins, fit-to-width/page/custom %, gridlines, sheet names, page numbers, preview. .xls (incl. Tally exports): values, number formats, bold/italic, widths, merges (no fills/borders) |
| GST invoice register | ✅ | Invoice PDFs (text or scanned) → Excel: invoice no., date, supplier/buyer GSTIN, taxable, CGST, SGST/UTGST, IGST, cess, total; GSTIN checksum, tax arithmetic, CGST=SGST, IGST vs same-state checks; duplicates flagged; evidence sheet |
| Statement insights & Tally | ✅ | Month-wise, party-wise (from UPI/NEFT/IMPS narrations) and category summaries via keyword → ledger rules; Tally XML (Payment/Receipt/Contra vouchers) for import |
| Home: search, favourites, categories, shortcuts | ✅ | One search for tools and files; ★ favourites; tools grouped; long-press app icon for Scan / Create PDF / Bank statements |
| Search in files | ✅ | Text search inside all PDFs, Word, Excel and text files in My Files |
| Scan & OCR | ✅ | Camera scanner (edges, crop, perspective, rotate), then reorder, rotate, brightness/contrast, colour/grey/B&W; searchable PDF; text export |
| Extract text from PDF (OCR) | ✅ | English and Hindi, editable result, low-confidence words listed, TXT, searchable PDF |
| Annotate & sign | ✅ | Highlight/underline/strikethrough that **snap to words**, pen, shapes, lines, arrows, text boxes, sticky notes, **stamps** (PAID, APPROVED, RECEIVED… with date), images, signatures, colours, sizes, move/resize, undo/redo, **pinch zoom**; markups can be saved as **editable Acrobat annotations** |
| Edit text | ✅ (line replacement) | Tap a line → change it; old line covered, new text placed at same position/size (standard font). Full reflowing text editing needs a commercial engine – see [docs/FEASIBILITY.md](docs/FEASIBILITY.md) |
| Secure redaction | ✅ | Redacted pages are rebuilt as images so the hidden content is really removed |
| Create PDF | ✅ | Word, Excel, photos and PDFs → one combined PDF or separate PDFs; "Share › DocDesk" and "Open with" from other apps |
| Fill forms | ✅ | Text fields, checkboxes, radio buttons, lists; optional flatten |
| Watermark, page numbers, header/footer | ✅ | Diagonal/horizontal watermark with opacity; `{n}`, `{total}`, `{date}`, `{file}`, Bates `{n:4}` |
| Compress PDF | ✅ | Light / medium / strong image recompression; reports size saved |
| Password-protect PDF | ✅ | AES-256, permissions |
| Digital signatures | ✅ | Sign with a .pfx/.p12 certificate or a personal certificate created in the app (PKCS#7 detached, SHA-256, visible box optional, incremental so earlier signatures stay valid); check signatures in received PDFs (intact / changed after signing / certificate details) |
| Compare PDFs | ✅ | Line and word-level differences; highlighted copies of both versions (editable annotations, comments with original wording) and a text report |
| PDF → JPG / PNG | ✅ | Pages at 96/150/300 dpi, or extract embedded pictures; optional ZIP |
| Bank statements → Excel/CSV | ✅ | Several statements (any month/bank layout the table engine reads) → one standard sheet: Date, Narration, Reference, Debit, Credit, Balance, Source; sorted by date; per-file totals and balance checks; overlapping transactions flagged; CSV for Tally/Zoho/reconciliation |
| Find & redact | ✅ | Detects PAN, Aadhaar (Verhoeff checksum), GSTIN (checksum), IFSC, mobile, email, card (Luhn), account numbers and custom words (OCR for scans); review, then secure redaction |
| Batch process | ✅ | Many PDFs → Excel, Word, compressed or password-protected, optional ZIP |
| App lock & privacy screen | ✅ | Fingerprint/face/screen-lock to open (re-locks after 1 min in background); option to block screenshots and hide content in recent apps |
| Read aloud | ✅ | Viewer reads the current page with the phone's text-to-speech (English/Hindi) |
| Viewer: contents & copy | ✅ | Bookmarks panel; long-press and drag to select text, then Copy |

Every conversion shows a report: document type (text/scanned/mixed), pages selected and processed, failed pages with reasons, warnings, checks and a preview **before** you save or share.

## Quick start

```bash
cd docdesk-android
./gradlew :core:test            # engine unit + real-document tests (no Android SDK needed)
./gradlew :app:assembleDebug    # needs the Android SDK; APK in app/build/outputs/apk/debug/
```

Full setup, signing and release steps: [docs/BUILD.md](docs/BUILD.md).

## Documentation

- [docs/FEASIBILITY.md](docs/FEASIBILITY.md) – feature & feasibility assessment, libraries and licences, offline vs. server/paid features, roadmap
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – architecture, project structure, data flow, how to extend
- [docs/BUILD.md](docs/BUILD.md) – setup, debug APK, signed release / App Bundle, CI
- [docs/TESTING.md](docs/TESTING.md) – test plan, results, known limitations, sample files
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) – how to use each tool
