# Feature and feasibility assessment

This document records which requested features can be built reliably on a phone, offline, with open-source or free components – and which need a commercial SDK, a server, or later work. Each library was checked for Android compatibility, licence, commercial-use terms and memory needs before it was chosen.

## 1. Summary

| Requirement | Feasible offline? | How DocDesk does it | Confidence |
|---|---|---|---|
| View PDFs (zoom, thumbnails, search) | Yes | Android `PdfRenderer` (PDFium) + PdfBox text layer for search | High |
| Merge / split / rotate / reorder / delete / extract / duplicate / insert pages | Yes | PdfBox-Android page tree operations, always into a new file | High |
| Password-protected PDFs (open with password) | Yes | PdfBox decrypts with the user's password; author permissions enforced | High |
| Add password (AES-256) | Yes | PdfBox `StandardProtectionPolicy`, 256-bit | High |
| PDF → Excel for text PDFs | Yes | Own table reconstruction from glyph positions (`:core`) | Good for ruled/aligned tables (statements, invoices); lower for free-form layouts |
| PDF → Excel for scanned PDFs | Yes | ML Kit OCR word boxes → same table engine; low-confidence cells flagged | Medium – depends on scan quality |
| PDF → Word | Yes | Positioned text → paragraphs/headings/lists/tables/images → own DOCX writer | Good for text documents; layout of complex designs is approximate |
| Word (.docx) → PDF | Yes | Own DOCX reader → Android text layout (StaticLayout) → `PdfDocument` | Good for business documents; not pixel-identical to Word |
| Excel (.xlsx) → PDF | Yes | Own XLSX reader + number-format engine → paginated drawing | Good for values/formatting; charts and conditional formatting not drawn |
| Legacy .doc / .xls | Yes (own readers) | OLE2 compound-file reader + BIFF8 (.xls) and Word 97 piece-table (.doc) readers in `:core` | .xls: high for values/formats; .doc: text/tables only |
| OCR English + Hindi | Yes | ML Kit Text Recognition v2 Latin and **Devanagari** models, bundled in APK | Verified API (element confidence available) |
| Camera scan with edge detection, crop, perspective | Yes* | ML Kit Document Scanner (*runs in Google Play services; module downloaded on first use) | High where Play services exist |
| Brightness/contrast, colour/grey/B&W, reorder, rotate | Yes | In-app processing after scanning | High |
| Searchable PDF from scans | Yes (Latin) | Invisible text layer with PdfBox; Hindi words can't be embedded (no shaping/font in PdfBox 2) | Medium |
| Annotations, drawing, shapes, text, images, signatures | Yes | Drawn into page content with PdfBox; sticky notes as real PDF comments | High |
| Edit existing PDF text | Partly | *Edit text* tool: replaces a tapped line (cover + new text at the same position and size, standard font). No reflow, original font not reused | Good for corrections of names/dates/amounts |
| Secure redaction | Yes | Pages with redactions are re-rendered to images; original content removed | High (page loses searchable text) |
| Editable annotations (Acrobat-compatible) | Yes | PdfBox `PDAnnotationTextMarkup`, `SquareCircle`, `Line` with generated appearances | High |
| Fill AcroForm forms | Yes | PdfBox `PDAcroForm` (text, checkbox, radio, choice), optional flatten | High for Latin text; Hindi depends on the form's font |
| Watermark, page numbers, header/footer, compress | Yes | PdfBox content streams; JPEG recompression of large images | High |

## 2. Libraries, licences and restrictions

