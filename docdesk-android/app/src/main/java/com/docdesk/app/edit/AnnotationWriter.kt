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
import com.tom_roush.pdfbox.pdmodel.graphics.image.LosslessFactory
import com.tom_roush.pdfbox.pdmodel.graphics.state.PDExtendedGraphicsState
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationText
import com.tom_roush.pdfbox.pdmodel.graphics.color.PDColor
import com.tom_roush.pdfbox.pdmodel.graphics.color.PDDeviceRGB
import com.tom_roush.pdfbox.util.Matrix
import java.io.File

/**
 * Writes annotations into a NEW PDF. Drawings, shapes, highlights, text boxes and images are
 * added to the page content (visible in every PDF viewer, not editable later). Sticky notes
 * are real PDF comments. The page's existing text and images are not changed.
 */
object AnnotationWriter {
    data class Stats(val textAsImage: Int)

    fun write(doc: PDDocument, annots: List<Annot>, out: File, progress: Progress?): Stats {
        var textAsImage = 0
        val byPage = annots.groupBy { it.page }
        for ((index, list) in byPage) {
            progress?.step("Applying changes to page ${index + 1}…", null)
            val page = doc.getPage(index)
            val box = page.cropBox
            val (dw, dh) = PageTransform.displaySize(box.width, box.height, page.rotation)
            val t = PageTransform.displayToPdf(box.lowerLeftX, box.lowerLeftY, box.width, box.height, page.rotation)
            fun X(u: Float) = u * dw
            fun Y(v: Float) = (1f - v) * dh
            PDPageContentStream(doc, page, PDPageContentStream.AppendMode.APPEND, true, true).use { cs ->
                cs.saveGraphicsState()
                cs.transform(Matrix(t.a, t.b, t.c, t.d, t.e, t.f))
                for (a in list.filter { it !is Annot.Note }) {
                    cs.saveGraphicsState()
                    when (a) {
                        is Annot.Box -> {
                            val x = X(a.rect.left); val yTop = Y(a.rect.top); val yBot = Y(a.rect.bottom); val w = a.rect.width * dw
                            setColor(cs, a.color)
                            when (a.kind) {
                                Annot.BoxKind.HIGHLIGHT -> { alpha(cs, 0.35f); cs.addRect(x, yBot, w, yTop - yBot); cs.fill() }
                                Annot.BoxKind.WHITEOUT -> { cs.setNonStrokingColor(1f, 1f, 1f); cs.addRect(x, yBot, w, yTop - yBot); cs.fill() }
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
                                val p1x = x2 - len * Math.cos(ang - 0.45).toFloat(); val p1y = y2 - len * Math.sin(ang - 0.45).toFloat()
                                val p2x = x2 - len * Math.cos(ang + 0.45).toFloat(); val p2y = y2 - len * Math.sin(ang + 0.45).toFloat()
                                cs.moveTo(x2, y2); cs.lineTo(p1x, p1y); cs.lineTo(p2x, p2y); cs.closePath(); cs.fill()
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
                            if (encodable(a.text)) {
                                setColor(cs, a.color)
                                val lead = a.sizePt * 1.2f
                                a.text.lines().forEachIndexed { i, line ->
                                    cs.beginText()
                                    cs.setFont(PDType1Font.HELVETICA, a.sizePt)
                                    cs.newLineAtOffset(X(a.origin.x), Y(a.origin.y) - a.sizePt - i * lead)
                                    cs.showText(line)
                                    cs.endText()
                                }
                            } else {
                                // Hindi and other scripts: shape with Android's text engine and embed as an image.
                                textAsImage++
                                val bmp = renderText(a.text, a.sizePt, a.color)
                                val img = LosslessFactory.createFromImage(doc, bmp)
                                val w = bmp.width / 4f; val h = bmp.height / 4f
                                cs.drawImage(img, X(a.origin.x), Y(a.origin.y) - h, w, h)
                                bmp.recycle()
                            }
                        }
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
            // Sticky notes as standard PDF text annotations (comments).
            for (n in list.filterIsInstance<Annot.Note>()) {
                val (px, py) = t.apply(X(n.at.x), Y(n.at.y))
                val ann = PDAnnotationText()
                ann.contents = n.text
                ann.name = PDAnnotationText.NAME_COMMENT
                ann.rectangle = PDRectangle(px, py - 20f, 20f, 20f)
                ann.color = PDColor(floatArrayOf(Color.red(n.color) / 255f, Color.green(n.color) / 255f, Color.blue(n.color) / 255f), PDDeviceRGB.INSTANCE)
                ann.titlePopup = "DocDesk"
                page.annotations.add(ann)
            }
        }
        progress?.step("Saving…", 0.95f)
        PdfOps.saveAtomically(doc, out)
        return Stats(textAsImage)
    }

    private fun encodable(text: String) = try { text.lines().forEach { PDType1Font.HELVETICA.encode(it) }; true } catch (e: Exception) { false }

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
    fun renderText(text: String, sizePt: Float, color: Int): Bitmap {
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = sizePt * 4; this.color = color }
        val width = text.lines().maxOf { paint.measureText(it) }.toInt().coerceAtLeast(4) + 8
        val layout = StaticLayout.Builder.obtain(text, 0, text.length, paint, width).setIncludePad(false).build()
        val bmp = Bitmap.createBitmap(width, layout.height.coerceAtLeast(4), Bitmap.Config.ARGB_8888)
        layout.draw(Canvas(bmp))
        return bmp
    }
}
