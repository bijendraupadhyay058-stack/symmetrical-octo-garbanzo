package com.docdesk.app.edit

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.text.StaticLayout
import android.text.TextPaint
import com.docdesk.app.jobs.Progress
import com.docdesk.app.pdf.PdfOps
import com.docdesk.core.PageTransform
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.font.PDType1Font
import com.tom_roush.pdfbox.pdmodel.graphics.color.PDColor
import com.tom_roush.pdfbox.pdmodel.graphics.color.PDDeviceRGB
import com.tom_roush.pdfbox.pdmodel.graphics.image.LosslessFactory
import com.tom_roush.pdfbox.pdmodel.graphics.state.PDExtendedGraphicsState
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationLine
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationSquareCircle
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationText
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationTextMarkup
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDBorderStyleDictionary
import com.tom_roush.pdfbox.util.Matrix
import java.io.File

/**
 * Writes annotations into a NEW PDF.
 *
 * With [editable] = true, highlights, underlines, strikethroughs, rectangles, ellipses, lines
 * and arrows become standard PDF annotations (with generated appearances) that Adobe Acrobat
 * and other readers can select, recolour, comment on or delete. Otherwise – and always for
 * freehand ink, text boxes, stamps, images, signatures, white-out and redaction boxes – the
 * drawing is added to the page content. Sticky notes are always real PDF comments.
 * The page's existing text and images are never changed here (see [RedactionApplier]).
 */
object AnnotationWriter {
    data class Stats(val textAsImage: Int, val editableAnnotations: Int)

    private val EDITABLE_KINDS = setOf(Annot.BoxKind.HIGHLIGHT, Annot.BoxKind.UNDERLINE, Annot.BoxKind.STRIKE, Annot.BoxKind.RECT, Annot.BoxKind.ELLIPSE)

