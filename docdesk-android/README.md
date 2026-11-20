# DocDesk – PDF & document tools for Android

DocDesk converts, edits, combines, splits and organises PDF files on an Android phone or tablet. It is designed for people who handle bank statements, invoices, financial statements, tax documents, agreements and reports, and **processes every file on the device** – nothing is uploaded.

| | |
|---|---|
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
| Word → PDF | ✅ (.docx) | Text, runs, headings, lists, tables, images, page breaks, header/footer, Hindi shaping. `.doc` not supported |
| Excel → PDF | ✅ (.xlsx) | Sheet selection, print area, orientation, paper, margins, fit-to-width/page/custom %, gridlines, sheet names, page numbers, preview. `.xls` not supported |
| Scan & OCR | ✅ | Camera scanner (edges, crop, perspective, rotate), then reorder, rotate, brightness/contrast, colour/grey/B&W; searchable PDF; text export |
| Extract text from PDF (OCR) | ✅ | English and Hindi, editable result, low-confidence words listed, TXT, searchable PDF |
| Annotate & sign | ✅ | Highlight, underline, strikethrough, pen, shapes, lines, arrows, text boxes, sticky notes, images, signatures (draw/import, saved privately), colours, sizes, move/resize, undo/redo, save as new |
| Edit existing PDF text in place | ❌ (planned) | Not reliable with open-source engines; app explains this and offers *Cover + Text box*. See [docs/FEASIBILITY.md](docs/FEASIBILITY.md) |
| Password-protect PDF | ✅ | AES-256, permissions |

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
