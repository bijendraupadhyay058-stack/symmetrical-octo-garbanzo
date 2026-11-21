package com.docdesk.app.pdf

import android.content.Context
import android.graphics.Color
import android.net.Uri
import com.docdesk.app.jobs.Progress
import com.docdesk.core.PageTransform
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.graphics.image.JPEGFactory
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationLink
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationPopup
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationWidget
import com.tom_roush.pdfbox.util.Matrix
import java.io.File

/** Crop, flatten and repair. */
object PdfFixes {

    /** Margins in points on the page as displayed. */
    data class Margins(val left: Float, val top: Float, val right: Float, val bottom: Float)

    /**
     * Sets the visible area (crop box) of [pages]. Content outside is hidden, not deleted –
     * the report says so, because hidden content can still be recovered by other tools.
     */
    fun crop(doc: PDDocument, pages: List<Int>, marginsFor: (Int) -> Margins?, progress: Progress?): Int {
        var changed = 0
        for ((k, i) in pages.withIndex()) {
            progress?.step("Cropping page ${i + 1}", k.toFloat() / pages.size)
            val m = marginsFor(i) ?: continue
            val page = doc.getPage(i)
            val box = page.cropBox
            val (l, b, r, t) = PageTransform.displayMarginsToBox(page.rotation, m.left, m.top, m.right, m.bottom).toList()
            val w = box.width - l - r; val h = box.height - b - t
            if (w < 36 || h < 36) continue // never crop a page to (almost) nothing
            page.cropBox = PDRectangle(box.lowerLeftX + l, box.lowerLeftY + b, w, h)
            changed++
        }
        return changed
    }

    /** Detects white borders by rendering at low resolution; returns margins with [padPt] padding. */
    suspend fun autoMargins(renderer: PageRenderer, index: Int, padPt: Float): Margins? {
        val (w, h) = renderer.pageSize(index)
        val bmp = renderer.render(index, 500, cache = false) ?: return null
        val px = IntArray(bmp.width * bmp.height)
        bmp.getPixels(px, 0, bmp.width, 0, 0, bmp.width, bmp.height)
        val grey = IntArray(px.size) { (Color.red(px[it]) * 30 + Color.green(px[it]) * 59 + Color.blue(px[it]) * 11) / 100 }
        val b = PageTransform.contentBounds(grey, bmp.width, bmp.height) ?: return null
        bmp.recycle()
        return Margins(
            (b[0] * w - padPt).coerceAtLeast(0f), (b[1] * h - padPt).coerceAtLeast(0f),
            ((1 - b[2]) * w - padPt).coerceAtLeast(0f), ((1 - b[3]) * h - padPt).coerceAtLeast(0f),
        )
    }

    data class FlattenStats(val annotations: Int, val formFields: Int)

    /**
     * Makes comments, markups, stamps and form fields part of the page content. Links stay
     * clickable; pop-up note windows are removed (their icon stays visible).
     */
    fun flatten(doc: PDDocument, progress: Progress?): FlattenStats {
        var fields = 0
        doc.documentCatalog.acroForm?.let { form ->
            fields = form.fields.size
            runCatching { form.refreshAppearances() }
            form.flatten()
        }
        var count = 0
        for (i in 0 until doc.numberOfPages) {
            progress?.step("Flattening page ${i + 1}", i.toFloat() / doc.numberOfPages)
            val page = doc.getPage(i)
            val keep = mutableListOf<com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotation>()
            val annots = page.annotations
            if (annots.isEmpty()) continue
            PDPageContentStream(doc, page, PDPageContentStream.AppendMode.APPEND, true, true).use { cs ->
                for (a in annots) {
                    if (a is PDAnnotationLink) { keep.add(a); continue }
                    if (a is PDAnnotationPopup) continue
                    if (a.isHidden || a.isNoView) continue
                    if (a !is PDAnnotationWidget && a.appearance == null) runCatching { a.constructAppearances(doc) }
                    val ap = a.normalAppearanceStream ?: run { keep.add(a); null } ?: continue
                    val rect = a.rectangle ?: continue
                    val bbox = ap.bBox ?: continue
                    if (bbox.width <= 0f || bbox.height <= 0f) continue
                    // Map the appearance's bounding box onto the annotation rectangle (PDF 32000 §12.5.5).
                    val sx = rect.width / bbox.width; val sy = rect.height / bbox.height
                    cs.saveGraphicsState()
                    cs.transform(Matrix(sx, 0f, 0f, sy, rect.lowerLeftX - bbox.lowerLeftX * sx, rect.lowerLeftY - bbox.lowerLeftY * sy))
                    cs.drawForm(ap)
                    cs.restoreGraphicsState()
                    count++
                }
            }
            page.annotations = keep
        }
        return FlattenStats(count, fields)
    }

    data class RepairResult(val method: String, val pages: Int)

    /**
     * Rebuilds a damaged PDF: first by re-reading it with PdfBox's tolerant parser and saving a clean
     * copy; if that fails, by rendering each page that the Android viewer can still read into images.
     */
    suspend fun repair(context: Context, uri: Uri, password: String?, out: File, work: File, progress: Progress): RepairResult {
        progress.step("Reading the file…", 0.1f)
        val first = runCatching {
            PdfDocs.open(context, uri, password).use { d ->
                if (d.numberOfPages == 0) error("no pages")
                // Touch every page so broken objects show up now, not in the result.
                for (i in 0 until d.numberOfPages) { progress.step("Checking page ${i + 1}", 0.1f + 0.5f * i / d.numberOfPages); d.getPage(i).contents?.close() }
                if (d.isEncrypted) d.isAllSecurityToBeRemoved = d.currentAccessPermission.isOwnerPermission
                PdfOps.saveAtomically(d, out)
                d.numberOfPages
            }
        }
        if (first.isSuccess) {
            // Verify the rebuilt file opens cleanly.
            val ok = runCatching { PdfDocs.open(out, password).use { it.numberOfPages } }.isSuccess
            if (ok) return RepairResult("Structure rebuilt (text, images and links kept)", first.getOrThrow())
        }
        if (first.exceptionOrNull() is PasswordRequiredException) throw first.exceptionOrNull()!!
        progress.step("Rescuing pages as images…", 0.6f)
        val r = runCatching { PageRenderer.open(context, uri, work) }.getOrNull()
            ?: throw com.docdesk.app.jobs.OperationFailed("This file is too badly damaged to repair. If it was downloaded or e-mailed, ask for it again.")
        r.use {
            PDDocument().use { doc ->
                var rescued = 0
                for (i in 0 until it.pageCount) {
                    progress.step("Rescuing page ${i + 1} of ${it.pageCount}", 0.6f + 0.35f * i / it.pageCount)
                    val (w, h) = runCatching { it.pageSize(i) }.getOrNull() ?: continue
                    val bmp = runCatching { it.render(i, (w / 72f * 150).toInt(), cache = false) }.getOrNull() ?: continue
                    val p = PDPage(PDRectangle(w.toFloat(), h.toFloat())); doc.addPage(p)
                    val img = JPEGFactory.createFromImage(doc, bmp, 0.85f)
                    PDPageContentStream(doc, p).use { cs -> cs.drawImage(img, 0f, 0f, w.toFloat(), h.toFloat()) }
                    bmp.recycle(); rescued++
                }
                if (rescued == 0) throw com.docdesk.app.jobs.OperationFailed("No page could be rescued from this file.")
                PdfOps.saveAtomically(doc, out)
                return RepairResult("Pages rescued as images ($rescued of ${it.pageCount}); text is no longer selectable – run OCR to make it searchable", rescued)
            }
        }
    }
}
