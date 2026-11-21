package com.docdesk.core

import kotlin.math.max
import kotlin.math.min

enum class ColumnType { TEXT, DATE, AMOUNT }

/** Why a cell needs a human look before the data is trusted. */
enum class CellFlag(val message: String) {
    LOW_OCR_CONFIDENCE("Low OCR confidence"),
    MERGED_WRAPPED_TEXT("Wrapped text joined from several lines"),
    UNPARSED_VALUE("Value could not be read as a number/date; kept as text"),
    AMBIGUOUS_COLUMN("Text may belong to a neighbouring column"),
    EDITED("Edited by you"),
}

data class TableCell(
    /** The exact extracted text. Never rewritten by interpretation. */
    val raw: String,
    val confidence: Float? = null,
    val flags: Set<CellFlag> = emptySet(),
) {
    val isBlank get() = raw.isBlank()
}

data class TableRow(
    val cells: List<TableCell>, val pageIndex: Int, val isHeader: Boolean = false,
    /** Vertical extent on the page as a fraction of page height (0 = top), for showing the row on the source page. */
    val top: Float? = null, val bottom: Float? = null,
)

data class ExtractedTable(
    val pageIndex: Int,
    val tableIndexOnPage: Int,
    val columnCount: Int,
    val rows: List<TableRow>,
    val columnTypes: List<ColumnType>,
    val source: TextSource,
) {
    val header: TableRow? get() = rows.firstOrNull { it.isHeader }
    val bodyRows: List<TableRow> get() = rows.filter { !it.isHeader }
    val flaggedCellCount: Int get() = rows.sumOf { r -> r.cells.count { it.flags.isNotEmpty() } }
}

data class TableOptions(
    val numberStyle: NumberStyle = NumberStyle.INDIAN,
    val dateOrder: DateOrder = DateOrder.DMY,
    /** Limit extraction to this area of every page (manual table selection). */
    val area: NormRect? = null,
    /** OCR words below this confidence are flagged for review. */
    val lowConfidence: Float = 0.75f,
    /** Join description lines that wrap onto the next line into the row above. */
    val mergeWrappedRows: Boolean = true,
    /** Minimum number of rows for a block of aligned lines to count as a table. */
    val minRows: Int = 2,
)

/**
 * Rebuilds tables from positioned words using whitespace analysis:
 * 1. words are grouped into lines;
 * 2. each line is cut into "segments" wherever the horizontal gap is wider than a space;
 * 3. lines with two or more segments form table candidates; a horizontal coverage profile of
 *    their segments yields the column boundaries (empty vertical corridors = separators);
 * 4. lines that carry only description text directly below a row are treated as wrapped text.
 *
 * The extractor never invents values: empty cells stay empty, and uncertain cells are flagged.
 */
object TableExtractor {

    private data class Segment(val words: List<TextWord>) {
        val x = words.minOf { it.x }
        val right = words.maxOf { it.right }
        val text = words.joinToString(" ") { it.text }
        val confidence: Float? = words.mapNotNull { it.confidence }.minOrNull()
    }

    private data class SegLine(val line: TextLine, val segments: List<Segment>)

    fun extract(page: PageText, options: TableOptions = TableOptions()): List<ExtractedTable> {
        val words = options.area?.let { a -> page.words.filter { a.containsCenterOf(it, page.width, page.height) } } ?: page.words
        val lines = LineGrouper.group(words)
        if (lines.isEmpty()) return emptyList()
        val segLines = lines.map { SegLine(it, segment(it)) }

        // Find blocks of consecutive lines that look tabular. Single-segment lines are allowed
        // inside a block (wrapped descriptions) but not at its start.
        val blocks = mutableListOf<MutableList<SegLine>>()
        var current: MutableList<SegLine>? = null
        var singleRun = 0
        for ((i, sl) in segLines.withIndex()) {
            val multi = sl.segments.size >= 2
            val gapOk = current != null && i > 0 && (sl.line.top - segLines[i - 1].line.bottom) < max(sl.line.height, segLines[i - 1].line.height) * 2.5f
            if (multi) {
                if (current == null || !gapOk) { current = mutableListOf(); blocks.add(current) }
                current.add(sl); singleRun = 0
            } else if (current != null && gapOk && singleRun < 3) {
                current.add(sl); singleRun++
            } else {
                current = null; singleRun = 0
            }
        }

        val tables = mutableListOf<ExtractedTable>()
        for (block in blocks) {
            // Drop trailing single-segment lines: they belong to the text after the table.
            while (block.isNotEmpty() && block.last().segments.size < 2) block.removeAt(block.lastIndex)
            if (block.count { it.segments.size >= 2 } < options.minRows) continue
            buildTable(block, page, tables.size, options)?.let { tables.add(it) }
        }
        return tables
    }