    /** Applies [annots] to [doc] in memory; the caller saves. */
    fun apply(doc: PDDocument, annots: List<Annot>, editable: Boolean, progress: Progress?): Stats {
        var textAsImage = 0
        var editableCount = 0
        for ((index, list) in annots.groupBy { it.page }) {
            progress?.step("Applying changes to page ${index + 1}…", null)
            val page = doc.getPage(index)
            val box = page.cropBox
            val (dw, dh) = PageTransform.displaySize(box.width, box.height, page.rotation)
            val t = PageTransform.displayToPdf(box.lowerLeftX, box.lowerLeftY, box.width, box.height, page.rotation)
            fun X(u: Float) = u * dw
            fun Y(v: Float) = (1f - v) * dh
            fun pdf(u: Float, v: Float) = t.apply(X(u), Y(v))
            fun isEditable(a: Annot) = editable && (a is Annot.Line || (a is Annot.Box && a.kind in EDITABLE_KINDS))

            PDPageContentStream(doc, page, PDPageContentStream.AppendMode.APPEND, true, true).use { cs ->
                cs.saveGraphicsState()
                cs.transform(Matrix(t.a, t.b, t.c, t.d, t.e, t.f))
                for (a in list.filter { it !is Annot.Note && !isEditable(it) }) {
                    cs.saveGraphicsState()
                    when (a) {
                        is Annot.Box -> {
                            val x = X(a.rect.left); val yTop = Y(a.rect.top); val yBot = Y(a.rect.bottom); val w = a.rect.width * dw
                            setColor(cs, a.color)
                            when (a.kind) {
                                Annot.BoxKind.HIGHLIGHT -> { alpha(cs, 0.35f); cs.addRect(x, yBot, w, yTop - yBot); cs.fill() }
                                Annot.BoxKind.WHITEOUT -> { cs.setNonStrokingColor(1f, 1f, 1f); cs.addRect(x, yBot, w, yTop - yBot); cs.fill() }
                                Annot.BoxKind.REDACT -> { cs.setNonStrokingColor(0f, 0f, 0f); cs.addRect(x, yBot, w, yTop - yBot); cs.fill() }
                                Annot.BoxKind.UNDERLINE -> { cs.setLineWidth(a.strokePt); cs.moveTo(x, yBot); cs.lineTo(x + w, yBot); cs.stroke() }
                                Annot.BoxKind.STRIKE -> { val m = (yTop + yBot) / 2; cs.setLineWidth(a.strokePt); cs.moveTo(x, m); cs.lineTo(x + w, m); cs.stroke() }
                                Annot.BoxKind.RECT -> { cs.setLineWidth(a.strokePt); cs.addRect(x, yBot, w, yTop - yBot); cs.stroke() }
                                Annot.BoxKind.ELLIPSE -> { cs.setLineWidth(a.strokePt); ellipse(cs, x, yBot, w, yTop - yBot); cs.stroke() }
                            }
                        }
                        is Annot.Line -> {
                            setColor(cs, a.color); cs.setLineWidth(a.strokePt)
                            val x1 = X(a.a.x); val y1 = Y(a.a.y); val x2 = X(a.b.x); val y2 = Y(a.b.y)
                            cs.moveTo(x1, y1); cs.lineTo(x2, y2); cs.stroke()
                            if (a.arrow) {
                                val ang = Math.atan2((y2 - y1).toDouble(), (x2 - x1).toDouble())
                                val len = 6f + a.strokePt * 3f
                                cs.moveTo(x2, y2)
                                cs.lineTo(x2 - len * Math.cos(ang - 0.45).toFloat(), y2 - len * Math.sin(ang - 0.45).toFloat())
                                cs.lineTo(x2 - len * Math.cos(ang + 0.45).toFloat(), y2 - len * Math.sin(ang + 0.45).toFloat())
                                cs.closePath(); cs.fill()
                            }
                        }
                        is Annot.Ink -> if (a.points.size > 1) {
                            setColor(cs, a.color); cs.setLineWidth(a.strokePt)
                            cs.setLineCapStyle(1); cs.setLineJoinStyle(1)
                            cs.moveTo(X(a.points[0].x), Y(a.points[0].y))
                            for (p in a.points.drop(1)) cs.lineTo(X(p.x), Y(p.y))
                            cs.stroke()
                        }
                        is Annot.TextBox -> {
                            val font = if (a.bold) PDType1Font.HELVETICA_BOLD else PDType1Font.HELVETICA
                            if (encodable(font, a.text)) {
                                setColor(cs, a.color)
                                val lead = a.sizePt * 1.2f
                                a.text.lines().forEachIndexed { i, line ->
                                    cs.beginText(); cs.setFont(font, a.sizePt)
                                    cs.newLineAtOffset(X(a.origin.x), Y(a.origin.y) - a.sizePt - i * lead)
                                    cs.showText(line); cs.endText()
                                }
                            } else {
                                // Hindi and other scripts: shape with Android's text engine and embed as an image.
                                textAsImage++
                                val bmp = renderText(a.text, a.sizePt, a.color, a.bold)
                                val img = LosslessFactory.createFromImage(doc, bmp)
                                val w = bmp.width / 4f; val h = bmp.height / 4f
                                cs.drawImage(img, X(a.origin.x), Y(a.origin.y) - h, w, h)
                                bmp.recycle()
                            }
                        }
                        is Annot.Stamp -> drawStamp(cs, a, X(a.rect.left), Y(a.rect.bottom), a.rect.width * dw, a.rect.height * dh)
                        is Annot.Picture -> {
                            val bmp = BitmapFactory.decodeFile(a.path) ?: continue
                            val img = LosslessFactory.createFromImage(doc, bmp)
                            cs.drawImage(img, X(a.rect.left), Y(a.rect.bottom), a.rect.width * dw, a.rect.height * dh)
                            bmp.recycle()
                        }
                        is Annot.Note -> Unit
                    }
                    cs.restoreGraphicsState()
                }
                cs.restoreGraphicsState()
            }

            // Real, editable PDF annotations.
            for (a in list.filter { isEditable(it) }) {
                val ann = when (a) {
                    is Annot.Box -> {
                        val tl = pdf(a.rect.left, a.rect.top); val tr = pdf(a.rect.right, a.rect.top)
                        val bl = pdf(a.rect.left, a.rect.bottom); val br = pdf(a.rect.right, a.rect.bottom)
                        val xs = listOf(tl.first, tr.first, bl.first, br.first); val ys = listOf(tl.second, tr.second, bl.second, br.second)
                        val rect = PDRectangle(xs.min(), ys.min(), xs.max() - xs.min(), ys.max() - ys.min())
                        when (a.kind) {
                            Annot.BoxKind.HIGHLIGHT, Annot.BoxKind.UNDERLINE, Annot.BoxKind.STRIKE -> PDAnnotationTextMarkup(
                                when (a.kind) { Annot.BoxKind.HIGHLIGHT -> PDAnnotationTextMarkup.SUB_TYPE_HIGHLIGHT; Annot.BoxKind.UNDERLINE -> PDAnnotationTextMarkup.SUB_TYPE_UNDERLINE; else -> PDAnnotationTextMarkup.SUB_TYPE_STRIKEOUT },
                            ).apply {
                                rectangle = rect
                                // Quad order used by Acrobat: top-left, top-right, bottom-left, bottom-right.
                                quadPoints = floatArrayOf(tl.first, tl.second, tr.first, tr.second, bl.first, bl.second, br.first, br.second)
                                if (a.kind == Annot.BoxKind.HIGHLIGHT) constantOpacity = 0.5f
                            }
                            else -> PDAnnotationSquareCircle(if (a.kind == Annot.BoxKind.ELLIPSE) PDAnnotationSquareCircle.SUB_TYPE_CIRCLE else PDAnnotationSquareCircle.SUB_TYPE_SQUARE).apply {
                                val pad = a.strokePt
                                rectangle = PDRectangle(rect.lowerLeftX - pad, rect.lowerLeftY - pad, rect.width + 2 * pad, rect.height + 2 * pad)
                                borderStyle = PDBorderStyleDictionary().apply { width = a.strokePt }
                            }
                        }
                    }
                    is Annot.Line -> {
                        val (x1, y1) = pdf(a.a.x, a.a.y); val (x2, y2) = pdf(a.b.x, a.b.y)
                        val pad = 8f + a.strokePt * 3
                        PDAnnotationLine().apply {
                            line = floatArrayOf(x1, y1, x2, y2)
                            rectangle = PDRectangle(minOf(x1, x2) - pad, minOf(y1, y2) - pad, kotlin.math.abs(x2 - x1) + 2 * pad, kotlin.math.abs(y2 - y1) + 2 * pad)
                            borderStyle = PDBorderStyleDictionary().apply { width = a.strokePt }
                            if (a.arrow) { endPointEndingStyle = "ClosedArrow"; interiorColor = rgb(a.color) }
                        }
                    }
                    else -> continue
                }
                ann.color = rgb(a.color)
                ann.titlePopup = "DocDesk"
                ann.constructAppearances(doc)
                page.annotations.add(ann)
                editableCount++
            }

            // Sticky notes as standard PDF text annotations (comments).
            for (n in list.filterIsInstance<Annot.Note>()) {
                val (px, py) = pdf(n.at.x, n.at.y)
                val ann = PDAnnotationText()
                ann.contents = n.text
                ann.name = PDAnnotationText.NAME_COMMENT
                ann.rectangle = PDRectangle(px, py - 20f, 20f, 20f)
                ann.color = rgb(n.color)
                ann.titlePopup = "DocDesk"
                page.annotations.add(ann)
            }
        }
        return Stats(textAsImage, editableCount)
    }

