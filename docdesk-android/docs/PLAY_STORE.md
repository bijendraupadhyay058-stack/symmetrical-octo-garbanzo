# Publishing DocDesk on Google Play – step-by-step kit

Everything you need to fill in the Play Console. Replace text in **[brackets]**.

## 0. Before you start (one-time decisions)

| Item | Notes |
|---|---|
| **Application ID** | Permanent. Currently `com.docdesk.app` (may already be taken). Choose e.g. `com.<yourname>.docdesk`; it is set in `app/build.gradle.kts` (`applicationId`). |
| **App name** | Max 30 characters, e.g. `DocDesk: PDF, Excel & GST` |
| **Developer account** | play.google.com/console – $25 one-time, ID verification. Personal accounts must run a **closed test with ≥12 testers for 14 days** before production. |
| **Signing** | Use *Play App Signing* (default). You keep an **upload key** (`keystore.properties`, see BUILD.md); if lost, Google support can reset it. |

## 1. Build the upload file

```bash
./gradlew :app:bundleRelease   # app/build/outputs/bundle/release/app-release.aab
```

## 2. Store listing (Main store listing)

**App name (≤30):** DocDesk: PDF, Excel & GST

**Short description (≤80):**
`PDF to Excel & Word, bank statements, GST invoices, edit, sign & scan – offline`

**Full description (≤4000):**
```
DocDesk is a private, offline PDF and document toolkit for accountants, businesses and professionals. Your files are processed on your phone – nothing is uploaded.

CONVERT
• PDF to Excel – tables from bank statements, invoices and reports, with Indian number formats, an editable review and highlighted cells to check
• PDF to Word – editable text, headings, lists, tables and images
• Word, Excel and photos to PDF – including old .doc/.xls and Tally exports
• Scan documents with your camera; OCR for English and Hindi; searchable PDFs
• PDF to JPG/PNG

ACCOUNTING
• Bank statements to one Excel/CSV – sorted, checked, month-wise and party-wise summaries
• Tally import file (Payment, Receipt and Contra vouchers) using your own ledger rules
• GST invoice register – GSTIN, taxable value, CGST, SGST, IGST and total with checks

EDIT & SIGN
• Highlight, underline, draw, shapes, text, stamps (PAID, APPROVED…), comments
• Edit a line of text, add images and signatures
• Digital signatures with certificates; check signatures on received PDFs
• Fill PDF forms, watermark, page numbers, header & footer

ORGANISE
• Merge, split, reorder, rotate, delete and extract pages
• Compress, compare two versions, batch process many files

PRIVACY & SECURITY
• Find & redact PAN, Aadhaar, GSTIN, account and card numbers – permanently
• Password-protect PDFs (AES-256)
• App lock with fingerprint, screenshot blocking
• No ads, no tracking, no account needed

Conversions are never perfect: DocDesk shows a report with every conversion and flags values to check. It never invents figures.
```

**Category:** Business · **Tags:** PDF, Productivity, Business, Finance tools
**Contact e-mail:** [your email] · **Privacy policy URL:** [link to published privacy-policy.html]

**Graphics (in `docs/store/`):**
| Asset | File |
|---|---|
| App icon 512×512 | `icon-512.png` |
| Feature graphic 1024×500 | `feature-graphic-1024x500.png` |
| Phone screenshots (2–8, 16:9 or 9:16) | Take on your phone: Home, PDF→Excel review, Bank statements result, Edit with stamp, Digital signature |

## 3. Publish the privacy policy

1. Open `docs/store/privacy-policy.html`, replace **[DATE]**, **[YOUR NAME / BUSINESS]** and **[YOUR EMAIL]**.
2. Free hosting options: **Google Sites** (sites.google.com → new site → paste the text → Publish) or GitHub Pages. Copy the public link into the Play Console.

## 4. App content forms – answers

| Form | Answer |
|---|---|
| **Privacy policy** | Your published link |
| **Ads** | No, the app does not contain ads |
| **App access** | All functionality is available without special access (no login) |
| **Content rating** (IARC questionnaire) | Category: *Utility, Productivity, Communication or other*; answer **No** to violence, sexuality, language, controlled substances, gambling, user-generated content sharing, location sharing. Expected rating: Everyone / 3+ |
| **Target audience** | 18 and over (business app). Not designed for children |
| **News app** | No |
| **COVID-19 tracing** | No |
| **Data safety** | **Does your app collect or share any of the required user data types? → No.** Data is processed on device only ("processed ephemerally / on-device" is not collection). Encryption in transit: not applicable (no transfer). Users can request deletion: not applicable (no data held by developer). |
| **Government app** | No |
| **Financial features** | Select "None of the above" (DocDesk does not provide banking, loans or payments; it only processes documents the user owns) |
| **Health** | No |

Note on Google Play services: the document scanner module is provided by Google Play services; Google's own data handling is covered by Google's policies and does not need declaring as your app's collection.

## 5. Testing track and release

1. *Testing › Closed testing* → create track → upload `app-release.aab` → add testers' Gmail addresses (≥12) → share the opt-in link.
2. Testers install and keep the app for **14 days**; collect feedback (Settings › Send problem report helps).
3. *Production* → *Apply for production access* → answer questions about testing → create release with the same or newer bundle (increase `versionCode` for every upload).
4. Review usually takes from a few hours to several days.

## 6. Every update

Increase `versionCode` (and `versionName`) in `app/build.gradle.kts`, build `bundleRelease`, upload to the track, add release notes.
