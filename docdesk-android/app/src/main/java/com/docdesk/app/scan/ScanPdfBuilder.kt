package com.docdesk.app.scan

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Matrix
import android.graphics.Paint
import com.docdesk.app.jobs.Progress
import com.docdesk.app.pdf.PdfOps
import com.docdesk.core.TextWord
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.font.PDType1Font
import com.tom_roush.pdfbox.pdmodel.graphics.image.JPEGFactory
import com.tom_roush.pdfbox.pdmodel.graphics.state.RenderingMode
import java.io.File

enum class ColorMode(val label: String) { COLOR("Colour"), GRAYSCALE("Grayscale"), BLACK_WHITE("Black & white") }

data class PageAdjust(val rotation: Int = 0, val brightness: Float = 0f, val contrast: Float = 1f, val mode: ColorMode = ColorMode.COLOR)

object ImageProcessor {
    /** Applies rotation, brightness (−100..100), contrast (0.5..2) and colour mode. */
    fun apply(src: Bitmap, a: PageAdjust): Bitmap {
        val m = Matrix().apply { postRotate(a.rotation.toFloat()) }
        val rotated = if (a.rotation % 360 != 0) Bitmap.createBitmap(src, 0, 0, src.width, src.height, m, true) else src
        val out = Bitmap.createBitmap(rotated.width, rotated.height, Bitmap.Config.ARGB_8888)
        val cm = ColorMatrix()
        if (a.mode != ColorMode.COLOR) cm.setSaturation(0f)
        val c = a.contrast; val t = (1f - c) * 128f + a.brightness
        cm.postConcat(ColorMatrix(floatArrayOf(c, 0f, 0f, 0f, t, 0f, c, 0f, 0f, t, 0f, 0f, c, 0f, t, 0f, 0f, 0f, 1f, 0f)))
        Canvas(out).drawBitmap(rotated, 0f, 0f, Paint(Paint.FILTER_BITMAP_FLAG).apply { colorFilter = ColorMatrixColorFilter(cm) })
        if (rotated !== src) rotated.recycle()
        if (a.mode == ColorMode.BLACK_WHITE) threshold(out)
        return out
    }

    /** Global mean threshold: simple and predictable for printed documents. */
    private fun threshold(b: Bitmap) {
        val w = b.width; val h = b.height
        val row = IntArray(w)
        var sum = 0L
        for (y in 0 until h step 4) { b.getPixels(row, 0, w, 0, y, w, 1); for (x in 0 until w step 4) sum += row[x] and 0xFF }
        val samples = ((h + 3) / 4).toLong() * ((w + 3) / 4)
        val level = ((sum / samples.coerceAtLeast(1)) * 0.85).toInt()
        for (y in 0 until h) {
            b.getPixels(row, 0, w, 0, y, w, 1)
            for (x in 0 until w) row[x] = if ((row[x] and 0xFF) < level) 0xFF000000.toInt() else 0xFFFFFFFF.toInt()
            b.setPixels(row, 0, w, 0, y, w, 1)
        }
    }
}

/** Builds a PDF from scanned page images, optionally with an invisible OCR text layer. */
object ScanPdfBuilder {
    data class Stats(val pages: Int, val wordsSkipped: Int)

    /**
     * [pages] supplies one bitmap at a time to limit memory use. [ocrWords] (optional) gives
     * recognised words in image-pixel coordinates for each page.
     */
    suspend fun build(count: Int, page: suspend (Int) -> Bitmap, ocrWords: (suspend (Int, Bitmap) -> List<TextWord>)?, out: File, progress: Progress, paperWidthPt: Float = PDRectangle.A4.width): Stats {
        var skipped = 0
        PDDocument().use { doc ->
            for (i in 0 until count) {
                progress.step("Adding page ${i + 1} of $count", i.toFloat() / count)
                val bmp = page(i)
                // Page width = paper width (A4 by default); height follows the image's aspect ratio.
                val pw = paperWidthPt
                val ph = pw * bmp.height / bmp.width
                val p = PDPage(PDRectangle(pw, ph))
                doc.addPage(p)
                val img = JPEGFactory.createFromImage(doc, bmp, 0.82f)
                val words = ocrWords?.invoke(i, bmp).orEmpty()
                PDPageContentStream(doc, p).use { cs ->
                    cs.drawImage(img, 0f, 0f, pw, ph)
                    if (words.isNotEmpty()) {
                        val s = pw / bmp.width
                        val font = PDType1Font.HELVETICA
                        for (w in words) {
                            val text = w.text
                            val ok = try { font.encode(text); true } catch (e: Exception) { false }
                            if (!ok) { skipped++; continue }
                            val h = w.height * s
                            val size = (h * 0.9f).coerceIn(2f, 200f)
                            val natural = font.getStringWidth(text) / 1000f * size
                            if (natural <= 0f) continue
                            cs.beginText()
                            cs.setFont(font, size)
                            cs.setRenderingMode(RenderingMode.NEITHER)
                            cs.setHorizontalScaling((w.width * s / natural * 100f).coerceIn(10f, 500f))
                            cs.newLineAtOffset(w.x * s, ph - (w.y + w.height) * s + h * 0.15f)
                            cs.showText(text)
                            cs.endText()
                        }
                    }
                }
                bmp.recycle()
            }
            progress.step("Saving PDF…", 0.97f)
            doc.documentInformation.producer = "DocDesk"
            PdfOps.saveAtomically(doc, out)
        }
        return Stats(count, skipped)
    }
}
