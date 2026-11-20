package com.docdesk.app.pdf

import android.graphics.Bitmap
import android.graphics.Color
import com.docdesk.app.edit.AnnotationWriter
import com.docdesk.app.jobs.Progress
import com.docdesk.core.LabelTemplate
import com.docdesk.core.PageTransform
import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.PDResources
import com.tom_roush.pdfbox.pdmodel.font.PDType1Font
import com.tom_roush.pdfbox.pdmodel.graphics.form.PDFormXObject
import com.tom_roush.pdfbox.pdmodel.graphics.image.JPEGFactory
import com.tom_roush.pdfbox.pdmodel.graphics.image.LosslessFactory
import com.tom_roush.pdfbox.pdmodel.graphics.image.PDImageXObject
import com.tom_roush.pdfbox.pdmodel.graphics.state.PDExtendedGraphicsState
import com.tom_roush.pdfbox.util.Matrix

enum class Position(val label: String) {
    TOP_LEFT("Top left"), TOP_CENTER("Top centre"), TOP_RIGHT("Top right"),
    BOTTOM_LEFT("Bottom left"), BOTTOM_CENTER("Bottom centre"), BOTTOM_RIGHT("Bottom right"),
}

data class WatermarkOptions(val text: String, val sizePt: Float = 60f, val opacity: Float = 0.2f, val diagonal: Boolean = true, val color: Int = 0xFF9E9E9E.toInt())

data class HeaderFooterItem(val template: String, val position: Position)

data class NumberingOptions(val items: List<HeaderFooterItem>, val startAt: Int = 1, val sizePt: Float = 10f, val marginPt: Float = 24f, val fileName: String = "", val date: String = "")

enum class CompressLevel(val label: String, val maxSide: Int, val quality: Float) {
    LIGHT("Light – best quality", 2200, 0.85f), MEDIUM("Medium – recommended", 1600, 0.7f), STRONG("Strong – smallest file", 1100, 0.55f),
}

/** Watermarks, page numbers / headers / footers and image compression (all on new files). */
object PdfEnhance {

    /** Runs [draw] on each page in a coordinate space matching the page as displayed (y up). */
    private fun forPages(doc: PDDocument, pages: List<Int>, progress: Progress?, label: String, draw: (PDPageContentStream, Float, Float, Int) -> Unit) {
        for ((k, i) in pages.withIndex()) {
            progress?.step("$label page ${i + 1}", k.toFloat() / pages.size)
            val page = doc.getPage(i)
            val box = page.cropBox
            val (dw, dh) = PageTransform.displaySize(box.width, box.height, page.rotation)
            val t = PageTransform.displayToPdf(box.lowerLeftX, box.lowerLeftY, box.width, box.height, page.rotation)
            PDPageContentStream(doc, page, PDPageContentStream.AppendMode.APPEND, true, true).use { cs ->
                cs.saveGraphicsState()
                cs.transform(Matrix(t.a, t.b, t.c, t.d, t.e, t.f))
                draw(cs, dw, dh, i)
                cs.restoreGraphicsState()
            }
        }
    }

    private fun latin(text: String) = try { PDType1Font.HELVETICA_BOLD.encode(text); true } catch (e: Exception) { false }

    fun watermark(doc: PDDocument, pages: List<Int>, o: WatermarkOptions, progress: Progress?) {
        val useFont = latin(o.text)
        val image = if (useFont) null else AnnotationWriter.renderText(o.text, o.sizePt, o.color, bold = true).let { b -> LosslessFactory.createFromImage(doc, b).also { b.recycle() } to (b.width / 4f to b.height / 4f) }
        forPages(doc, pages, progress, "Watermarking") { cs, w, h, _ ->
            val gs = PDExtendedGraphicsState().apply { nonStrokingAlphaConstant = o.opacity; strokingAlphaConstant = o.opacity }
            cs.setGraphicsStateParameters(gs)
            val angle = if (o.diagonal) Math.atan2(h.toDouble(), w.toDouble()) else 0.0
            cs.transform(Matrix.getRotateInstance(angle, w / 2, h / 2))
            if (useFont) {
                val font = PDType1Font.HELVETICA_BOLD
                var size = o.sizePt
                val diag = if (o.diagonal) Math.hypot(w.toDouble(), h.toDouble()).toFloat() else w
                val tw = font.getStringWidth(o.text) / 1000f
                if (tw * size > diag * 0.9f) size = diag * 0.9f / tw
                cs.setNonStrokingColor(Color.red(o.color) / 255f, Color.green(o.color) / 255f, Color.blue(o.color) / 255f)
                cs.beginText(); cs.setFont(font, size); cs.newLineAtOffset(-tw * size / 2, -size * 0.35f); cs.showText(o.text); cs.endText()
            } else {
                val (img, sz) = image!!
                cs.drawImage(img, -sz.first / 2, -sz.second / 2, sz.first, sz.second)
            }
        }
    }

