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
            for ((k, i) in pages.sorted().withIndex()) {
                progress?.step("Securing redacted page ${i + 1}…", 0.6f + 0.3f * k / pages.size)
                val (w, h) = r.pageSize(i)
                val px = (w / 72f * 200f).toInt().coerceIn(800, 2400) // ≈200 dpi
                val bmp = r.render(i, px, cache = false) ?: continue
                val old = doc.getPage(i)
                val fresh = PDPage(PDRectangle(w.toFloat(), h.toFloat())) // displayed orientation, no /Rotate
                fresh.resources = PDResources()
                val img = JPEGFactory.createFromImage(doc, bmp, 0.85f)
                PDPageContentStream(doc, fresh).use { cs -> cs.drawImage(img, 0f, 0f, w.toFloat(), h.toFloat()) }
                bmp.recycle()
                // Replace in place so page order and links to other pages stay valid.
                doc.pages.insertBefore(fresh, old)
                doc.pages.remove(old)
            }
        }
        // Text in bookmarks and document properties could reveal redacted content.
        doc.documentInformation.cosObject.removeItem(COSName.KEYWORDS)
        doc.documentInformation.cosObject.removeItem(COSName.SUBJECT)
    }
}