    /** Convenience: apply and save to [out]. */
    fun write(doc: PDDocument, annots: List<Annot>, out: File, progress: Progress?, editable: Boolean = false): Stats {
        val stats = apply(doc, annots, editable, progress)
        progress?.step("Saving…", 0.95f)
        PdfOps.saveAtomically(doc, out)
        return stats
    }

    private fun rgb(c: Int) = PDColor(floatArrayOf(Color.red(c) / 255f, Color.green(c) / 255f, Color.blue(c) / 255f), PDDeviceRGB.INSTANCE)

    private fun drawStamp(cs: PDPageContentStream, s: Annot.Stamp, x: Float, y: Float, w: Float, h: Float) {
        setColor(cs, s.color)
        alpha(cs, 0.9f)
        val lw = (h * 0.06f).coerceIn(1f, 4f)
        cs.setLineWidth(lw)
        cs.addRect(x + lw, y + lw, w - 2 * lw, h - 2 * lw); cs.stroke()
        cs.setLineWidth(lw / 2)
        cs.addRect(x + lw * 2.5f, y + lw * 2.5f, w - 5 * lw, h - 5 * lw); cs.stroke()
        val font = PDType1Font.HELVETICA_BOLD
        val label = s.label.filter { it.code < 256 }.ifEmpty { "STAMP" }
        val hasDate = !s.dateText.isNullOrBlank()
        var size = h * (if (hasDate) 0.42f else 0.55f)
        val maxW = w * 0.85f
        val tw = font.getStringWidth(label) / 1000f
        if (tw * size > maxW) size = maxW / tw
        val labelW = tw * size
        val labelY = if (hasDate) y + h * 0.42f else y + (h - size * 0.72f) / 2
        cs.beginText(); cs.setFont(font, size); cs.newLineAtOffset(x + (w - labelW) / 2, labelY); cs.showText(label); cs.endText()
        if (hasDate) {
            val d = s.dateText!!.filter { it.code < 256 }
            val ds = h * 0.2f
            val dw = PDType1Font.HELVETICA.getStringWidth(d) / 1000f * ds
            cs.beginText(); cs.setFont(PDType1Font.HELVETICA, ds); cs.newLineAtOffset(x + (w - dw) / 2, y + h * 0.17f); cs.showText(d); cs.endText()
        }
    }