| Library | Version | Licence | Commercial use | Why / notes |
|---|---|---|---|---|
| PdfBox-Android (`com.tom-roush:pdfbox-android`) | 2.0.27.0 | Apache 2.0 | Yes | Android port of Apache PDFBox 2.0: parse, decrypt, modify, encrypt, write PDFs, text positions. No JBIG2/JPX decoding (we render scans with PdfRenderer instead). Uses a scratch file for large documents (`MemoryUsageSetting.setupMixed(48 MB)`). Pulls in Bouncy Castle; lint flags an unused trust-all TrustManager inside it – DocDesk makes no network calls. |
| Android `PdfRenderer` | platform | – | Yes | Fast, accurate rendering (PDFium) incl. JBIG2/JPX scans. Cannot open encrypted files on API < 35 → DocDesk renders a decrypted *private temporary* copy after the user enters the password, deleted on close. |
| ML Kit Text Recognition v2 – Latin & Devanagari | 16.0.1 | Google ML Kit Terms of Service (free) | Yes, under the ML Kit terms | Bundled models (~+4 MB assets, ~11 MB native per ABI). On-device; images not sent to Google. Provides per-element confidence (verified in the AAR: `Text.Element.getConfidence()`). |
| ML Kit Document Scanner (`play-services-mlkit-document-scanner`) | 16.0.0 | Google ML Kit / Play services terms | Yes | Edge detection, crop, perspective, rotate, filters, multi-page. Needs Google Play services; downloads its UI module on first use (needs internet once). Without it, DocDesk offers *Import images*. |
| AndroidX: Compose BOM, Activity, Lifecycle, Navigation, Room, WorkManager, DataStore, Core | see `gradle/libs.versions.toml` | Apache 2.0 | Yes | Standard Jetpack stack. |
| AndroidX Biometric | 1.1.0 | Apache 2.0 | Yes | App lock (fingerprint/face/device credential). Requires an AppCompat theme (used since 1.3.0). |
| Reorderable (`sh.calvin.reorderable`) | 2.4.3 | Apache 2.0 | Yes | Drag-and-drop for LazyColumn/LazyVerticalGrid (merge list, organise grid). Up/down buttons provided too, for accessibility. |
| kotlinx.coroutines (+ play-services adapter) | 1.10.2 | Apache 2.0 | Yes | Background work, `Task.await()` for ML Kit. |
| Bouncy Castle (bcprov/bcpkix, via PdfBox-Android) | 1.72 | MIT-style (Bouncy Castle licence) | Yes | CMS signature creation/verification and certificate generation for digital signatures. Kept in release builds by R8 rule (+≈2 MB). |
| Apache PDFBox (desktop) | 2.0.32 | Apache 2.0 | Yes | **Test-only** (`:core` integration tests on sample PDFs). Not shipped. |

### Libraries considered and not used

| Library | Reason |
|---|---|
| Apache POI | Very large on Android (method count, `java.awt`/StAX gaps, memory). DocDesk only needs a subset of OOXML, so it ships a small, tested reader/writer instead. POI's HSSF/HWPF could be added later for `.xls`/`.doc` **reading** (Apache 2.0). |
| Tesseract (tess-two / Tesseract4Android) | Apache 2.0 and offline, but larger language data (Hindi ≈ 15–30 MB each), slower, no confidence-ready Compose integration; ML Kit v2 is faster and its Devanagari model is good. Viable alternative where Google libraries are not allowed. |
| iText 7 / iText Core | AGPL (or commercial licence). Not suitable for a closed-source app without buying a licence. |
| MuPDF (mupdf-android) | AGPL (or commercial licence from Artifex). Excellent rendering/text editing primitives, but licence restricts closed-source use. |
| PSPDFKit/Nutrient, Apryse (PDFTron), Foxit, ComPDFKit | Commercial SDKs (annual licence, typically priced per app/platform). They provide reliable **in-place text editing**, redaction, form filling and higher-fidelity Office conversion. Recommended route if those features become requirements. |
| LibreOffice / server conversion | High-fidelity Word/Excel ↔ PDF, but requires a server and uploading documents – conflicts with the privacy goal. Only as an opt-in, clearly labelled feature if ever added. |

## 3. Offline vs. internet

**Everything works offline**, with one exception:

- **Camera scanner (ML Kit Document Scanner)** – runs inside Google Play services, which downloads the scanner module the first time it is used. The scanned images stay on the phone. If the module is unavailable (no Play services, offline on first use), *Import images* still works, without automatic edge detection.

DocDesk requests **no INTERNET permission** in its own manifest and has no analytics. Libraries that include Play services may contribute their own manifest entries; review the merged manifest before release (see [BUILD.md](BUILD.md)).

## 4. Features needing a server, subscription, paid library or future work

| Feature | What is needed | Suggested next step |
|---|---|---|
| Reflowing in-place text editing with the original fonts, editing existing images | Commercial SDK (Apryse, Nutrient/PSPDFKit, Foxit) | Phase 6: wrap the SDK behind *Edit PDF*; keep the free line-replacement tool |
| Text-preserving redaction (remove only the covered glyphs, keep the rest searchable) | Content-stream rewriting or commercial SDK | Current redaction rasterises the affected pages |
| Hardware-token DSC (USB Class 3 tokens), timestamping (TSA), long-term validation (LTV), trust-list validation | USB token drivers/PKCS#11 on Android, a TSA server (network), CA trust lists | Future; current signing uses .pfx/.p12 files and reports identity without trust-list validation |
| Full formatting of `.doc` (fonts, headings, images) and `.xls` (fills, borders, charts) | Parsing CHPX/PAPX/drawing records, or Apache POI | Future |
| Pixel-exact Word/Excel → PDF (exact fonts, charts, SmartArt) | Server-side LibreOffice/Office, or commercial SDK | Opt-in cloud conversion with explicit upload consent screen |
| Hindi in searchable-PDF text layer | Type0 font embedding with OpenType shaping (PdfBox 3 + HarfBuzz-style shaping) | Investigate PdfBox 3.x port or shaping via Android `TextShaper` (API 31+) |
| Handwriting recognition | ML Kit Digital Ink is for live strokes, not scans; cloud OCR (Google Cloud Vision, Azure) handles some handwriting | Only as opt-in cloud feature |
| Text-selection-based highlight (snap to words) | Hit-testing PDF text positions (already extracted) | Phase 4 enhancement |
| Form filling (AcroForm) | PdfBox supports AcroForm fields | Phase 4 enhancement |

