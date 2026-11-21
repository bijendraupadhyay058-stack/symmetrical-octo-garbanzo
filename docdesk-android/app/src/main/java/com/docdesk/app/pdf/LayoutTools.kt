package com.docdesk.app.pdf

import com.docdesk.app.jobs.Progress
import com.docdesk.core.Imposition
import com.docdesk.core.PageTransform
import com.docdesk.core.PaperSize
import com.tom_roush.pdfbox.multipdf.LayerUtility
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.graphics.form.PDFormXObject
import com.tom_roush.pdfbox.util.Matrix
import java.io.File

/** Print layouts: N pages per sheet, booklets, and collating double-sided scans. Pages stay vector (sharp, searchable). */
object LayoutTools {
    private fun displaySize(p: PDPage): Pair<Float, Float> = p.cropBox.let { PageTransform.displaySize(it.width, it.height, p.rotation) }

    private fun draw(cs: PDPageContentStream, form: PDFormXObject, pw: Float, ph: Float, slot: FloatArray, border: Boolean) {
        val (s, x, y) = Imposition.fit(pw, ph, slot).let { Triple(it[0], it[1], it[2]) }
        cs.saveGraphicsState()
        cs.transform(Matrix(s, 0f, 0f, s, x, y))
        cs.drawForm(form)
        cs.restoreGraphicsState()
        if (border) { cs.setLineWidth(0.5f); cs.setStrokingColor(0.6f, 0.6f, 0.6f); cs.addRect(x, y, pw * s, ph * s); cs.stroke() }
    }

    /** Places [perSheet] pages on each sheet of [paper], in reading order. Returns the number of sheets. */
    fun nUp(src: PDDocument, out: File, paper: PaperSize, perSheet: Int, marginPt: Float, borders: Boolean, progress: Progress?): Int {
        val n = src.numberOfPages
        val (fw, fh) = displaySize(src.getPage(0))
        val g = Imposition.grid(perSheet, sourceLandscape = fw > fh)
        val sw = if (g.landscape) paper.heightPt else paper.widthPt
        val sh = if (g.landscape) paper.widthPt else paper.heightPt
        val slots = Imposition.slots(sw, sh, g, marginPt, marginPt / 2)
        PDDocument().use { target ->
            val layer = LayerUtility(target)
            for (start in 0 until n step perSheet) {
                progress?.step("Arranging pages ${start + 1}–${minOf(n, start + perSheet)} of $n", start.toFloat() / n)
                val sheet = PDPage(PDRectangle(sw, sh)); target.addPage(sheet)
                PDPageContentStream(target, sheet).use { cs ->
                    for (k in 0 until perSheet) {
                        val i = start + k; if (i >= n) break
                        val page = src.getPage(i)
                        val (pw, ph) = displaySize(page)
                        draw(cs, layer.importPageAsForm(src, page), pw, ph, slots[k], borders)
                    }
                }
            }
            target.documentInformation.producer = "DocDesk"
            PdfOps.saveAtomically(target, out)
            return target.numberOfPages
        }
    }

    /** Two pages side by side on landscape sheets in booklet order. Returns the number of sheet sides. */
    fun booklet(src: PDDocument, out: File, paper: PaperSize, progress: Progress?): Int {
        val order = Imposition.booklet(src.numberOfPages)
        val sw = paper.heightPt; val sh = paper.widthPt
        val slots = Imposition.slots(sw, sh, Imposition.Grid(2, 1, true), 0f, 0f)
        PDDocument().use { target ->
            val layer = LayerUtility(target)
            val forms = HashMap<Int, PDFormXObject>()
            order.forEachIndexed { k, (l, r) ->
                progress?.step("Arranging sheet side ${k + 1} of ${order.size}", k.toFloat() / order.size)
                val sheet = PDPage(PDRectangle(sw, sh)); target.addPage(sheet)
                PDPageContentStream(target, sheet).use { cs ->
                    for ((slot, i) in listOf(slots[0] to l, slots[1] to r)) {
                        if (i < 0) continue
                        val page = src.getPage(i)
                        val (pw, ph) = displaySize(page)
                        // Each page is used once in a booklet; cache anyway in case of repeats.
                        draw(cs, forms.getOrPut(i) { layer.importPageAsForm(src, page) }, pw, ph, slot, false)
                    }
                }
            }
            target.documentInformation.producer = "DocDesk"
            PdfOps.saveAtomically(target, out)
            return target.numberOfPages
        }
    }

    /** Interleaves a fronts scan and a backs scan into one document. Returns the page count. */
    fun collate(fronts: PDDocument, backs: PDDocument, backsReversed: Boolean, out: File, progress: Progress?): Int {
        val order = Imposition.collate(fronts.numberOfPages, backs.numberOfPages, backsReversed)
        PDDocument().use { target ->
            order.forEachIndexed { k, (isBack, i) ->
                progress?.step("Adding page ${k + 1} of ${order.size}", k.toFloat() / order.size)
                PdfOps.copyPage(target, (if (isBack) backs else fronts).getPage(i), 0)
            }
            target.documentInformation.producer = "DocDesk"
            PdfOps.saveAtomically(target, out)
            return target.numberOfPages
        }
    }
}