    private fun encodable(font: PDType1Font, text: String) = try { text.lines().forEach { font.encode(it) }; true } catch (e: Exception) { false }

    private fun setColor(cs: PDPageContentStream, c: Int) {
        val r = Color.red(c) / 255f; val g = Color.green(c) / 255f; val b = Color.blue(c) / 255f
        cs.setStrokingColor(r, g, b); cs.setNonStrokingColor(r, g, b)
    }

    private fun alpha(cs: PDPageContentStream, a: Float) {
        val gs = PDExtendedGraphicsState(); gs.nonStrokingAlphaConstant = a; gs.strokingAlphaConstant = a
        cs.setGraphicsStateParameters(gs)
    }

    private fun ellipse(cs: PDPageContentStream, x: Float, y: Float, w: Float, h: Float) {
        val k = 0.5523f; val rx = w / 2; val ry = h / 2; val cx = x + rx; val cy = y + ry
        cs.moveTo(cx + rx, cy)
        cs.curveTo(cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry)
        cs.curveTo(cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy)
        cs.curveTo(cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry)
        cs.curveTo(cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy)
        cs.closePath()
    }

    /** Renders text at 4× for sharpness; caller draws it at 1/4 size in points. */
    fun renderText(text: String, sizePt: Float, color: Int, bold: Boolean = false): Bitmap {
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = sizePt * 4; this.color = color; isFakeBoldText = bold }
        val width = text.lines().maxOf { paint.measureText(it) }.toInt().coerceAtLeast(4) + 8
        val layout = StaticLayout.Builder.obtain(text, 0, text.length, paint, width).setIncludePad(false).build()
        val bmp = Bitmap.createBitmap(width, layout.height.coerceAtLeast(4), Bitmap.Config.ARGB_8888)
        layout.draw(Canvas(bmp))
        return bmp
    }
}
