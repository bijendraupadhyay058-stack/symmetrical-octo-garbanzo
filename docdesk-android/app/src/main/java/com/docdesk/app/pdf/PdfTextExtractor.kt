package com.docdesk.app.pdf

import android.graphics.Bitmap
import com.docdesk.core.PageImage
import com.docdesk.core.PageText
import com.docdesk.core.TextSource
import com.docdesk.core.TextWord
import com.tom_roush.pdfbox.contentstream.PDFStreamEngine
import com.tom_roush.pdfbox.contentstream.operator.DrawObject
import com.tom_roush.pdfbox.contentstream.operator.Operator
import com.tom_roush.pdfbox.contentstream.operator.state.Concatenate
import com.tom_roush.pdfbox.contentstream.operator.state.Restore
import com.tom_roush.pdfbox.contentstream.operator.state.Save
import com.tom_roush.pdfbox.contentstream.operator.state.SetGraphicsStateParameters
import com.tom_roush.pdfbox.contentstream.operator.state.SetMatrix
import com.tom_roush.pdfbox.cos.COSBase
import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.graphics.image.PDImageXObject
import com.tom_roush.pdfbox.text.PDFTextStripper
import com.tom_roush.pdfbox.text.TextPosition
import java.io.ByteArrayOutputStream

/** Extracts positioned words (with font size/bold/italic) from the PDF text layer. */
object PdfTextExtractor {

    fun extract(doc: PDDocument, pageIndex: Int): PageText {
        val page = doc.getPage(pageIndex)
        val words = mutableListOf<TextWord>()
        val stripper = object : PDFTextStripper() {
            override fun writeString(text: String, textPositions: MutableList<TextPosition>) {
                // Split the run into words at spaces and at gaps wider than a space.
                var cur = mutableListOf<TextPosition>()
                fun flush() {
                    if (cur.isEmpty()) return
                    val t = cur.joinToString("") { it.unicode ?: "" }.trim()
                    if (t.isNotEmpty()) {
                        val x = cur.minOf { it.xDirAdj }
                        val right = cur.maxOf { it.xDirAdj + it.widthDirAdj }
                        val h = cur.maxOf { it.heightDir }.coerceAtLeast(1f)
                        val size = cur.map { it.fontSizeInPt }.maxOrNull()?.takeIf { it > 0 } ?: h
                        val top = cur.minOf { it.yDirAdj } - h
                        val fontName = cur.first().font?.name?.lowercase() ?: ""
                        val desc = cur.first().font?.fontDescriptor
                        val bold = fontName.contains("bold") || fontName.contains("black") || fontName.contains("heavy") || fontName.contains("semibold") || (desc?.isForceBold ?: false) || ((desc?.fontWeight ?: 0f) >= 600f)
                        val italic = fontName.contains("italic") || fontName.contains("oblique") || (desc?.isItalic ?: false)
                        words.add(TextWord(t, x, top, right - x, h * 1.2f, size, bold, italic))
                    }
                    cur = mutableListOf()
                }
                for (tp in textPositions) {
                    val u = tp.unicode ?: continue
                    if (u.isBlank()) { flush(); continue }
                    val prev = cur.lastOrNull()
                    if (prev != null) {
                        val gap = tp.xDirAdj - (prev.xDirAdj + prev.widthDirAdj)
                        val space = (prev.widthOfSpace.takeIf { it > 0 } ?: prev.widthDirAdj).coerceAtLeast(0.5f)
                        if (gap > space * 0.6f || kotlin.math.abs(tp.yDirAdj - prev.yDirAdj) > prev.heightDir * 0.5f) flush()
                    }
                    cur.add(tp)
                }
                flush()
            }
        }
        stripper.sortByPosition = true
        stripper.startPage = pageIndex + 1
        stripper.endPage = pageIndex + 1
        stripper.getText(doc)
        val box = page.cropBox
        val rot = page.rotation % 180 != 0
        val w = if (rot) box.height else box.width
        val h = if (rot) box.width else box.height
        return PageText(pageIndex, w, h, words, if (words.isEmpty()) TextSource.NONE else TextSource.PDF_TEXT)
    }

    /** Images drawn on a page with their displayed position (for PDF → Word). Unrotated pages only. */
    fun images(doc: PDDocument, pageIndex: Int, maxImages: Int = 20): List<PageImage> {
        val page = doc.getPage(pageIndex)
        val out = mutableListOf<PageImage>()
        val pageH = page.cropBox.height
        val engine = object : PDFStreamEngine() {
            init {
                addOperator(Concatenate()); addOperator(DrawObject()); addOperator(SetGraphicsStateParameters())
                addOperator(Save()); addOperator(Restore()); addOperator(SetMatrix())
            }

            override fun processOperator(operator: Operator, operands: MutableList<COSBase>) {
                if (operator.name == "Do" && out.size < maxImages) {
                    val name = operands.firstOrNull() as? COSName
                    val xobj = name?.let { runCatching { resources.getXObject(it) }.getOrNull() }
                    if (xobj is PDImageXObject) {
                        val ctm = graphicsState.currentTransformationMatrix
                        val w = ctm.scalingFactorX; val h = ctm.scalingFactorY
                        if (w > 20 && h > 20) {
                            runCatching {
                                val bmp: Bitmap = xobj.image
                                val scaled = scaleDown(bmp, 1600)
                                val bos = ByteArrayOutputStream()
                                val png = xobj.suffix == "png" || bmp.hasAlpha()
                                scaled.compress(if (png) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, 88, bos)
                                out.add(PageImage(bos.toByteArray(), if (png) "png" else "jpeg", ctm.translateX - page.cropBox.lowerLeftX, pageH - (ctm.translateY - page.cropBox.lowerLeftY) - h, w, h))
                                if (scaled !== bmp) scaled.recycle()
                            }
                        }
                        return
                    }
                }
                super.processOperator(operator, operands)
            }
        }
        if (page.rotation % 360 != 0) return emptyList()
        runCatching { engine.processPage(page) }
        return out
    }

    private fun scaleDown(b: Bitmap, max: Int): Bitmap {
        val m = maxOf(b.width, b.height)
        if (m <= max) return b
        val s = max.toFloat() / m
        return Bitmap.createScaledBitmap(b, (b.width * s).toInt().coerceAtLeast(1), (b.height * s).toInt().coerceAtLeast(1), true)
    }

    /** Plain text of a page (for search / statement totals). */
    fun plainText(doc: PDDocument, pageIndex: Int): String {
        val s = PDFTextStripper().apply { sortByPosition = true; startPage = pageIndex + 1; endPage = pageIndex + 1 }
        return runCatching { s.getText(doc) }.getOrDefault("")
    }

    @Suppress("unused") private fun PDPage.isRotated() = rotation % 180 != 0
}
