package com.docdesk.app

import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import com.docdesk.app.convert.CompareEngine
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.PdfToExcelEngine
import com.docdesk.app.convert.PdfToWordEngine
import com.docdesk.app.data.FileRepository
import com.docdesk.app.edit.Annot
import com.docdesk.app.edit.AnnotationWriter
import com.docdesk.app.edit.NPoint
import com.docdesk.app.edit.NRect
import com.docdesk.app.jobs.Progress
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.pdf.CompressLevel
import com.docdesk.app.pdf.FieldKind
import com.docdesk.app.pdf.FormFiller
import com.docdesk.app.pdf.HeaderFooterItem
import com.docdesk.app.pdf.NumberingOptions
import com.docdesk.app.pdf.PageRef
import com.docdesk.app.pdf.PasswordRequiredException
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfEnhance
import com.docdesk.app.pdf.PdfKind
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.app.pdf.Position
import com.docdesk.app.pdf.WatermarkOptions
import com.docdesk.app.sign.DigitalSigner
import com.docdesk.app.sign.SignOptions
import com.docdesk.core.DocxReader
import com.docdesk.core.StatementNormalizer
import com.docdesk.core.TableOptions
import com.docdesk.core.WordMode
import com.docdesk.core.XlsxReader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationTextMarkup
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDAcroForm
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDCheckBox
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDTextField
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationWidget
import com.tom_roush.pdfbox.pdmodel.font.PDType1Font
import com.tom_roush.pdfbox.pdmodel.PDResources
import com.tom_roush.pdfbox.cos.COSName
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Runs the Android-side engines (PdfBox-Android, writers, signing…) on the sample documents. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class EngineTest {

    private val samples = File(System.getProperty("docdesk.samples") ?: "../samples/out")
    private val app get() = ApplicationProvider.getApplicationContext<DocDeskApp>()
    private val progress = Progress { _, _ -> }
    private fun s(name: String) = File(samples, name).also { assumeTrue("missing sample $name", it.exists()) }
    private fun out(name: String) = app.files.newOutputFile(name)

    @Before fun ready() { assumeTrue(samples.exists()) }

    @Test fun inspectClassifiesTextAndScanned() {
        PdfDocs.open(s("bank_statement_text.pdf")).use { assertEquals(PdfKind.TEXT, PdfDocs.inspect(it).kind) }
        PdfDocs.open(s("bank_statement_scanned.pdf")).use { assertEquals(PdfKind.SCANNED, PdfDocs.inspect(it).kind) }
        PdfDocs.open(s("report_mixed_text_and_scan.pdf")).use { assertEquals(PdfKind.MIXED, PdfDocs.inspect(it).kind) }
    }

    @Test fun mergeWithRotationAndDuplicate() = runBlocking {
        val o = out("merged.pdf")
        PdfDocs.open(s("invoice.pdf")).use { a -> PdfDocs.open(s("large_100_pages.pdf")).use { b ->
            PdfOps.assemble(listOf(a, b), listOf(PageRef(0, 0), PageRef(1, 4, 90), PageRef(1, 4), PageRef(0, 0, 180)), o, progress)
        } }
        PdfDocs.open(o).use { d ->
            assertEquals(4, d.numberOfPages)
            assertEquals(listOf(0, 90, 0, 180), (0 until 4).map { d.getPage(it).rotation })
            assertTrue(PdfTextExtractor.plainText(d, 1).contains("page 5"))
        }
    }

    @Test fun passwordProtectAndOpen() {
        val o = out("p.pdf")
        PdfDocs.open(s("invoice.pdf")).use { com.docdesk.app.pdf.PdfSecurity.protect(it, o, "abcd", "owner123", com.docdesk.app.pdf.Allowed(print = true, copy = false), com.docdesk.app.pdf.Strength.AES256) }
        try { PdfDocs.open(o).close(); fail("should need a password") } catch (e: PasswordRequiredException) { assertTrue(!e.wrongPassword) }
        try { PdfDocs.open(o, "wrong").close(); fail() } catch (e: PasswordRequiredException) { assertTrue(e.wrongPassword) }
        PdfDocs.open(o, "abcd").use { assertTrue(it.isEncrypted); assertTrue(!it.currentAccessPermission.canExtractContent()) }
        // the sample with restricted permissions opens but refuses extraction
        PdfDocs.open(s("restricted_no_copy.pdf")).use { d ->
            try { PdfDocs.require(d, com.docdesk.app.pdf.PdfAction.EXTRACT); fail("permissions must be respected") } catch (e: Exception) { assertTrue(e.message!!.contains("does not allow")) }
        }
    }

    @Test fun protectAndUnlock() {
        val sec = com.docdesk.app.pdf.PdfSecurity
        // Open password only: the same password gives full rights, so it can unlock again.
        val a = out("a.pdf")
        PdfDocs.open(s("invoice.pdf")).use { sec.protect(it, a, "open123", null, com.docdesk.app.pdf.Allowed(), com.docdesk.app.pdf.Strength.AES256) }
        PdfDocs.open(a, "open123").use { d ->
            val info = sec.describe(d); assertTrue(info.ownerRights); assertEquals("AES-256", info.method)
            val u = out("a-unlocked.pdf"); sec.removeAll(d, u)
            PdfDocs.open(u).use { assertTrue(!it.isEncrypted) }
        }
        // Restrictions with a separate permissions password, AES-128, no open password.
        val b = out("b.pdf")
        PdfDocs.open(s("invoice.pdf")).use { sec.protect(it, b, "", "perm456", com.docdesk.app.pdf.Allowed(print = true, copy = false, edit = false), com.docdesk.app.pdf.Strength.AES128) }
        PdfDocs.open(b).use { d ->
            val info = sec.describe(d)
            assertEquals("AES-128", info.method); assertTrue(!info.ownerRights)
            assertTrue(info.restrictions.any { it.startsWith("Copying") }); assertTrue(info.restrictions.none { it.startsWith("Printing") })
            try { sec.removeAll(d, out("nope.pdf")); fail("must not remove without permissions password") } catch (e: IllegalStateException) { }
        }
        PdfDocs.open(b, "perm456").use { d -> assertTrue(d.currentAccessPermission.isOwnerPermission); val u = out("b-u.pdf"); sec.removeAll(d, u); PdfDocs.open(u).use { assertTrue(!it.isEncrypted) } }
    }

    @Test fun annotationsLandWhereShownEvenOnRotatedPages() {
        // Blank A4 page and a 90°-rotated copy, so added text can't mix with existing text.
        val blank = out("blank.pdf")
        PDDocument().use { it.addPage(PDPage(PDRectangle.A4)); it.save(blank) }
        val rotated = out("rot.pdf")
        runBlocking { PdfDocs.open(blank).use { PdfOps.assemble(listOf(it), listOf(PageRef(0, 0, 90)), rotated) } }
        for (src in listOf(blank, rotated)) {
            val o = out("ann-${src.name}")
            val annots = listOf(
                Annot.TextBox(1, 0, NPoint(0.1f, 0.1f), "HELLO MARK", 12f, android.graphics.Color.BLUE),
                Annot.Stamp(2, 0, NRect(0.5f, 0.5f, 0.85f, 0.57f), "PAID", "01-01-2025", android.graphics.Color.RED),
                Annot.Box(3, 0, Annot.BoxKind.HIGHLIGHT, NRect(0.1f, 0.3f, 0.5f, 0.32f), android.graphics.Color.YELLOW, 1f),
                Annot.Line(4, 0, NPoint(0.2f, 0.8f), NPoint(0.6f, 0.85f), true, android.graphics.Color.RED, 2f),
                Annot.Note(5, 0, NPoint(0.9f, 0.05f), "Check this", android.graphics.Color.YELLOW),
                Annot.Ink(6, 0, listOf(NPoint(0.1f, 0.9f), NPoint(0.2f, 0.92f), NPoint(0.3f, 0.9f)), android.graphics.Color.BLACK, 2f),
            )
            val st = PdfDocs.open(src).use { AnnotationWriter.write(it, annots, o, null, editable = true) }
            assertEquals(2, st.editableAnnotations) // highlight + arrow
            PdfDocs.open(o).use { d ->
                val subtypes = d.getPage(0).annotations.map { it.subtype }
                assertTrue(subtypes.toString(), subtypes.containsAll(listOf("Highlight", "Line", "Text")))
                assertTrue((d.getPage(0).annotations.first { it is PDAnnotationTextMarkup } as PDAnnotationTextMarkup).quadPoints.size == 8)
                // The text box must appear near (0.1, 0.1) of the page AS DISPLAYED.
                val t = PdfTextExtractor.extract(d, 0)
                val w = t.words.firstOrNull { it.text.contains("HELLO") }
                    ?: fail("HELLO not found on ${src.name} (rotation ${d.getPage(0).rotation}); words: ${t.words.take(60).joinToString { it.text }}; plain: ${PdfTextExtractor.plainText(d, 0).take(300)}").let { error("unreachable") }
                assertEquals("x for ${src.name}", 0.1, (w.x / t.width).toDouble(), 0.03)
                assertEquals("y for ${src.name}", 0.1, (w.y / t.height).toDouble(), 0.04)
                assertTrue(t.words.any { it.text == "PAID" })
            }
        }
    }

    @Test fun watermarkNumberingCompress() {
        val o = out("wm.pdf")
        PdfDocs.open(s("large_100_pages.pdf")).use { d ->
            PdfEnhance.watermark(d, listOf(0, 1), WatermarkOptions("CONFIDENTIAL"), null)
            PdfEnhance.numbering(d, (0 until d.numberOfPages).toList(), NumberingOptions(listOf(HeaderFooterItem("Page {n} of {total}", Position.BOTTOM_CENTER), HeaderFooterItem("INV-{n:4}", Position.TOP_RIGHT))), null)
            PdfOps.saveAtomically(d, o)
        }
        PdfDocs.open(o).use { d ->
            val p1 = PdfTextExtractor.plainText(d, 0)
            assertTrue(p1.contains("CONFIDENTIAL")); assertTrue(p1.contains("Page 1 of 100")); assertTrue(p1.contains("INV-0001"))
            assertTrue(PdfTextExtractor.plainText(d, 99).contains("Page 100 of 100"))
        }
        val c = out("small.pdf")
        PdfDocs.open(s("bank_statement_scanned.pdf")).use { d -> PdfEnhance.compress(d, CompressLevel.STRONG, null); PdfOps.saveAtomically(d, c) }
        assertTrue("compressed ${c.length()} vs ${s("bank_statement_scanned.pdf").length()}", c.length() < s("bank_statement_scanned.pdf").length())
    }

    @Test fun fillForm() {
        val form = out("form.pdf")
        PDDocument().use { doc ->
            val page = PDPage(PDRectangle.A4); doc.addPage(page)
            val acro = PDAcroForm(doc); doc.documentCatalog.acroForm = acro
            val res = PDResources(); res.put(COSName.getPDFName("Helv"), PDType1Font.HELVETICA); acro.defaultResources = res
            acro.defaultAppearance = "/Helv 10 Tf 0 g"
            val tf = PDTextField(acro); tf.partialName = "name"; tf.alternateFieldName = "Full name"
            val w = tf.widgets[0]; w.rectangle = PDRectangle(50f, 700f, 200f, 20f); w.page = page; page.annotations.add(w)
            val cb = PDCheckBox(acro); cb.partialName = "agree"
            val cw: PDAnnotationWidget = cb.widgets[0]; cw.rectangle = PDRectangle(50f, 650f, 15f, 15f); cw.page = page; page.annotations.add(cw)
            acro.fields.addAll(listOf(tf, cb))
            doc.save(form)
        }
        PdfDocs.open(form).use { d ->
            val f = FormFiller.read(d)
            assertEquals(listOf(FieldKind.TEXT, FieldKind.CHECKBOX), f.map { it.kind })
            assertEquals("Full name", f[0].label)
        }
        val filled = out("filled.pdf")
        PdfDocs.open(form).use { d -> val r = FormFiller.fill(d, mapOf("name" to "Asha Rao"), flatten = false); assertEquals(1, r.filled); PdfOps.saveAtomically(d, filled) }
        PdfDocs.open(filled).use { assertEquals("Asha Rao", FormFiller.read(it).first().value) }
    }

    @Test fun digitalSignatureRoundTrip() {
        val p12 = out("me.p12")
        DigitalSigner.createSelfSigned(p12, "Test Signer", "", "DocDesk Test", "secret1".toCharArray())
        val id = DigitalSigner.loadIdentity(p12, "secret1".toCharArray())
        val o = out("signed.pdf")
        DigitalSigner.sign(s("invoice.pdf"), o, id, SignOptions("Approved", "Pune", true, 0), app.files.workDir)
        val r = DigitalSigner.verify(o).single()
        assertTrue(r.intact && r.coversWholeFile && r.selfSigned)
    }

    @Test fun realExtractorOnBankStatement() = runBlocking {
        val uri = Uri.fromFile(s("bank_statement_text.pdf"))
        val ex = PdfToExcelEngine.extract(app, uri, null, (0 until 3).toList(), OcrMode.NEVER, OcrLanguage.LATIN, TableOptions(), app.files.workDir, progress)
        val n = StatementNormalizer.normalize(ex.tables, com.docdesk.core.NumberStyle.INDIAN, com.docdesk.core.DateOrder.DMY, "s")!!
        assertEquals(55, n.rows.size)
        assertEquals(emptyList<Int>(), StatementNormalizer.balanceMismatches(n.rows))
        val xlsx = out("t.xlsx")
        PdfToExcelEngine.export(ex.tables, com.docdesk.core.ExcelExportOptions(), emptyList(), xlsx)
        assertTrue(XlsxReader.read(xlsx.inputStream()).sheets.first().maxRow >= 55)
    }

    @Test fun pdfToWordAndCompare() = runBlocking {
        val uri = Uri.fromFile(s("report_mixed_text_and_scan.pdf"))
        val docx = out("r.docx")
        val r = PdfToWordEngine.convert(app, uri, "r.pdf", null, listOf(0), WordMode.EDITABLE, OcrMode.NEVER, OcrLanguage.LATIN, true, app.files.workDir, docx, progress)
        assertTrue(r.report.failedPages.isEmpty())
        val d = DocxReader.read(docx.inputStream())
        assertTrue(d.blocks.any { it is com.docdesk.core.DocBlock.Image })
        // Compare the invoice with a watermarked copy: the new text must be reported.
        val v2 = out("v2.pdf")
        PdfDocs.open(s("invoice.pdf")).use { doc -> PdfEnhance.numbering(doc, listOf(0), NumberingOptions(listOf(HeaderFooterItem("Revised copy", Position.TOP_LEFT))), null); PdfOps.saveAtomically(doc, v2) }
        val res = CompareEngine.compare(app, app.files.inputOf(s("invoice.pdf")), null, app.files.inputOf(v2), null, true, { app.files.newOutputFile(it) }, progress)
        assertTrue(res.report.checks.first(), res.report.checks.first().contains("1 added"))
    }

    @Test fun portalTools() = runBlocking {
        // Resize mixed pages (incl. a rotated one) to A4: every page A4, text still extractable.
        val mixed = out("mixed.pdf")
        PdfDocs.open(s("invoice.pdf")).use { a -> PdfDocs.open(s("large_100_pages.pdf")).use { b -> PdfOps.assemble(listOf(a, b), listOf(PageRef(0, 0), PageRef(1, 0, 90)), mixed) } }
        val a4 = out("a4.pdf")
        PdfDocs.open(mixed).use { com.docdesk.app.pdf.PortalTools.fitPages(it, a4, com.docdesk.core.PaperSize.A4, com.docdesk.app.pdf.FitOrientation.PORTRAIT, 18f, null) }
        PdfDocs.open(a4).use { d ->
            assertEquals(2, d.numberOfPages)
            (0 until 2).forEach { i -> assertEquals(595f, d.getPage(i).mediaBox.width, 1f); assertEquals(842f, d.getPage(i).mediaBox.height, 1f) }
            assertTrue(PdfTextExtractor.plainText(d, 0).contains("TAX INVOICE"))
            assertTrue(PdfTextExtractor.plainText(d, 1).contains("page 1"))
        }
        // Split the 100-page file into parts under 30 KB; every part must respect the limit.
        PdfDocs.open(s("large_100_pages.pdf")).use { d ->
            val parts = com.docdesk.app.pdf.PortalTools.splitBySize(d, 30L * 1024, { k -> out("part$k.pdf") }, app.files.workDir, progress)
            assertTrue(parts.size > 1)
            assertEquals((0 until 100).toList(), parts.flatMap { it.second })
            assertTrue(parts.all { it.first.length() <= 30L * 1024 })
        }
    }

    @Test fun cropFlattenRepair() = runBlocking {
        // Crop 50 pt from the displayed left on a 90°-rotated page: the visible width shrinks by 50.
        val rot = out("crop-src.pdf")
        PdfDocs.open(s("invoice.pdf")).use { PdfOps.assemble(listOf(it), listOf(PageRef(0, 0, 90)), rot) }
        PdfDocs.open(rot).use { d ->
            val before = d.getPage(0).cropBox
            assertEquals(1, com.docdesk.app.pdf.PdfFixes.crop(d, listOf(0), { com.docdesk.app.pdf.PdfFixes.Margins(50f, 0f, 0f, 0f) }, null))
            val after = d.getPage(0).cropBox
            // Display left of a 90° page = box bottom: height shrinks, width unchanged.
            assertEquals(before.width, after.width, 0.1f); assertEquals(before.height - 50f, after.height, 0.1f)
            assertEquals(before.lowerLeftY + 50f, after.lowerLeftY, 0.1f)
        }
        // Flatten: the stamp/highlight annotations disappear but their drawing stays on the page.
        val annotated = out("ann.pdf")
        PdfDocs.open(s("invoice.pdf")).use { AnnotationWriter.write(it, listOf(
            Annot.Box(1, 0, Annot.BoxKind.HIGHLIGHT, NRect(0.1f, 0.6f, 0.4f, 0.62f), android.graphics.Color.YELLOW, 1f),
            Annot.Note(2, 0, NPoint(0.5f, 0.7f), "note", android.graphics.Color.YELLOW)), annotated, null, editable = true) }
        val flat = out("flat.pdf")
        PdfDocs.open(annotated).use { d ->
            assertTrue(d.getPage(0).annotations.isNotEmpty())
            val st = com.docdesk.app.pdf.PdfFixes.flatten(d, null); assertTrue(st.annotations >= 1)
            PdfOps.saveAtomically(d, flat)
        }
        PdfDocs.open(flat).use { assertTrue(it.getPage(0).annotations.isEmpty()); assertTrue(PdfTextExtractor.plainText(it, 0).contains("TAX INVOICE")) }
        // Repair: remove the cross-reference table/trailer at the end – PdfBox rebuilds the structure.
        val bytes = s("invoice.pdf").readBytes()
        val cut = String(bytes, Charsets.ISO_8859_1).lastIndexOf("xref")
        val broken = out("broken.pdf"); broken.writeBytes(bytes.copyOf(if (cut > 0) cut else bytes.size - 100))
        val fixed = out("fixed.pdf")
        val r = com.docdesk.app.pdf.PdfFixes.repair(app, Uri.fromFile(broken), null, fixed, app.files.workDir, progress)
        assertTrue(r.method, r.method.startsWith("Structure rebuilt"))
        PdfDocs.open(fixed).use { assertEquals(1, it.numberOfPages); assertTrue(PdfTextExtractor.plainText(it, 0).contains("TAX INVOICE")) }
    }

    @Test fun sanitizeAndUniqueNames() {
        assertEquals("a_b_c.pdf", FileRepository.sanitize("a/b:c.pdf"))
        val dir = app.files.workDir
        File(dir, "x.pdf").writeText("1")
        assertEquals("x (2).pdf", FileRepository.unique(dir, "x.pdf").name)
    }
}
