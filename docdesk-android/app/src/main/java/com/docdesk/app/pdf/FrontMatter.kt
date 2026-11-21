package com.docdesk.app.pdf

import com.docdesk.app.edit.AnnotationWriter
import com.docdesk.app.jobs.Progress
import com.docdesk.core.OutlineEntry
import com.docdesk.core.PageTransform
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.font.PDType1Font
import com.tom_roush.pdfbox.pdmodel.graphics.image.LosslessFactory
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationLink
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDBorderStyleDictionary
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.destination.PDPageFitWidthDestination
import com.tom_roush.pdfbox.pdmodel.interactive.action.PDActionGoTo

/** Cover page, contents page(s) and blank pages, added in front of / inside an existing PDF. */
object FrontMatter {
    data class Cover(val title: String, val subtitle: String = "", val preparedFor: String = "", val preparedBy: String = "", val date: String = "")
    data class Result(val coverPages: Int, val contentsPages: Int, val blankPages: Int, val contentsEntries: Int)

    private const val MARGIN = 64f

    private fun latin(t: String) = try { PDType1Font.HELVETICA.encode(t); true } catch (e: Exception) { false }

    /** Draws one line of text; Unicode text (Hindi, ₹…) is drawn as a high-resolution image because the built-in font is Latin-only. Returns its width. */
    private fun text(doc: PDDocument, cs: PDPageContentStream, t: String, x: Float, y: Float, size: Float, bold: Boolean, maxW: Float, alignRight: Boolean = false, centre: Boolean = false): Float {
        if (t.isEmpty()) return 0f
        if (latin(t)) {
            val font = if (bold) PDType1Font.HELVETICA_BOLD else PDType1Font.HELVETICA
            var s = t; var w = font.getStringWidth(s) / 1000f * size
            while (w > maxW && s.length > 1) { s = s.dropLast(2) + "…".takeIf { latin(it) }.orEmpty().ifEmpty { "." }; w = font.getStringWidth(s) / 1000f * size }
            val xx = when { alignRight -> x - w; centre -> x - w / 2; else -> x }
            cs.beginText(); cs.setFont(font, size); cs.newLineAtOffset(xx, y); cs.showText(s); cs.endText()
            return w
        }
        val b = AnnotationWriter.renderText(t, size, android.graphics.Color.BLACK, bold)
        val img = LosslessFactory.createFromImage(doc, b); val w0 = b.width / 4f; val h0 = b.height / 4f; b.recycle()
        val k = if (w0 > maxW) maxW / w0 else 1f
        val w = w0 * k; val h = h0 * k
        val xx = when { alignRight -> x - w; centre -> x - w / 2; else -> x }
        cs.drawImage(img, xx, y - h * 0.25f, w, h)
        return w
    }

