package com.docdesk.app.pdf

import com.docdesk.app.jobs.Progress
import com.docdesk.core.FoundLink
import com.docdesk.core.LinkFinder
import com.docdesk.core.PageTransform
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.interactive.action.PDActionURI
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationLink
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDBorderStyleDictionary

/** Turns web addresses, e-mail addresses and phone numbers in the text into clickable links. */
object PdfLinks {
    data class Stats(val web: Int, val email: Int, val phone: Int, val skippedExisting: Int, val pagesWithoutText: Int) {
        val total get() = web + email + phone
    }

    suspend fun autoLink(doc: PDDocument, kinds: Set<FoundLink.Kind>, pages: List<Int>, progress: Progress?): Stats {
        var web = 0; var email = 0; var phone = 0; var skipped = 0; var noText = 0
        pages.forEachIndexed { k, i ->
            progress?.step("Looking for links on page ${i + 1}", k.toFloat() / pages.size)
            val text = PdfTextExtractor.extract(doc, i)
            if (text.words.isEmpty()) { noText++; return@forEachIndexed }
            val page = doc.getPage(i)
            val box = page.cropBox
            val (_, dh) = PageTransform.displaySize(box.width, box.height, page.rotation)
            val t = PageTransform.displayToPdf(box.lowerLeftX, box.lowerLeftY, box.width, box.height, page.rotation)
            val annots = page.annotations
            val existing = annots.filterIsInstance<PDAnnotationLink>().map { it.rectangle }
            for (link in LinkFinder.find(text.words, kinds)) {
                val rects = link.rects.map { r ->
                    // Display (top-left origin) → PDF user space; pad 1 pt so the tap target covers the glyphs.
                    val (x0, y0) = t.apply(r[0] - 1f, dh - r[3] - 1f); val (x1, y1) = t.apply(r[2] + 1f, dh - r[1] + 1f)
                    PDRectangle(minOf(x0, x1), minOf(y0, y1), kotlin.math.abs(x1 - x0), kotlin.math.abs(y1 - y0))
                }
                if (rects.any { r -> existing.any { overlaps(it, r) } }) { skipped++; continue }
                for (r in rects) {
                    val a = PDAnnotationLink()
                    a.rectangle = r
                    a.borderStyle = PDBorderStyleDictionary().apply { width = 0f }
                    a.action = PDActionURI().apply { uri = link.target }
                    a.isPrinted = true
                    annots.add(a)
                }
                when (link.kind) { FoundLink.Kind.WEB -> web++; FoundLink.Kind.EMAIL -> email++; FoundLink.Kind.PHONE -> phone++ }
            }
            page.annotations = annots
        }
        return Stats(web, email, phone, skipped, noText)
    }

    private fun overlaps(a: PDRectangle, b: PDRectangle) =
        a.lowerLeftX < b.upperRightX && b.lowerLeftX < a.upperRightX && a.lowerLeftY < b.upperRightY && b.lowerLeftY < a.upperRightY

    /** Counts existing web links (for the report). */
    fun countLinks(doc: PDDocument): Int = doc.pages.sumOf { p -> runCatching { p.annotations.count { it is PDAnnotationLink } }.getOrDefault(0) }
}
