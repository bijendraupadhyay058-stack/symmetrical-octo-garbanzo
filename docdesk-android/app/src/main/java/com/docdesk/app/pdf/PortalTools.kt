package com.docdesk.app.pdf

import android.content.Context
import android.net.Uri
import com.docdesk.app.jobs.OperationCancelled
import com.docdesk.app.jobs.Progress
import com.docdesk.core.PageTransform
import com.docdesk.core.PaperSize
import com.docdesk.core.SizeSplitter
import com.tom_roush.pdfbox.multipdf.LayerUtility
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.graphics.image.JPEGFactory
import com.tom_roush.pdfbox.util.Matrix
import java.io.File

enum class FitOrientation(val label: String) { AUTO("Same as each page"), PORTRAIT("Always portrait"), LANDSCAPE("Always landscape") }

/** Tools for upload portals with file-size and page-size rules (GST, Income Tax, banks, exams…). */
object PortalTools {

    /**
     * Places every page, scaled to fit, on a page of [paper] size with [marginPt] margins.
     * Pages are embedded as vector content, so text stays sharp and searchable.
     */
    fun fitPages(src: PDDocument, out: File, paper: PaperSize, orientation: FitOrientation, marginPt: Float, progress: Progress?) {
        PDDocument().use { target ->
            val layer = LayerUtility(target)
            for (i in 0 until src.numberOfPages) {
                progress?.step("Resizing page ${i + 1} of ${src.numberOfPages}", i.toFloat() / src.numberOfPages)
                val page = src.getPage(i)
                val box = page.cropBox
                val (dw, dh) = PageTransform.displaySize(box.width, box.height, page.rotation)
                val landscape = when (orientation) { FitOrientation.AUTO -> dw > dh; FitOrientation.PORTRAIT -> false; FitOrientation.LANDSCAPE -> true }
                val tw = if (landscape) paper.heightPt else paper.widthPt
                val th = if (landscape) paper.widthPt else paper.heightPt
                val s = minOf((tw - 2 * marginPt) / dw, (th - 2 * marginPt) / dh)
                val form = layer.importPageAsForm(src, page) // handles crop box and /Rotate
                val newPage = PDPage(PDRectangle(tw, th))
                target.addPage(newPage)
                PDPageContentStream(target, newPage).use { cs ->
                    cs.saveGraphicsState()
                    cs.transform(Matrix(s, 0f, 0f, s, (tw - dw * s) / 2, (th - dh * s) / 2))
                    cs.drawForm(form)
                    cs.restoreGraphicsState()
                }
            }
            target.documentInformation.producer = "DocDesk"
            PdfOps.saveAtomically(target, out)
        }
    }

    data class SizeResult(val file: File, val bytes: Long, val method: String, val reached: Boolean, val rasterised: Boolean)

    /**
     * Tries progressively stronger steps until the file is at most [limit] bytes:
     * 1) recompress images (light, medium, strong) – text stays as text;
     * 2) only if still too big: rebuild pages as images at decreasing resolution/quality.
     * Returns the smallest result found, saying whether the target was reached.
     */
    suspend fun compressToSize(context: Context, uri: Uri, password: String?, encrypted: Boolean, limit: Long, outName: (String) -> File, work: File, progress: Progress): SizeResult {
        var best: SizeResult? = null
        fun keep(r: SizeResult) { if (best == null || r.bytes < best!!.bytes) { best?.file?.takeIf { it != r.file }?.delete(); best = r } else r.file.delete() }
        for ((k, level) in CompressLevel.entries.withIndex()) {
            progress.step("Trying ${level.label.substringBefore(" –").lowercase()} compression…", 0.05f + 0.1f * k)
            val f = outName("try-$k.pdf")
            PdfDocs.open(context, uri, password).use { d ->
                PdfDocs.require(d, PdfAction.MODIFY)
                PdfEnhance.compress(d, level, null)
                if (d.isEncrypted) d.isAllSecurityToBeRemoved = true
                PdfOps.saveAtomically(d, f)
            }
            keep(SizeResult(f, f.length(), "Images recompressed (${level.label.substringBefore(" –").lowercase()})", f.length() <= limit, false))
            if (best!!.reached) return best!!
        }
        // Rasterise: page images; try a sequence of resolution/quality pairs from best to smallest.
        val steps = listOf(150 to 0.75f, 130 to 0.6f, 110 to 0.5f, 96 to 0.45f, 80 to 0.4f, 72 to 0.3f)
        val renderer = if (encrypted) PageRenderer.openDecryptedCopy(context, uri, password ?: "", work) else PageRenderer.open(context, uri, work)
        renderer.use { r ->
            for ((k, step) in steps.withIndex()) {
                val (dpi, q) = step
                if (progress.cancelRequested) throw OperationCancelled()
                val f = outName("img-$k.pdf")
                PDDocument().use { doc ->
                    for (i in 0 until r.pageCount) {
                        progress.step("Rebuilding pages at $dpi dpi: page ${i + 1} of ${r.pageCount}", 0.35f + 0.6f * (k * r.pageCount + i) / (steps.size * r.pageCount))
                        val (w, h) = r.pageSize(i)
                        val bmp = r.render(i, (w / 72f * dpi).toInt().coerceAtLeast(200), cache = false) ?: continue
                        val page = PDPage(PDRectangle(w.toFloat(), h.toFloat())); doc.addPage(page)
                        val img = JPEGFactory.createFromImage(doc, bmp, q)
                        PDPageContentStream(doc, page).use { it.drawImage(img, 0f, 0f, w.toFloat(), h.toFloat()) }
                        bmp.recycle()
                    }
                    PdfOps.saveAtomically(doc, f)
                }
                keep(SizeResult(f, f.length(), "Pages rebuilt as images ($dpi dpi, quality ${(q * 100).toInt()}%)", f.length() <= limit, true))
                if (best!!.reached) return best!!
            }
        }
        return best!!
    }

    /** Splits into parts of at most [limit] bytes (estimated per page, then verified). */
    suspend fun splitBySize(doc: PDDocument, limit: Long, outName: (Int) -> File, work: File, progress: Progress): List<Pair<File, List<Int>>> {
        val n = doc.numberOfPages
        val sizes = (0 until n).map { i ->
            progress.step("Measuring page ${i + 1} of $n", 0.5f * i / n)
            val t = File.createTempFile("page", ".pdf", work)
            try { PDDocument().use { one -> PdfOps.copyPage(one, doc.getPage(i), 0); one.save(t) }; t.length() } finally { t.delete() }
        }
        // Single-page files repeat shared fonts, so the sum over-estimates; a 5% margin keeps parts under the limit.
        val groups = SizeSplitter.groups(sizes, (limit * 0.95).toLong())
        val out = mutableListOf<Pair<File, List<Int>>>()
        val queue = ArrayDeque(groups)
        while (queue.isNotEmpty()) {
            val g = queue.removeFirst()
            progress.step("Creating part ${out.size + 1}", 0.5f + 0.5f * out.size / (groups.size + 1))
            val f = outName(out.size + 1)
            PdfOps.assemble(listOf(doc), g.map { PageRef(0, it) }, f)
            if (f.length() > limit && g.size > 1) { f.delete(); queue.addFirst(g.subList(g.size / 2, g.size)); queue.addFirst(g.subList(0, g.size / 2)) }
            else out.add(f to g)
        }
        return out
    }
}