    /**
     * Adds front matter to [doc] in place: [cover], a contents page built from [contents] (0-based
     * original page numbers) and blank pages after the given 1-based original pages (0 = before page 1).
     * Contents rows show the final page numbers and link to their pages.
     */
    fun apply(doc: PDDocument, cover: Cover?, contents: List<OutlineEntry>?, blanksAfter: List<Int>, progress: Progress?): Result {
        val n = doc.numberOfPages
        val originals = (0 until n).map { doc.getPage(it) }
        val first = originals.first()
        val (w, h) = first.cropBox.let { PageTransform.displaySize(it.width, it.height, first.rotation) }
        fun newPage() = PDPage(PDRectangle(w, h))

        // Blank pages first (they shift the contents' page numbers).
        val blanks = blanksAfter.filter { it in 0..n }.sorted()
        for (after in blanks.sortedDescending()) {
            val p = newPage()
            if (after == 0) doc.pages.insertBefore(p, originals[0]) else doc.pages.insertAfter(p, originals[after - 1])
        }
        val front = mutableListOf<PDPage>()
        if (cover != null) {
            progress?.step("Creating cover page", 0.2f)
            val p = newPage()
            PDPageContentStream(doc, p).use { cs ->
                cs.setNonStrokingColor(0.12f, 0.31f, 0.64f); cs.addRect(0f, h - 14f, w, 14f); cs.fill()
                cs.setNonStrokingColor(0f, 0f, 0f)
                val cx = w / 2; val maxW = w - 2 * MARGIN
                var y = h * 0.62f
                text(doc, cs, cover.title, cx, y, 28f, true, maxW, centre = true)
                if (cover.subtitle.isNotBlank()) { y -= 34f; text(doc, cs, cover.subtitle, cx, y, 16f, false, maxW, centre = true) }
                y = h * 0.30f
                cs.setNonStrokingColor(0.25f, 0.25f, 0.25f)
                if (cover.preparedFor.isNotBlank()) { text(doc, cs, "Prepared for: ${cover.preparedFor}", cx, y, 12f, false, maxW, centre = true); y -= 20f }
                if (cover.preparedBy.isNotBlank()) { text(doc, cs, "Prepared by: ${cover.preparedBy}", cx, y, 12f, false, maxW, centre = true); y -= 20f }
                if (cover.date.isNotBlank()) text(doc, cs, cover.date, cx, y, 12f, false, maxW, centre = true)
            }
            front.add(p)
        }
        val entries = contents.orEmpty().filter { it.page in 0 until n && it.title.isNotBlank() }
        val tocPages = mutableListOf<PDPage>()
        if (contents != null && entries.isNotEmpty()) {
            progress?.step("Creating contents page", 0.5f)
            val rowH = 18f; val top = h - MARGIN - 40f
            val perPage = ((top - MARGIN) / rowH).toInt().coerceAtLeast(5)
            val pageCountTotal = (entries.size + perPage - 1) / perPage
            repeat(pageCountTotal) { tocPages.add(newPage()) }
            // Final 1-based number of each original page = its index in the finished document.
            val frontCount = front.size + tocPages.size
            fun finalNumber(orig: Int) = frontCount + doc.pages.indexOf(originals[orig]) + 1
            entries.chunked(perPage).forEachIndexed { pi, chunk ->
                val p = tocPages[pi]
                val links = mutableListOf<PDAnnotationLink>()
                PDPageContentStream(doc, p).use { cs ->
                    if (pi == 0) text(doc, cs, "Contents", MARGIN, h - MARGIN - 10f, 20f, true, w - 2 * MARGIN)
                    var y = top
                    for (e in chunk) {
                        val x = MARGIN + e.level.coerceAtMost(4) * 16f
                        val num = finalNumber(e.page).toString()
                        val numW = text(doc, cs, num, w - MARGIN, y, 11f, false, 60f, alignRight = true)
                        val tw = text(doc, cs, e.title, x, y, 11f, e.level == 0, w - MARGIN - x - numW - 24f)
                        // Dot leader
                        cs.setNonStrokingColor(0.6f, 0.6f, 0.6f)
                        var dx = x + tw + 6f
                        while (dx < w - MARGIN - numW - 8f) { cs.addRect(dx, y + 2f, 1f, 1f); dx += 4f }
                        cs.fill(); cs.setNonStrokingColor(0f, 0f, 0f)
                        links.add(PDAnnotationLink().apply {
                            rectangle = PDRectangle(x, y - 4f, w - MARGIN - x, rowH - 2f)
                            borderStyle = PDBorderStyleDictionary().apply { width = 0f }
                            action = PDActionGoTo().apply { destination = PDPageFitWidthDestination().apply { page = originals[e.page] } }
                        })
                        y -= rowH
                    }
                }
                p.annotations = links
            }
        }
        // Insert cover + contents before the (possibly blank) first page.
        val firstNow = doc.getPage(0)
        (front + tocPages).forEach { doc.pages.insertBefore(it, firstNow) }
        return Result(front.size, tocPages.size, blanks.size, entries.size)
    }
}