## 5. Minimum Android version

**minSdk 26 (Android 8.0)**:
- `java.time`, adaptive icons and modern `StaticLayout` justification are available natively; no desugaring needed.
- Covers the large majority (roughly 95%+) of active Android devices according to recent Android Studio distribution data; check the current figure before release.
- ML Kit and the document scanner require API 21+, PdfBox-Android works from API 19 – 26 is not limited by libraries, it is a balance of reach and maintenance.
- **targetSdk/compileSdk 36** for current Play Store requirements.

## 6. Development phases – status

| Phase | Scope | Status |
|---|---|---|
| 1 Core PDF tools | Home & navigation, viewer, merge, split, organise, save/share | Done |
| 2 Conversion | PDF→Word, Word→PDF, PDF→Excel (text), Excel→PDF, previews & reports | Done |
| 3 Scanning, OCR, editing | Camera scan, English+Hindi OCR, OCR-assisted conversions, annotations & signatures | Done; in-place text editing deferred (see §4) |
| 4 Refinement | Performance, accessibility, privacy review, large files, user docs | Partly done (see [TESTING.md](TESTING.md)); on-device testing on a range of phones still required |
| 13 Fix & finish | Crop (auto/manual), flatten annotations and forms, repair damaged PDFs; AES-128 bug fix | Done (v1.9.0) |
| 14 Navigation & metadata | Bookmarks editor with auto-creation from headings (font-size analysis, running headers ignored); document properties editor and metadata removal; temp-file naming fix | Done (v1.10.0) |
| 15 Attachments & links | Embedded-file manager (add/extract/remove, 100 MB limit per file); auto-linking of URLs, e-mails and phone numbers via positioned text; scanned pages need OCR first | Done (v1.11.0) |
| 16 Printing | Printing via Android PrintManager (temporary decrypted copy, deleted after the job; no-print permission respected); N-up and booklet imposition with vector page forms; duplex-scan collation | Done (v1.12.0) |
| 17 Accountant workflows | Statement review with reconciliation, categories and 6-sheet workbook; invoice review with names/items/duplicate checks; client workspace and checklists; backup/restore; recycle bin; batch rename/split/report; cover and contents pages | Done (v1.13.0) – see FEATURE_STATUS.md |
| 12 Portal-ready PDFs | Compress to target size, split by size, resize pages to A4/Letter; deprecation clean-up | Done (v1.8.0) |
| 11 Security | Protect PDF (granular permissions, AES-256/128), Remove password with owner rights | Done (v1.7.0) |
| 10 Quality & release | Robolectric engine tests and screen smoke tests (run in CI), sanitised local problem reports, Play Store kit | Done (v1.6.0) |
| 9 Insights & usability | Statement month/party/category summaries, keyword→ledger rules, Tally XML export, Home search/favourites/categories, app shortcuts | Done (v1.5.0); Tally XML verified well-formed and with Tally's sign convention in tests; import should be tried on a Tally test company |
| 8 Compatibility & GST | .xls and .doc support, GST invoice register, search inside files | Done (v1.4.0); readers tested on files produced by LibreOffice; on-device testing required |
| 7 Accounting & privacy | Multi-statement normalisation to Excel/CSV, find & redact sensitive data, batch processing, app lock, screenshot blocking, read aloud | Done (v1.3.0); core logic unit-tested incl. real sample statement (55/55 rows, balances reconcile); on-device testing required |
| 6 Signatures & review | Digital signatures (sign/verify), Compare PDFs, PDF→JPG/PNG & image extraction, viewer bookmarks and text copy | Done (v1.2.0); signing verified on JVM with desktop PDFBox + Bouncy Castle (sign, double-sign, tamper detection, wrong password); on-device testing required |
| 5 Professional tools | Editor zoom, snap-to-text markups, Edit text, stamps, secure redaction, editable annotations, Create PDF hub, share-to-app, fill forms, watermark, page numbers/header/footer, compress | Done (v1.1.0); on-device testing required |
