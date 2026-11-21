package com.docdesk.core

enum class Orientation { PORTRAIT, LANDSCAPE }
enum class PaperSize(val label: String, val widthPt: Float, val heightPt: Float) {
    A4("A4", 595.3f, 841.9f), LETTER("Letter", 612f, 792f), LEGAL("Legal", 612f, 1008f), A3("A3", 841.9f, 1190.6f)
}
enum class Margins(val label: String, val pt: Float) { NARROW("Narrow", 18f), NORMAL("Normal", 36f), WIDE("Wide", 72f) }
enum class Scaling(val label: String) { ACTUAL("Actual size"), FIT_COLUMNS("Fit all columns on one page"), FIT_SHEET("Fit sheet on one page"), CUSTOM("Custom %") }

data class SheetPrintOptions(
    val orientation: Orientation = Orientation.PORTRAIT,
    val paper: PaperSize = PaperSize.A4,
    val margins: Margins = Margins.NORMAL,
    val scaling: Scaling = Scaling.FIT_COLUMNS,
    val customPercent: Int = 100,
    val gridlines: Boolean = true,
    val sheetNameHeader: Boolean = true,
    val pageNumbers: Boolean = true,
    val usePrintArea: Boolean = true,
)

/** One printed page: a block of rows × columns of a sheet, drawn at [scale]. */
data class SheetPage(val rows: List<Int>, val cols: List<Int>, val scale: Float)

/**
 * Decides which rows/columns go on which PDF page (Excel's "down, then over" order).
 * Sizes are in points; character-width units are converted with an approximate 7 px/char.
 */
object SheetPaginator {
    const val HEADER_SPACE = 22f
    const val FOOTER_SPACE = 18f

    fun columnWidthPt(sheet: Sheet, col: Int): Float = if (col in sheet.hiddenColumns) 0f else
        ((sheet.columnWidths[col] ?: sheet.defaultColumnWidth) * 7.0 + 5.0).toFloat() * 0.75f

    fun rowHeightPt(sheet: Sheet, row: Int, autoHeight: (Int) -> Float = { 15f }): Float = if (row in sheet.hiddenRows) 0f else sheet.rowHeightsPt[row] ?: autoHeight(row)

    fun pageSize(o: SheetPrintOptions): Pair<Float, Float> =
        if (o.orientation == Orientation.PORTRAIT) o.paper.widthPt to o.paper.heightPt else o.paper.heightPt to o.paper.widthPt

    fun range(sheet: Sheet, o: SheetPrintOptions): CellRange? {
        if (o.usePrintArea) sheet.printArea?.let { return it }
        if (sheet.maxRow < 0 || sheet.maxCol < 0) return null
        return CellRange(0, 0, sheet.maxRow, sheet.maxCol)
    }

    fun paginate(sheet: Sheet, o: SheetPrintOptions, autoHeight: (Int) -> Float = { 15f }): List<SheetPage> {
        val r = range(sheet, o) ?: return emptyList()
        val rows = (r.firstRow..r.lastRow).filter { it !in sheet.hiddenRows }
        val cols = (r.firstCol..r.lastCol).filter { it !in sheet.hiddenColumns }
        if (rows.isEmpty() || cols.isEmpty()) return emptyList()
        val (pw, ph) = pageSize(o)
        val availW = pw - 2 * o.margins.pt
        val availH = ph - 2 * o.margins.pt - (if (o.sheetNameHeader) HEADER_SPACE else 0f) - (if (o.pageNumbers) FOOTER_SPACE else 0f)
        val totalW = cols.sumOf { columnWidthPt(sheet, it).toDouble() }.toFloat()
        val totalH = rows.sumOf { rowHeightPt(sheet, it, autoHeight).toDouble() }.toFloat()
        val scale = when (o.scaling) {
            Scaling.ACTUAL -> 1f
            Scaling.CUSTOM -> (o.customPercent.coerceIn(10, 400)) / 100f
            Scaling.FIT_COLUMNS -> minOf(1f, availW / totalW)
            Scaling.FIT_SHEET -> minOf(1f, availW / totalW, availH / totalH)
        }.coerceAtLeast(0.1f)
        val colChunks = chunk(cols, availW / scale) { columnWidthPt(sheet, it) }
        val rowChunks = chunk(rows, availH / scale) { rowHeightPt(sheet, it, autoHeight) }
        val pages = mutableListOf<SheetPage>()
        for (cc in colChunks) for (rc in rowChunks) pages.add(SheetPage(rc, cc, scale))
        return pages
    }

    private fun chunk(items: List<Int>, limit: Float, size: (Int) -> Float): List<List<Int>> {
        val out = mutableListOf<List<Int>>()
        var cur = mutableListOf<Int>(); var used = 0f
        for (i in items) {
            val s = size(i)
            if (cur.isNotEmpty() && used + s > limit) { out.add(cur); cur = mutableListOf(); used = 0f }
            cur.add(i); used += s
        }
        if (cur.isNotEmpty()) out.add(cur)
        return out
    }
}
