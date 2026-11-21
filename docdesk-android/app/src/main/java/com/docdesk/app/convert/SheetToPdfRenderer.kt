package com.docdesk.app.convert

import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.text.TextUtils
import com.docdesk.app.jobs.Progress
import com.docdesk.core.Align
import com.docdesk.core.Sheet
import com.docdesk.core.SheetPaginator
import com.docdesk.core.SheetPrintOptions
import java.io.File

/** Draws worksheets onto PDF pages following [SheetPaginator]'s page plan. */
object SheetToPdfRenderer {

    data class Stats(val pages: Int, val truncatedCells: Int)

    fun render(sheets: List<Sheet>, o: SheetPrintOptions, out: File, progress: Progress?): Stats {
        val plans = sheets.map { s -> s to SheetPaginator.paginate(s, o) { r -> autoRowHeight(s, r) } }.filter { it.second.isNotEmpty() }
        val total = plans.sumOf { it.second.size }
        if (total == 0) throw com.docdesk.app.jobs.OperationFailed("The selected sheets are empty.")
        val (pw, ph) = SheetPaginator.pageSize(o)
        val pdf = PdfDocument()
        var pageNo = 0
        var truncated = 0
        val text = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK }
        val grid = Paint().apply { style = Paint.Style.STROKE; color = Color.rgb(200, 200, 200); strokeWidth = 0.4f }
        val border = Paint().apply { style = Paint.Style.STROKE; color = Color.BLACK; strokeWidth = 0.7f }
        val fill = Paint().apply { style = Paint.Style.FILL }
        val small = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 9f; color = Color.DKGRAY }
        try {
            for ((sheet, pages) in plans) {
                val mergeMap = HashMap<Pair<Int, Int>, com.docdesk.core.CellRange>()
                for (m in sheet.merges) for (r in m.firstRow..m.lastRow) for (c in m.firstCol..m.lastCol) mergeMap[r to c] = m
                for (pg in pages) {
                    pageNo++
                    progress?.step("Drawing page $pageNo of $total", pageNo.toFloat() / total)
                    val page = pdf.startPage(PdfDocument.PageInfo.Builder(pw.toInt(), ph.toInt(), pageNo).create())
                    val c = page.canvas
                    val m = o.margins.pt
                    if (o.sheetNameHeader) c.drawText(TextUtils.ellipsize(sheet.name, small, pw - 2 * m, TextUtils.TruncateAt.END).toString(), m, m + 10f, small)
                    if (o.pageNumbers) { small.textAlign = Paint.Align.CENTER; c.drawText("Page $pageNo of $total", pw / 2, ph - m + 12f, small); small.textAlign = Paint.Align.LEFT }
                    c.save()
                    c.translate(m, m + if (o.sheetNameHeader) SheetPaginator.HEADER_SPACE else 0f)
                    c.scale(pg.scale, pg.scale)
                    val colX = HashMap<Int, Float>(); var x = 0f
                    for (col in pg.cols) { colX[col] = x; x += SheetPaginator.columnWidthPt(sheet, col) }
                    val rowY = HashMap<Int, Float>(); var y = 0f
                    for (row in pg.rows) { rowY[row] = y; y += SheetPaginator.rowHeightPt(sheet, row) { autoRowHeight(sheet, it) } }
                    for (row in pg.rows) for (col in pg.cols) {
                        val merge = mergeMap[row to col]
                        if (merge != null && (merge.firstRow != row || merge.firstCol != col)) {
                            // Covered by a merge that starts on another page chunk: draw nothing but keep gridlines off.
                            if (!(merge.firstRow !in pg.rows || merge.firstCol !in pg.cols)) continue
                        }
                        val cx = colX[col]!!; val cy = rowY[row]!!
                        var cw = SheetPaginator.columnWidthPt(sheet, col); var ch = SheetPaginator.rowHeightPt(sheet, row) { autoRowHeight(sheet, it) }
                        if (merge != null && merge.firstRow == row && merge.firstCol == col) {
                            cw = (merge.firstCol..merge.lastCol).filter { it in pg.cols }.sumOf { SheetPaginator.columnWidthPt(sheet, it).toDouble() }.toFloat()
                            ch = (merge.firstRow..merge.lastRow).filter { it in pg.rows }.sumOf { SheetPaginator.rowHeightPt(sheet, it) { r -> autoRowHeight(sheet, r) }.toDouble() }.toFloat()
                        }
                        val cell = sheet.cells[row]?.get(col)
                        cell?.fillHex?.let { h -> runCatching { Color.parseColor("#$h") }.getOrNull()?.let { fill.color = it; c.drawRect(cx, cy, cx + cw, cy + ch, fill) } }
                        if (o.gridlines) c.drawRect(cx, cy, cx + cw, cy + ch, grid)
                        if (cell != null) {
                            if (cell.borderLeft) c.drawLine(cx, cy, cx, cy + ch, border)
                            if (cell.borderRight) c.drawLine(cx + cw, cy, cx + cw, cy + ch, border)
                            if (cell.borderTop) c.drawLine(cx, cy, cx + cw, cy, border)
                            if (cell.borderBottom) c.drawLine(cx, cy + ch, cx + cw, cy + ch, border)
                            if (cell.display.isNotEmpty()) {
                                text.textSize = cell.fontSizePt
                                text.typeface = Typeface.create(Typeface.DEFAULT, when { cell.bold && cell.italic -> Typeface.BOLD_ITALIC; cell.bold -> Typeface.BOLD; cell.italic -> Typeface.ITALIC; else -> Typeface.NORMAL })
                                text.color = cell.colorHex?.let { h -> runCatching { Color.parseColor("#$h") }.getOrNull() } ?: Color.BLACK
                                val align = cell.align ?: if (cell.isNumeric) Align.RIGHT else Align.LEFT
                                c.save()
                                c.clipRect(cx, cy, cx + cw, cy + ch)
                                val innerW = (cw - 4f).coerceAtLeast(4f)
                                if (cell.wrap) {
                                    val l = StaticLayout.Builder.obtain(cell.display, 0, cell.display.length, text, innerW.toInt())
                                        .setAlignment(when (align) { Align.CENTER -> Layout.Alignment.ALIGN_CENTER; Align.RIGHT -> Layout.Alignment.ALIGN_OPPOSITE; else -> Layout.Alignment.ALIGN_NORMAL })
                                        .setIncludePad(false).build()
                                    if (l.height > ch) truncated++
                                    c.translate(cx + 2f, cy + 1f); l.draw(c)
                                } else {
                                    val w = text.measureText(cell.display)
                                    var shown = cell.display
                                    if (w > innerW) {
                                        // Excel shows ### for numbers that do not fit; text is cut at the cell edge.
                                        if (cell.isNumeric) shown = "#".repeat((innerW / text.measureText("#")).toInt().coerceAtLeast(1))
                                        truncated++
                                    }
                                    val tw = text.measureText(shown)
                                    val tx = when (align) { Align.RIGHT -> cx + cw - 2f - tw; Align.CENTER -> cx + (cw - tw) / 2; else -> cx + 2f }
                                    val baseline = cy + ch - 3f - (ch - cell.fontSizePt * 1.25f).coerceAtLeast(0f) / 2f * 0f
                                    c.drawText(shown, tx, baseline.coerceAtMost(cy + ch - 2f), text)
                                }
                                c.restore()
                            }
                        }
                    }
                    c.restore()
                    pdf.finishPage(page)
                }
            }
            val tmp = File(out.parentFile, out.name + ".part")
            tmp.outputStream().buffered().use { pdf.writeTo(it) }
            if (!tmp.renameTo(out)) throw java.io.IOException("Could not save the PDF")
        } finally { pdf.close() }
        return Stats(total, truncated)
    }

    private fun autoRowHeight(sheet: Sheet, row: Int): Float {
        val maxFont = sheet.cells[row]?.values?.maxOfOrNull { it.fontSizePt } ?: 11f
        val lines = sheet.cells[row]?.values?.filter { it.wrap }?.maxOfOrNull { it.display.count { ch -> ch == '\n' } + 1 } ?: 1
        return (maxFont * 1.35f + 2f) * lines
    }
}