    private fun segment(line: TextLine): List<Segment> {
        val out = mutableListOf<Segment>()
        var cur = mutableListOf<TextWord>()
        for (w in line.words) {
            if (cur.isEmpty()) { cur.add(w); continue }
            val prev = cur.last()
            val gap = w.x - prev.right
            val threshold = max(prev.fontSize, w.fontSize) * 0.8f
            if (gap > threshold) { out.add(Segment(cur)); cur = mutableListOf(w) } else cur.add(w)
        }
        if (cur.isNotEmpty()) out.add(Segment(cur))
        return out
    }

    private fun buildTable(block: List<SegLine>, page: PageText, index: Int, options: TableOptions): ExtractedTable? {
        val multiLines = block.filter { it.segments.size >= 2 }
        val minX = block.minOf { it.line.x }
        val maxX = block.maxOf { it.line.right }
        val width = (maxX - minX).toInt() + 2
        if (width <= 0) return null
        // Coverage profile in 1-unit bins across multi-segment lines.
        val coverage = IntArray(width)
        for (sl in multiLines) for (s in sl.segments) {
            val a = (s.x - minX).toInt().coerceIn(0, width - 1)
            val b = (s.right - minX).toInt().coerceIn(0, width - 1)
            for (i in a..b) coverage[i]++
        }
        val threshold = max(1, (multiLines.size * 0.08f).toInt())
        // Columns = maximal runs of covered bins; tiny gaps (< 2 units) do not split columns.
        val cols = mutableListOf<IntRange>()
        var start = -1
        for (i in 0 until width) {
            val on = coverage[i] >= threshold
            if (on && start < 0) start = i
            if (!on && start >= 0) { cols.add(start until i); start = -1 }
        }
        if (start >= 0) cols.add(start until width)
        val merged = mutableListOf<IntRange>()
        for (c in cols) {
            if (merged.isNotEmpty() && c.first - merged.last().last <= 2) merged[merged.lastIndex] = merged.last().first..c.last
            else merged.add(c)
        }
        if (merged.size < 2) return null
        val bounds = merged.map { (it.first + minX) to (it.last + minX) }

        fun columnOf(s: Segment): Pair<Int, Boolean> {
            var best = 0; var bestOverlap = -1f; var spans = 0
            for ((ci, b) in bounds.withIndex()) {
                val ov = min(s.right, b.second) - max(s.x, b.first)
                if (ov > 0) spans++
                if (ov > bestOverlap) { bestOverlap = ov; best = ci }
            }
            if (bestOverlap <= 0) {
                // No overlap: nearest column by centre distance.
                val cx = (s.x + s.right) / 2
                best = bounds.indices.minBy { kotlin.math.abs((bounds[it].first + bounds[it].second) / 2 - cx) }
            }
            return best to (spans > 1)
        }

        // Assign segments to columns, row by row.
        data class RawRow(val texts: Array<MutableList<Segment>>, val ambiguous: BooleanArray, val line: TextLine)
        val rawRows = block.map { sl ->
            val arr = Array(bounds.size) { mutableListOf<Segment>() }
            val amb = BooleanArray(bounds.size)
            for (s in sl.segments) { val (c, a) = columnOf(s); arr[c].add(s); if (a) amb[c] = true }
            RawRow(arr, amb, sl.line)
        }

        // Column types from the contents of the rows, excluding a header row.
        val firstIsHeader = rawRows.firstOrNull()?.let { r ->
            looksLikeHeader(r.texts.map { segs -> TableCell(segs.joinToString(" ") { it.text }) }, options)
        } ?: false
        val typedRows = if (firstIsHeader) rawRows.drop(1) else rawRows
        val types = bounds.indices.map { c ->
            val vals = typedRows.mapNotNull { r -> r.texts[c].takeIf { it.isNotEmpty() }?.joinToString(" ") { it.text } }
            classify(vals, options)
        }

        val rows = mutableListOf<TableRow>()
        var headerFound = false
        for (r in rawRows) {
            val cells = bounds.indices.map { c ->
                val segs = r.texts[c]
                val text = segs.joinToString(" ") { it.text }
                val conf = segs.mapNotNull { it.confidence }.minOrNull()
                val flags = mutableSetOf<CellFlag>()
                if (conf != null && conf < options.lowConfidence) flags.add(CellFlag.LOW_OCR_CONFIDENCE)
                if (r.ambiguous[c]) flags.add(CellFlag.AMBIGUOUS_COLUMN)
                TableCell(text, conf, flags)
            }
            val filled = cells.count { !it.isBlank }
            // Wrapped-description line: only TEXT columns filled, no date/amount, directly under a row.
            val onlyText = cells.withIndex().all { (i, c) -> c.isBlank || types[i] == ColumnType.TEXT }
            val prev = rows.lastOrNull()
            val noDateOrAmountTypes = types.none { it != ColumnType.TEXT }
            if (options.mergeWrappedRows && prev != null && !prev.isHeader && onlyText && !noDateOrAmountTypes &&
                (filled == 1 || r.texts.count { it.isNotEmpty() } < cells.size / 2)
            ) {
                val mergedCells = prev.cells.mapIndexed { i, pc ->
                    val add = cells[i]
                    if (add.isBlank) pc else TableCell(
                        listOf(pc.raw, add.raw).filter { it.isNotBlank() }.joinToString(" "),
                        listOfNotNull(pc.confidence, add.confidence).minOrNull(),
                        pc.flags + add.flags + CellFlag.MERGED_WRAPPED_TEXT,
                    )
                }
                rows[rows.lastIndex] = prev.copy(cells = mergedCells, bottom = maxOf(prev.bottom ?: 0f, r.line.bottom / page.height))
                continue
            }
            val isHeader = !headerFound && rows.isEmpty() && looksLikeHeader(cells, options)
            if (isHeader) headerFound = true
            rows.add(TableRow(cells, page.pageIndex, isHeader, r.line.top / page.height, r.line.bottom / page.height))
        }
        // Flag values in typed columns that could not be interpreted.
        val checked = rows.map { row ->
            if (row.isHeader) row else row.copy(cells = row.cells.mapIndexed { i, c ->
                val bad = !c.isBlank && when (types[i]) {
                    ColumnType.AMOUNT -> AmountParser.parse(c.raw, options.numberStyle) == null
                    ColumnType.DATE -> DateParser.parse(c.raw, options.dateOrder) == null
                    ColumnType.TEXT -> false
                }
                if (bad) c.copy(flags = c.flags + CellFlag.UNPARSED_VALUE) else c
            })
        }
        return ExtractedTable(page.pageIndex, index, bounds.size, checked, types, page.source)
    }

