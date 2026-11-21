# Architecture and maintenance guide

## Overview

```
┌──────────────────────────── app (Android) ─────────────────────────────┐
│ UI (Jetpack Compose)                                                   │
│   ui/home  ui/files  ui/history  ui/settings      (bottom navigation)  │
│   ui/viewer ui/merge ui/split ui/organize ui/convert ui/scan ui/edit   │
│   ui/result  ui/components (shared widgets, PdfInputHolder)            │
│        │ state: ViewModels / remembered holders                        │
│        ▼                                                               │
│ Operations ──► JobRunner (one job, progress, cooperative cancel)       │
│        │                                                               │
│ Engines (Android-specific)                                             │
│   pdf/   PdfDocs (open, password, permissions, inspect)                │
│          PageRenderer (PdfRenderer + LRU cache)                        │
│          PdfTextExtractor (PdfBox glyphs → words)   PdfOps (pages)     │
│   ocr/   OcrEngine (ML Kit Latin/Devanagari)                           │
│   convert/ PageTextSource (text layer or OCR) PdfToExcel/WordEngine    │
│            DocToPdfRenderer  SheetToPdfRenderer  Report types          │
│   edit/  Annotations model, AnnotationWriter (PdfBox)                  │
│   scan/  ImageLoader, ImageProcessor, ScanPdfBuilder                   │
│ Data                                                                   │
│   data/FileRepository (My Files, cache, SAF, FileProvider)             │
│   data/db (Room history)  data/SettingsRepository (DataStore)          │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ depends on
┌───────────────────────────────▼───────── core (pure Kotlin/JVM) ───────┐
│ TextModel / LineGrouper    TableExtractor   FinancialChecks            │
│ AmountParser (Indian numbers)  DateParser   PageRanges  PageTransform  │
│ ExcelExport + XlsxWriter   XlsxReader + NumberFormatter  SheetPaginator│
│ DocModel  DocxWriter  DocxReader  PdfToDocBuilder  OoxmlPackage  Xml   │
└────────────────────────────────────────────────────────────────────────┘
```

**Why a separate `:core` module?** All document logic that does not need Android lives in plain Kotlin. It is fast to unit-test on any machine (`./gradlew :core:test`, no emulator), cannot accidentally touch the UI thread, and could be reused (desktop, server) later.

**MVVM-style state.** Each tool screen keeps its state in a `ViewModel` (PDF→Excel, PDF→Word, Office→PDF, Scan, OCR) or, for simple screens, in remembered state holders. `PdfInputHolder` encapsulates the common "choose a PDF → password prompt → inspect → thumbnails" flow; the password lives only in that object (memory) and is cleared when the screen closes.

**Background work.** `JobRunner` runs one document operation at a time on `Dispatchers.IO` in an application-wide scope, so it continues while the user navigates, and the Home screen shows its progress with a Cancel button. Cancellation is cooperative: page-by-page conversions call `progress.allowPartialResults()` and return the pages finished so far, marked **Cancelled – partial result**. WorkManager runs a daily `CleanupWorker`. Conversions are *not* WorkManager jobs because they are interactive (preview before saving) and often need a password that must not be persisted into WorkManager's database.

**Results.** Every operation returns an `OperationResult` = `OperationReport` (outcome, document kind, pages selected/processed, failed pages, warnings, checks, notes) + output files (in the cache) + a `Preview`. `Operations.run` stores it in `ResultStore` (memory), records a history row (names and counts only) and opens the Result screen, where the user saves to My Files, saves to device (SAF) or shares.

## Data flow examples