    fun numbering(doc: PDDocument, pages: List<Int>, o: NumberingOptions, progress: Progress?): Int {
        var asImage = 0
        val total = pages.size + o.startAt - 1
        forPages(doc, pages, progress, "Numbering") { cs, w, h, idx ->
            val n = pages.indexOf(idx) + o.startAt
            for (item in o.items) {
                val text = LabelTemplate.render(item.template, n, total, o.date, o.fileName)
                if (text.isBlank()) continue
                val top = item.position.name.startsWith("TOP")
                val y = if (top) h - o.marginPt - o.sizePt * 0.8f else o.marginPt
                if (latin(text)) {
                    val tw = PDType1Font.HELVETICA.getStringWidth(text) / 1000f * o.sizePt
                    val x = when { item.position.name.endsWith("LEFT") -> o.marginPt; item.position.name.endsWith("RIGHT") -> w - o.marginPt - tw; else -> (w - tw) / 2 }
                    cs.setNonStrokingColor(0.15f, 0.15f, 0.15f)
                    cs.beginText(); cs.setFont(PDType1Font.HELVETICA, o.sizePt); cs.newLineAtOffset(x, y); cs.showText(text); cs.endText()
                } else {
                    asImage++
                    val b = AnnotationWriter.renderText(text, o.sizePt, 0xFF262626.toInt())
                    val img = LosslessFactory.createFromImage(doc, b)
                    val iw = b.width / 4f; val ih = b.height / 4f; b.recycle()
                    val x = when { item.position.name.endsWith("LEFT") -> o.marginPt; item.position.name.endsWith("RIGHT") -> w - o.marginPt - iw; else -> (w - iw) / 2 }
                    cs.drawImage(img, x, y - ih * 0.25f, iw, ih)
                }
            }
        }
        return asImage
    }

    data class CompressStats(val imagesSeen: Int, val imagesRecompressed: Int)

    /**
     * Downscales and re-encodes large photographic images as JPEG. Images with transparency,
     * masks or very small sizes are left alone. Text and vector graphics are not touched.
     */
    fun compress(doc: PDDocument, level: CompressLevel, progress: Progress?): CompressStats {
        var seen = 0; var done = 0
        val processed = HashMap<COSName, Unit>()
        fun handle(res: PDResources?, depth: Int) {
            if (res == null || depth > 3) return
            for (name in res.xObjectNames.toList()) {
                val x = runCatching { res.getXObject(name) }.getOrNull() ?: continue
                when (x) {
                    is PDFormXObject -> handle(x.resources, depth + 1)
                    is PDImageXObject -> {
                        seen++
                        if (x.cosObject.containsKey(COSName.SMASK) || x.cosObject.containsKey(COSName.MASK) || x.isStencil) continue
                        if (x.width * x.height < 200 * 200) continue
                        if (x.bitsPerComponent == 1) continue // scanned black & white (CCITT/JBIG2) is already compact
                        val bmp: Bitmap = runCatching { x.image }.getOrNull() ?: continue
                        val m = maxOf(bmp.width, bmp.height)
                        val scaled = if (m > level.maxSide) Bitmap.createScaledBitmap(bmp, bmp.width * level.maxSide / m, bmp.height * level.maxSide / m, true) else bmp
                        val before = x.cosObject.length
                        val img = JPEGFactory.createFromImage(doc, scaled, level.quality)
                        if (img.cosObject.length < before * 0.95) { res.put(name, img); done++ }
                        if (scaled !== bmp) scaled.recycle()
                        bmp.recycle()
                    }
                }
            }
        }
        for (i in 0 until doc.numberOfPages) {
            progress?.step("Compressing images on page ${i + 1}", i.toFloat() / doc.numberOfPages)
            handle(doc.getPage(i).resources, 0)
        }
        processed.clear()
        return CompressStats(seen, done)
    }
}
