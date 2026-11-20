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