    fun classify(values: List<String>, options: TableOptions): ColumnType {
        val nonEmpty = values.filter { it.isNotBlank() }
        if (nonEmpty.isEmpty()) return ColumnType.TEXT
        val dates = nonEmpty.count { DateParser.looksLikeDate(it, options.dateOrder) }
        val money = nonEmpty.count { AmountParser.looksLikeMoney(it, options.numberStyle) }
        return when {
            // 50% tolerates OCR misreads in the column; misread cells are then flagged for review.
            dates >= nonEmpty.size * 0.5 && dates > 0 -> ColumnType.DATE
            money >= nonEmpty.size * 0.5 && money > 0 -> ColumnType.AMOUNT
            else -> ColumnType.TEXT
        }
    }

    private fun looksLikeHeader(cells: List<TableCell>, options: TableOptions): Boolean {
        val filled = cells.filter { !it.isBlank }
        if (filled.size < 2) return false
        val alpha = filled.count { c ->
            c.raw.any(Char::isLetter) && AmountParser.parse(c.raw, options.numberStyle) == null && DateParser.parse(c.raw, options.dateOrder) == null
        }
        return alpha == filled.size
    }

    /**
     * Joins tables that continue across pages (same column count and similar header) and
     * removes repeated header rows. Used when the user exports everything to one worksheet.
     */
    fun combine(tables: List<ExtractedTable>): List<ExtractedTable> {
        val out = mutableListOf<ExtractedTable>()
        for (t in tables) {
            val last = out.lastOrNull()
            if (last != null && last.columnCount == t.columnCount && (t.header == null || sameHeader(last.header, t.header))) {
                val body = t.rows.filter { !it.isHeader }
                out[out.lastIndex] = last.copy(rows = last.rows + body)
            } else out.add(t)
        }
        return out
    }

    private fun sameHeader(a: TableRow?, b: TableRow?): Boolean {
        if (a == null || b == null) return a == null && b == null
        fun norm(r: TableRow) = r.cells.joinToString("|") { it.raw.lowercase().filter(Char::isLetterOrDigit) }
        return norm(a) == norm(b)
    }
}
