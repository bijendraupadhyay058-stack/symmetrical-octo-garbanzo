package com.cashbook.app.export

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import com.cashbook.core.Align
import com.cashbook.core.Cell
import com.cashbook.core.DateFormatOption
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.ReportDocument
import com.cashbook.core.ReportTable
import com.cashbook.core.RowStyle
import java.io.OutputStream

/**
 * Renders a [ReportDocument] as a printable A4 PDF using Android's built-in [PdfDocument]:
 * report header, summary, tables with column headings repeated on every page, right-aligned
 * amounts, notes and "Page x of y" footers. Wide reports use landscape orientation.
 */
class PdfReportWriter(
    private val money: MoneyFormatter,
    private val dates: DateFormatOption,
    private val strings: Strings,
) {
    data class Strings(val appName: String, val cashbook: String, val period: String, val filters: String,
                       val generated: String, val currency: String, val page: String, val continued: String, val noData: String)

    private val navy = Color.rgb(0x1A, 0x2B, 0x5C)
    private val grey = Color.rgb(0x5F, 0x66, 0x73)
    private val lightFill = Color.rgb(0xEE, 0xF1, 0xF7)
    private val line = Color.rgb(0xD5, 0xDA, 0xE3)

    private fun paint(size: Float, bold: Boolean = false, color: Int = Color.BLACK) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = size; this.color = color
        typeface = Typeface.create(Typeface.DEFAULT, if (bold) Typeface.BOLD else Typeface.NORMAL)
    }

    private val pTitle = paint(17f, true, navy)
    private val pMeta = paint(9f, false, grey)
    private val pBody = paint(8.5f)
    private val pBold = paint(8.5f, true)
    private val pHead = paint(8.5f, true, Color.WHITE)
    private val pSection = paint(11f, true, navy)
    private val pFooter = paint(7.5f, false, grey)
    private val fill = Paint().apply { style = Paint.Style.FILL }
    private val stroke = Paint().apply { style = Paint.Style.STROKE; strokeWidth = 0.5f; color = line }

    private fun text(c: Cell): String = when (c) {
        is Cell.Text -> c.value
        is Cell.Amount -> money.format(c.paise)
        is Cell.Count -> c.value.toString()
        is Cell.Day -> dates.format(c.date)
        Cell.Empty -> ""
    }

    private class PageOps { val ops = ArrayList<(Canvas) -> Unit>() }

    fun write(doc: ReportDocument, out: OutputStream) {
        val wide = doc.tables.any { it.columns.size > 6 }
        val pw = if (wide) 842 else 595
        val ph = if (wide) 595 else 842
        val margin = 36f
        val contentW = pw - margin * 2
        val bottom = ph - margin - 18f

        val pages = ArrayList<PageOps>()
        var page = PageOps().also { pages += it }
        var y = margin

        fun newPage(): Float {
            page = PageOps().also { pages += it }
            val title = "${doc.title} · ${doc.cashbookName} · ${doc.periodLabel}"
            page.ops += { c -> c.drawText(ellipsize(title, pMeta, contentW), margin, margin + 8f, pMeta) }
            return margin + 22f
        }

        // ----- header -----
        page.ops += { c -> c.drawText(strings.appName.uppercase(), margin, y + 8f, pMeta) }
        y += 14f
        val yt = y
        page.ops += { c -> c.drawText(doc.title, margin, yt + 16f, pTitle) }
        y += 26f
        val meta = buildList {
            add("${strings.cashbook}: ${doc.cashbookName}")
            add("${strings.period}: ${doc.periodLabel}")
            if (doc.filtersLabel.isNotBlank()) add("${strings.filters}: ${doc.filtersLabel}")
            add("${strings.currency}: ${doc.currency}    ${strings.generated}: ${doc.generatedAt}")
        }
        for (m in meta) {
            for (ln in wrap(m, pMeta, contentW, 3)) { val yy = y; page.ops += { c -> c.drawText(ln, margin, yy + 9f, pMeta) }; y += 12f }
        }
        y += 4f
        run { val yy = y; page.ops += { c -> fill.color = navy; c.drawRect(margin, yy, margin + contentW, yy + 1.5f, fill) } }
        y += 10f

        // ----- summary (two columns) -----
        if (doc.summary.isNotEmpty()) {
            val colW = contentW / 2
            doc.summary.chunked(2).forEach { pair ->
                val yy = y
                pair.forEachIndexed { i, item ->
                    val x = margin + i * colW
                    val v = text(item.value)
                    page.ops += { c ->
                        fill.color = lightFill; c.drawRect(x + 2, yy, x + colW - 2, yy + 20f, fill)
                        c.drawText(ellipsize(item.label, pBody, colW * 0.55f), x + 8, yy + 13.5f, pBody)
                        c.drawText(v, x + colW - 8 - pBold.measureText(v), yy + 13.5f, pBold)
                    }
                }
                y += 23f
            }
            y += 8f
        }

        // ----- tables -----
        if (doc.isEmpty) {
            val yy = y; page.ops += { c -> c.drawText(strings.noData, margin, yy + 12f, pBody) }; y += 24f
        }
        for (table in doc.tables) {
            if (table.rows.isEmpty()) continue
            val widths = columnWidths(table, contentW)
            val headH = headerHeight(table, widths)
            if (y + (if (table.title != null) 18f else 0f) + headH + 16f > bottom) y = newPage()
            if (table.title != null) {
                val yy = y; page.ops += { c -> c.drawText(table.title!!, margin, yy + 12f, pSection) }; y += 18f
            }
            y = drawHeader(page, table, widths, margin, y)
            for (row in table.rows) {
                val bold = row.style != RowStyle.NORMAL
                val pt = if (bold) pBold else pBody
                val cellLines = row.cells.mapIndexed { i, cell -> wrap(text(cell), pt, widths[i] - 6f, 4) }
                val h = (cellLines.maxOfOrNull { it.size } ?: 1).coerceAtLeast(1) * 10.5f + 5f
                if (y + h > bottom) {
                    y = newPage()
                    if (table.title != null) {
                        val yy = y; val t = "${table.title} (${strings.continued})"
                        page.ops += { c -> c.drawText(t, margin, yy + 12f, pSection) }; y += 18f
                    }
                    y = drawHeader(page, table, widths, margin, y)
                }
                val yy = y
                page.ops += { c ->
                    when (row.style) {
                        RowStyle.HEADING -> { fill.color = lightFill; c.drawRect(margin, yy, margin + contentW, yy + h, fill) }
                        RowStyle.TOTAL -> { fill.color = Color.rgb(0xDD, 0xE3, 0xF0); c.drawRect(margin, yy, margin + contentW, yy + h, fill) }
                        else -> {}
                    }
                    var x = margin
                    cellLines.forEachIndexed { i, lines ->
                        val col = table.columns.getOrNull(i)
                        lines.forEachIndexed { li, ln ->
                            val tx = if (col?.align == Align.END) x + widths[i] - 3f - pt.measureText(ln) else x + 3f
                            c.drawText(ln, tx, yy + 9.5f + li * 10.5f, pt)
                        }
                        x += widths[i]
                    }
                    c.drawLine(margin, yy + h, margin + contentW, yy + h, stroke)
                }
                y += h
            }
            y += 14f
        }

        // ----- notes -----
        for (n in doc.notes) {
            val lines = wrap("• $n", pMeta, contentW, 6)
            if (y + lines.size * 11f > bottom) y = newPage()
            for (ln in lines) { val yy = y; page.ops += { c -> c.drawText(ln, margin, yy + 9f, pMeta) }; y += 11f }
        }

        // ----- render with page numbers -----
        val pdf = PdfDocument()
        try {
            pages.forEachIndexed { i, p ->
                val pg = pdf.startPage(PdfDocument.PageInfo.Builder(pw, ph, i + 1).create())
                val c = pg.canvas
                p.ops.forEach { it(c) }
                c.drawLine(margin, ph - margin - 8f, pw - margin, ph - margin - 8f, stroke)
                c.drawText("${strings.appName} · ${strings.generated}: ${doc.generatedAt}", margin, ph - margin + 4f, pFooter)
                val pn = strings.page.format(i + 1, pages.size)
                c.drawText(pn, pw - margin - pFooter.measureText(pn), ph - margin + 4f, pFooter)
                pdf.finishPage(pg)
            }
            pdf.writeTo(out)
        } finally {
            pdf.close()
        }
    }

    private fun columnWidths(t: ReportTable, total: Float): FloatArray {
        val sum = t.columns.sumOf { it.weight.toDouble() }.toFloat()
        return FloatArray(t.columns.size) { t.columns[it].weight / sum * total }
    }

    private fun headerHeight(t: ReportTable, widths: FloatArray): Float =
        (t.columns.mapIndexed { i, col -> wrap(col.title, pHead, widths[i] - 6f, 3).size }.maxOrNull() ?: 1) * 10.5f + 7f

    private fun drawHeader(page: PageOps, t: ReportTable, widths: FloatArray, margin: Float, y: Float): Float {
        val h = headerHeight(t, widths)
        val total = widths.sum()
        page.ops += { c ->
            fill.color = navy; c.drawRect(margin, y, margin + total, y + h, fill)
            var x = margin
            t.columns.forEachIndexed { i, col ->
                wrap(col.title, pHead, widths[i] - 6f, 3).forEachIndexed { li, ln ->
                    val tx = if (col.align == Align.END) x + widths[i] - 3f - pHead.measureText(ln) else x + 3f
                    c.drawText(ln, tx, y + 11f + li * 10.5f, pHead)
                }
                x += widths[i]
            }
        }
        return y + h
    }

    private fun ellipsize(s: String, p: Paint, w: Float): String {
        if (p.measureText(s) <= w) return s
        var end = s.length
        while (end > 0 && p.measureText(s, 0, end) + p.measureText("…") > w) end--
        return s.substring(0, end) + "…"
    }

    /** Word-wraps [s] to [w] points, at most [maxLines] lines (last line ellipsized). */
    private fun wrap(s: String, p: Paint, w: Float, maxLines: Int): List<String> {
        if (s.isEmpty()) return listOf("")
        if (p.measureText(s) <= w) return listOf(s)
        val out = ArrayList<String>()
        var current = ""
        for (word in s.split(' ')) {
            val candidate = if (current.isEmpty()) word else "$current $word"
            if (p.measureText(candidate) <= w) { current = candidate; continue }
            if (current.isNotEmpty()) out += current
            var rest = word
            while (p.measureText(rest) > w && rest.length > 1) {
                var n = rest.length
                while (n > 1 && p.measureText(rest, 0, n) > w) n--
                out += rest.substring(0, n); rest = rest.substring(n)
            }
            current = rest
        }
        if (current.isNotEmpty()) out += current
        if (out.size > maxLines) {
            val kept = out.take(maxLines).toMutableList()
            kept[maxLines - 1] = ellipsize(kept[maxLines - 1] + " " + out[maxLines], p, w)
            return kept
        }
        return out
    }
}