**PDF → Excel**
1. `PdfInputHolder` opens the PDF with PdfBox (`PdfDocs.open`), checks permissions, classifies text/scanned/mixed.
2. `PdfToExcelEngine.extract` → for each page `PageTextSource.get` returns positioned words from the text layer (`PdfTextExtractor`) or from OCR (`OcrEngine`, rendering via `PageRenderer`).
3. `TableExtractor.extract` (core) groups words into lines, cuts lines into segments at wide gaps, finds column corridors with a coverage profile, assigns cells, detects header row, column types (date/amount/text), joins wrapped description lines, and flags uncertain cells. It **never edits text**.
4. The Review screen lets the user edit cells (marked *Edited*), change column types and the header row; `FinancialChecks` totals debit/credit and verifies running balances and printed opening/closing balances.
5. `ExcelExport.build` writes numbers/dates with formats that look like the PDF (brackets, Dr/Cr, Indian grouping), plus *Source text* and *Review* sheets; `XlsxWriter` creates the file.

**Annotations** are stored normalised (0..1) to the page *as displayed*; `PageTransform.displayToPdf` maps them into PDF user space for any `/Rotate` value, so rotated pages are annotated correctly.

## Project structure

```
docdesk-android/
├── settings.gradle.kts, build.gradle.kts, gradle.properties
├── gradle/libs.versions.toml          # all dependency versions
├── core/                              # pure Kotlin engine + tests
│   └── src/{main,test}/kotlin/com/docdesk/core/
├── app/
│   ├── build.gradle.kts, proguard-rules.pro
│   ├── schemas/                       # Room schema history (commit changes!)
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── res/ (theme, icons, file_paths, backup exclusions)
│       └── java/com/docdesk/app/
│           ├── DocDeskApp.kt, MainActivity.kt, BuildConfigInfo.kt
│           ├── data/  (FileRepository, Settings, History, db/)
│           ├── jobs/  (JobRunner, CleanupWorker)
│           ├── pdf/ ocr/ convert/ edit/ scan/
│           └── ui/    (AppNav, theme, components, one package per screen)
├── samples/make_samples.py + samples/out/  # test documents
└── docs/
```

## Conventions

- **Never modify the user's original.** All tools write a new file to the cache; the user decides where to save it. `saveAtomically` writes `*.part` and renames.
- **Never invent data.** Extraction keeps the exact text (`TableCell.raw`); interpretation (numbers/dates) happens only at export and falls back to text when uncertain. Uncertain cells get a `CellFlag`.
- **Respect PDF permissions.** Call `PdfDocs.require(doc, action)` before extracting, assembling or modifying.
- **No sensitive logging.** Do not log document text, file contents or passwords. History stores names and counts only.
- **Accessibility.** Every icon-only button has a `contentDescription`; selectable items expose state; touch targets ≥ 48 dp; text uses `sp` so system font size applies.
- **User-facing errors** go through `Throwable.userMessage()`; never show stack traces.

## How to extend

**Add a tool**
1. Put any Android-independent logic in `:core` with unit tests.
2. Create `ui/<tool>/<Tool>Screen.kt`; reuse `ToolScaffold`, `PdfInputHolder`, `RadioOptions`, `JobProgressCard`.
3. Run the work with `Operations.run(title, onError, nav.resultCallback()) { progress -> … OperationResult(...) }`.
4. Add a route in `ui/AppNav.kt` (`Routes` + `tool(...)`) and a card in `HomeScreen.tools`.

**Swap or add an OCR engine** – implement the same signature as `OcrEngine.recognize` (returns `PageText` in page units with per-word confidence) and add a choice to `OcrLanguage`/Settings. Everything downstream (tables, Word, searchable PDF) works unchanged.

**Integrate a commercial PDF SDK for in-place editing** – keep `EditPdfScreen` as the entry point, add a mode that opens the SDK's editor activity on a private copy, and return its output through `OperationResult` so reports/history stay consistent.

**Change the Room schema** – bump `AppDatabase.version`, add a `Migration`, build once so `app/schemas/<version>.json` is generated, and commit it.

**Update dependencies** – edit `gradle/libs.versions.toml`. After updating PdfBox-Android, re-run the release build (R8 rules in `proguard-rules.pro`). After updating ML Kit, re-check the confidence API (`Text.Element.getConfidence`).
