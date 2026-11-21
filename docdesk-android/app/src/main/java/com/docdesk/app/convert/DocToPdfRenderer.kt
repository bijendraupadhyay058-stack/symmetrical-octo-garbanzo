package com.docdesk.app.convert

import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.Layout
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.text.style.LeadingMarginSpan
import android.text.style.StrikethroughSpan
import android.text.style.StyleSpan
import android.text.style.TypefaceSpan
import android.text.style.UnderlineSpan
import com.docdesk.app.jobs.Progress
import com.docdesk.core.Align
import com.docdesk.core.DocBlock
import com.docdesk.core.DocDocument
import java.io.File

/**
 * Lays out a [DocDocument] onto PDF pages with Android's text engine (StaticLayout), which
 * shapes complex scripts such as Devanagari correctly using the phone's system fonts.
 * This is a phone-side approximation of Word's layout, not a pixel-exact copy: line breaks
 * and page breaks can differ from Word, especially with uncommon fonts.
 */
class DocToPdfRenderer(private val doc: DocDocument, private val pageNumbers: Boolean) {
    var clippedItems = 0; private set
    var skippedImages = 0; private set
    private val page = doc.page
    private val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; textSize = doc.defaultFontSizePt }

    private inner class Sink(val pdf: PdfDocument?, val totalPages: Int) {
        var pageNo = 0
        var canvas: Canvas? = null
        private var current: PdfDocument.Page? = null
        var y = 0f
        val top = page.marginTopPt
        val bottom = page.heightPt - page.marginBottomPt
        val left = page.marginLeftPt
        val width = page.contentWidth

        fun newPage() {
            finish()
            pageNo++
            y = top
            if (pdf != null) {
                val p = pdf.startPage(PdfDocument.PageInfo.Builder(page.widthPt.toInt(), page.heightPt.toInt(), pageNo).create())
                current = p; canvas = p.canvas
                drawHeaderFooter(p.canvas, pageNo, totalPages)
            }
        }

        fun finish() { current?.let { pdf?.finishPage(it) }; current = null; canvas = null }
        val remaining get() = bottom - y
    }

    /** Renders to [out]; returns the page count. */
    fun render(out: File, progress: Progress?): Int {
        // Pass 1 counts pages (for "Page X of Y"); pass 2 draws.
        val total = layoutAll(Sink(null, 0), null)
        val pdf = PdfDocument()
        try {
            clippedItems = 0; skippedImages = 0
            layoutAll(Sink(pdf, total), progress)
            val tmp = File(out.parentFile, out.name + ".part")
            tmp.outputStream().buffered().use { pdf.writeTo(it) }
            if (!tmp.renameTo(out)) throw java.io.IOException("Could not save the PDF")
        } finally { pdf.close() }
        return total
    }

    private fun layoutAll(sink: Sink, progress: Progress?): Int {
        sink.newPage()
        doc.blocks.forEachIndexed { i, b ->
            if (i % 20 == 0) progress?.step("Laying out page ${sink.pageNo}…", i.toFloat() / doc.blocks.size)
            block(b, sink, sink.left, sink.width)
        }
        sink.finish()
        return sink.pageNo
    }

    private fun block(b: DocBlock, s: Sink, x: Float, width: Float) {
        when (b) {
            is DocBlock.PageBreak -> s.newPage()
            is DocBlock.Paragraph -> paragraph(b, s, x, width)
            is DocBlock.Image -> image(b, s, x, width)
            is DocBlock.Table -> table(b, s, x, width)
        }
    }

    private fun headingSize(level: Int): Float? = when (level) { -1 -> 26f; 1 -> 18f; 2 -> 15f; 3 -> 13.5f; 4 -> 12.5f; 5, 6 -> 12f; else -> null }

    fun spanned(p: DocBlock.Paragraph): CharSequence {
        val sb = SpannableStringBuilder()
        p.listLabel?.let { sb.append(it).append(if (it.length <= 2) "  " else " ") }
        val hSize = headingSize(p.headingLevel)
        for (r in p.runs) {
            val start = sb.length
            sb.append(r.text.replace('\t', ' ').let { if (it.contains("    ")) it else it })
            val end = sb.length
            if (start == end) continue
            val bold = r.bold || p.headingLevel != 0
            if (bold && r.italic) sb.setSpan(StyleSpan(Typeface.BOLD_ITALIC), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            else if (bold) sb.setSpan(StyleSpan(Typeface.BOLD), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            else if (r.italic) sb.setSpan(StyleSpan(Typeface.ITALIC), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            if (r.underline) sb.setSpan(UnderlineSpan(), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            if (r.strike) sb.setSpan(StrikethroughSpan(), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            (r.sizePt ?: hSize)?.let { sb.setSpan(AbsoluteSizeSpan(it.toInt().coerceAtLeast(4)), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE) }
            r.color?.let { c -> runCatching { Color.parseColor("#$c") }.getOrNull()?.let { sb.setSpan(ForegroundColorSpan(it), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE) } }
            r.fontName?.let { f ->
                val family = when {
                    f.contains("Courier", true) || f.contains("Mono", true) || f.contains("Consolas", true) -> "monospace"
                    f.contains("Times", true) || f.contains("Georgia", true) || f.contains("Cambria", true) || f.contains("Garamond", true) || f.contains("Book", true) -> "serif"
                    else -> null
                }
                family?.let { sb.setSpan(TypefaceSpan(it), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE) }
            }
        }
        if (sb.isEmpty()) sb.append(" ")
        if (p.firstLineIndentPt != 0f || p.listLabel != null) {
            val first = if (p.listLabel != null) 0 else p.firstLineIndentPt.coerceAtLeast(0f).toInt()
            val rest = if (p.listLabel != null) 14 else (-p.firstLineIndentPt).coerceAtLeast(0f).toInt()
            sb.setSpan(LeadingMarginSpan.Standard(first, rest), 0, sb.length, Spanned.SPAN_INCLUSIVE_INCLUSIVE)
        }
        return sb
    }

    fun layoutOf(p: DocBlock.Paragraph, width: Float): StaticLayout {
        val text = spanned(p)
        val indent = p.indentLeftPt + if (p.listLabel != null) 18f * (p.listLevel + 1) else 0f
        val w = (width - indent).toInt().coerceAtLeast(20)
        val align = when (p.align) { Align.CENTER -> Layout.Alignment.ALIGN_CENTER; Align.RIGHT -> Layout.Alignment.ALIGN_OPPOSITE; else -> Layout.Alignment.ALIGN_NORMAL }
        val b = StaticLayout.Builder.obtain(text, 0, text.length, paint, w).setAlignment(align).setLineSpacing(0f, 1.12f).setIncludePad(false)
        // Layout.JUSTIFICATION_MODE_INTER_WORD (API 26) has the same value as LineBreaker's (API 29).
        @android.annotation.SuppressLint("WrongConstant")
        if (p.align == Align.JUSTIFY) b.setJustificationMode(Layout.JUSTIFICATION_MODE_INTER_WORD)
        return b.build()
    }

    private fun paragraph(p: DocBlock.Paragraph, s: Sink, x: Float, width: Float) {
        val layout = layoutOf(p, width)
        val indent = p.indentLeftPt + if (p.listLabel != null) 18f * (p.listLevel + 1) else 0f
        s.y += p.spaceBeforePt
        var line = 0
        // Keep headings with at least two following lines' worth of space.
        if (p.headingLevel != 0 && s.remaining < layout.height + 40f && s.y > s.top + 1) s.newPage()
        while (line < layout.lineCount) {
            if (s.remaining < layout.getLineBottom(line) - layout.getLineTop(line)) {
                if (s.y <= s.top + 0.5f) { clippedItems++; break } // a single line taller than a page
                s.newPage()
            }
            var end = line
            val startTop = layout.getLineTop(line)
            while (end < layout.lineCount && layout.getLineBottom(end) - startTop <= s.remaining) end++
            if (end == line) end = line + 1
            val h = layout.getLineBottom(end - 1) - startTop
            s.canvas?.let { c ->
                c.save()
                c.translate(x + indent, s.y - startTop)
                c.clipRect(0f, startTop.toFloat(), layout.width.toFloat(), (startTop + h).toFloat())
                layout.draw(c)
                c.restore()
            }
            s.y += h
            line = end
            if (line < layout.lineCount) s.newPage()
        }
        s.y += p.spaceAfterPt
    }

    private fun image(img: DocBlock.Image, s: Sink, x: Float, width: Float) {
        var w = img.widthPt; var h = img.heightPt
        if (w > width) { h *= width / w; w = width }
        val maxH = s.bottom - s.top
        if (h > maxH) { w *= maxH / h; h = maxH }
        if (h > s.remaining) s.newPage()
        val left = when (img.align) { Align.CENTER -> x + (width - w) / 2; Align.RIGHT -> x + width - w; else -> x }
        s.canvas?.let { c ->
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(img.bytes, 0, img.bytes.size, opts)
            var sample = 1
            while (opts.outWidth / (sample * 2) >= w * 2.5f) sample *= 2
            val bmp = BitmapFactory.decodeByteArray(img.bytes, 0, img.bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
            if (bmp == null) skippedImages++ else {
                c.drawBitmap(bmp, null, RectF(left, s.y, left + w, s.y + h), Paint(Paint.FILTER_BITMAP_FLAG))
                bmp.recycle()
            }
        }
        s.y += h + 6f
    }

    private fun table(t: DocBlock.Table, s: Sink, x: Float, width: Float) {
        val cols = t.rows.maxOfOrNull { r -> r.sumOf { it.colSpan } } ?: return
        if (cols == 0) return
        val rel = if (t.columnWidths.size == cols && t.columnWidths.sum() > 0) t.columnWidths else List(cols) { 1f }
        val total = rel.sum()
        val widths = rel.map { it / total * width }
        val pad = 4f
        val border = Paint().apply { style = Paint.Style.STROKE; strokeWidth = 0.6f; color = Color.BLACK }
        val fill = Paint().apply { style = Paint.Style.FILL }
        for (row in t.rows) {
            var col = 0
            val cells = row.map { cell ->
                val span = cell.colSpan.coerceAtLeast(1)
                val cx = x + widths.take(col).sum()
                val cw = widths.subList(col.coerceAtMost(cols), (col + span).coerceAtMost(cols)).sum()
                col += span
                val layouts = cell.blocks.flatMap { flattenToParagraphs(it) }.map { layoutOf(it, cw - 2 * pad) to it }
                Triple(cell, cx to cw, layouts)
            }
            val rowH = (cells.maxOfOrNull { (_, _, ls) -> ls.sumOf { (l, p) -> (l.height + p.spaceAfterPt.coerceAtMost(4f)).toDouble() }.toFloat() } ?: 0f) + 2 * pad
            val maxH = s.bottom - s.top
            if (rowH > s.remaining && s.y > s.top + 1) s.newPage()
            val drawH = if (rowH > maxH) { clippedItems++; maxH } else rowH
            s.canvas?.let { c ->
                for ((cell, pos, ls) in cells) {
                    val (cx, cw) = pos
                    cell.shadeHex?.let { hex -> runCatching { Color.parseColor("#$hex") }.getOrNull()?.let { fill.color = it; c.drawRect(cx, s.y, cx + cw, s.y + drawH, fill) } }
                    c.save()
                    c.clipRect(cx, s.y, cx + cw, s.y + drawH)
                    var cy = s.y + pad
                    for ((l, p) in ls) {
                        c.save(); c.translate(cx + pad + p.indentLeftPt, cy); l.draw(c); c.restore()
                        cy += l.height + p.spaceAfterPt.coerceAtMost(4f)
                    }
                    c.restore()
                    if (t.bordered) c.drawRect(cx, s.y, cx + cw, s.y + drawH, border)
                }
            }
            s.y += drawH
        }
        s.y += 6f
    }

    private fun flattenToParagraphs(b: DocBlock): List<DocBlock.Paragraph> = when (b) {
        is DocBlock.Paragraph -> listOf(b)
        is DocBlock.Table -> b.rows.map { r -> DocBlock.Paragraph(listOf(com.docdesk.core.DocRun(r.joinToString(" | ") { c -> c.blocks.flatMap { flattenToParagraphs(it) }.joinToString(" ") { it.text } }))) }
        else -> emptyList()
    }

    private fun drawHeaderFooter(c: Canvas, pageNo: Int, total: Int) {
        fun drawBlocks(blocks: List<DocBlock>, yTop: Float) {
            var y = yTop
            for (b in blocks.flatMap { flattenToParagraphs(it) }.take(3)) {
                val l = layoutOf(b.copy(runs = b.runs.map { it.copy(sizePt = (it.sizePt ?: 9f).coerceAtMost(10f)) }), page.contentWidth)
                c.save(); c.translate(page.marginLeftPt, y); l.draw(c); c.restore()
                y += l.height
            }
        }
        if (doc.header.isNotEmpty()) drawBlocks(doc.header, (page.marginTopPt - 30f).coerceAtLeast(10f))
        if (doc.footer.isNotEmpty()) drawBlocks(doc.footer, page.heightPt - page.marginBottomPt + 12f)
        if (pageNumbers) {
            val p = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 9f; color = Color.DKGRAY; textAlign = Paint.Align.CENTER }
            c.drawText(if (total > 0) "Page $pageNo of $total" else "Page $pageNo", page.widthPt / 2, page.heightPt - 18f, p)
        }
    }
}
