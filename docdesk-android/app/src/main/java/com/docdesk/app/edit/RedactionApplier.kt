package com.docdesk.app.edit

import com.docdesk.app.jobs.Progress
import com.docdesk.app.pdf.PageRenderer
import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.PDResources
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.graphics.image.JPEGFactory
import java.io.File

/**
 * Secure redaction. Pages that carry black redaction boxes (already drawn into [annotated])
 * are rendered to images and their original content (text, fonts, vector drawings, hidden
 * layers, annotations) is replaced by that image, so the covered information is really gone.
 * Trade-off: those pages are no longer searchable or selectable.
 */
object RedactionApplier {
    /**
     * Full pipeline: draws black boxes for [annots] (all REDACT boxes, possibly other markups),
     * rebuilds the affected pages as images, keeps the original's protection policy and saves
     * to [out]. Returns a note about password protection, if any.
     */
    suspend fun redactToFile(context: android.content.Context, uri: android.net.Uri, password: String?, annots: List<Annot>, out: File, work: File, progress: Progress?): String? {
        val pages = annots.filter { it is Annot.Box && it.kind == Annot.BoxKind.REDACT }.map { it.page }.toSet()
        com.docdesk.app.pdf.PdfDocs.open(context, uri, password).use { doc ->
            com.docdesk.app.pdf.PdfDocs.require(doc, com.docdesk.app.pdf.PdfAction.MODIFY)
            val perm = if (doc.isEncrypted) doc.currentAccessPermission else null
            AnnotationWriter.apply(doc, annots, editable = false, progress = progress)
            val tmp = File.createTempFile("red", ".pdf", work)
            try {
                doc.isAllSecurityToBeRemoved = true
                doc.save(tmp)
                com.docdesk.app.pdf.PdfDocs.open(tmp).use { red ->
                    apply(red, tmp, pages, progress)
                    val note = com.docdesk.app.pdf.PdfOps.reapplyProtection(perm, red, password)
                    progress?.step("Saving…", 0.95f)
                    com.docdesk.app.pdf.PdfOps.saveAtomically(red, out)
                    return note
                }
            } finally { tmp.delete() }
        }
    }

    /** Rewrites [pages] (0-based) of [doc], which was loaded from [annotated]. */
    suspend fun apply(doc: PDDocument, annotated: File, pages: Set<Int>, progress: Progress?) {
        PageRenderer.open(annotated).use { r ->
            applyWith(doc, pages, progress, { i -> r.pageSize(i).let { (w, h) -> w.toFloat() to h.toFloat() } }) { i, w ->
                r.render(i, (w / 72f * 200f).toInt().coerceIn(800, 2400), cache = false) // ≈200 dpi
            }
        }
        scrubMetadata(doc)
    }

    /**
     * Replaces each page in [pages] by an image of itself, so none of its text, fonts, vector
     * drawings, hidden layers or annotations remain. [size] gives the displayed page size in points;
     * [render] draws the page (with the black boxes already on it).
     */
    suspend fun applyWith(doc: PDDocument, pages: Set<Int>, progress: Progress?, size: suspend (Int) -> Pair<Float, Float>, render: suspend (Int, Float) -> android.graphics.Bitmap?) {
        for ((k, i) in pages.sorted().withIndex()) {
            progress?.step("Securing redacted page ${i + 1}…", 0.6f + 0.3f * k / pages.size)
            val (w, h) = size(i)
            val bmp = render(i, w) ?: throw IllegalStateException("Page ${i + 1} could not be drawn, so it was not redacted.")
            val old = doc.getPage(i)
            val fresh = PDPage(PDRectangle(w, h)) // displayed orientation, no /Rotate
            fresh.resources = PDResources()
            val img = JPEGFactory.createFromImage(doc, bmp, 0.85f)
            PDPageContentStream(doc, fresh).use { cs -> cs.drawImage(img, 0f, 0f, w, h) }
            bmp.recycle()
            // Replace in place so page order and links to other pages stay valid.
            doc.pages.insertBefore(fresh, old)
            doc.pages.remove(old)
        }
    }

    fun scrubMetadata(doc: PDDocument) {
        // Text in bookmarks and document properties could reveal redacted content.
        doc.documentInformation.cosObject.removeItem(COSName.KEYWORDS)
        doc.documentInformation.cosObject.removeItem(COSName.SUBJECT)
    }
}
