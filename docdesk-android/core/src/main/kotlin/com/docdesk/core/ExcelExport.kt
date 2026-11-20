package com.docdesk.core

import java.math.BigDecimal

enum class SheetMode(val label: String) {
    ONE_SHEET("All tables on one worksheet"),
    SHEET_PER_PAGE("One worksheet per page"),
    SHEET_PER_TABLE("One worksheet per table"),
}

data class ExcelExportOptions(
    val mode: SheetMode = SheetMode.ONE_SHEET,
    val numberStyle: NumberStyle = NumberStyle.INDIAN,
    val dateOrder: DateOrder = DateOrder.DMY,
    /** Write recognised amounts as numbers (raw text kept on the "Source text" sheet). */
    val convertNumbers: Boolean = true,
    /** Write recognised dates as real Excel dates. */
    val convertDates: Boolean = true,
    val dateDisplayFormat: String = "dd-mm-yyyy",
    val includeSourceSheet: Boolean = true,
    val includeReviewSheet: Boolean = true,
    val highlightFlagged: Boolean = true,
)

/** Turns reviewed tables into worksheets, without ever altering the extracted text. */
object ExcelExport {

    const val INDIAN_FORMAT = """[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00"""
    private const val INTL_FORMAT = "#,##0.00"

    data class Built(val sheets: List<XSheet>, val convertedCells: Int, val textCells: Int, val flaggedCells: Int)

    fun build(tables: List<ExtractedTable>, options: ExcelExportOptions, report: List<Pair<String, String>> = emptyList()): Built {
        val groups: List<Pair<String, List<ExtractedTable>>> = when (options.mode) {
            SheetMode.ONE_SHEET -> listOf("Tables" to TableExtractor.combine(tables))
            SheetMode.SHEET_PER_PAGE -> tables.groupBy { it.pageIndex }.toSortedMap().map { (p, t) -> "Page ${p + 1}" to t }
            SheetMode.SHEET_PER_TABLE -> tables.map { "Page ${it.pageIndex + 1} Table ${it.tableIndexOnPage + 1}" to listOf(it) }
        }.ifEmpty { listOf("Tables" to emptyList()) }

        var converted = 0; var text = 0; var flagged = 0
        val sheets = mutableListOf<XSheet>()
        val sourceSheets = mutableListOf<XSheet>()
        val review = mutableListOf<List<XStyledCell>>()
        val sheetNames = XlsxWriter.uniqueSheetNames(groups.map { it.first })

        groups.forEachIndexed { gi, (_, groupTables) ->
            val rows = mutableListOf<List<XStyledCell>>()
            val srcRows = mutableListOf<List<XStyledCell>>()
            var maxCols = 0
            groupTables.forEachIndexed { ti, t ->
                if (ti > 0) { rows.add(emptyList()); srcRows.add(emptyList()) }
                maxCols = maxOf(maxCols, t.columnCount)
                for (row in t.rows) {
                    val cells = row.cells.mapIndexed { ci, cell ->
                        val excelRow = rows.size + 1
                        if (cell.flags.isNotEmpty()) {
                            flagged++
                            review.add(listOf(
                                XStyledCell(XCell.Text(sheetNames[gi])),
                                XStyledCell(XCell.Text(XlsxWriter.columnName(ci) + excelRow)),
                                XStyledCell(XCell.Text("${row.pageIndex + 1}")),
                                XStyledCell(XCell.Text(cell.raw)),
                                XStyledCell(XCell.Text(cell.flags.joinToString("; ") { it.message })),
                                XStyledCell(cell.confidence?.let { XCell.Number(BigDecimal(it.toDouble()).setScale(2, java.math.RoundingMode.HALF_UP)) } ?: XCell.Blank),
                            ))
                        }
                        val hl = options.highlightFlagged && cell.flags.any { it != CellFlag.EDITED }
                        if (row.isHeader) XStyledCell(XCell.Text(cell.raw), bold = true)
                        else {
                            val x = interpret(cell, t.columnTypes.getOrElse(ci) { ColumnType.TEXT }, options)
                            if (x is XCell.Text) text++ else if (x != XCell.Blank) converted++
                            XStyledCell(x, highlight = hl)
                        }
                    }
                    rows.add(cells)
                    srcRows.add(row.cells.map { XStyledCell(XCell.Text(it.raw), bold = row.isHeader) })
                }
            }
            val widths = (0 until maxCols).map { c ->
                val longest = srcRows.maxOfOrNull { r -> (r.getOrNull(c)?.cell as? XCell.Text)?.value?.length ?: 0 } ?: 8
                longest.coerceIn(8, 60) + 2.0
            }
            sheets.add(XSheet(sheetNames[gi], rows, widths, freezeTopRow = groupTables.firstOrNull()?.rows?.firstOrNull()?.isHeader == true))
            sourceSheets.add(XSheet("Source ${sheetNames[gi]}", srcRows, widths))
        }

        val extra = mutableListOf<XSheet>()
        if (options.includeSourceSheet) {
            // Source text exactly as extracted, so every converted value can be compared.
            extra.addAll(sourceSheets.map { it.copy(name = "Source text" + if (sourceSheets.size > 1) " " + it.name.removePrefix("Source ") else "") })
        }
        if (options.includeReviewSheet) {
            val head = listOf("Sheet", "Cell", "PDF page", "Extracted text", "Reason", "OCR confidence").map { XStyledCell(XCell.Text(it), bold = true) }
            val reportRows = report.map { (k, v) -> listOf(XStyledCell(XCell.Text(k), bold = true), XStyledCell(XCell.Text(v), wrap = true)) }
            val rows = buildList {
                add(listOf(XStyledCell(XCell.Text("Conversion report"), bold = true)))
                addAll(reportRows)
                add(listOf(XStyledCell(XCell.Text("Automatic checks help find errors but cannot guarantee that the extraction is complete or accurate. Compare important figures with the original PDF."), wrap = true)))
                add(emptyList())
                add(listOf(XStyledCell(XCell.Text(if (review.isEmpty()) "No cells were flagged for review." else "${review.size} cell(s) need review:"), bold = true)))
                if (review.isNotEmpty()) { add(head); addAll(review) }
            }
            extra.add(XSheet("Review", rows, listOf(26.0, 60.0, 10.0, 40.0, 50.0, 14.0)))
        }
        val all = sheets + extra
        val finalNames = XlsxWriter.uniqueSheetNames(all.map { it.name })
        return Built(all.mapIndexed { i, s -> s.copy(name = finalNames[i]) }, converted, text, flagged)
    }

    fun interpret(cell: TableCell, type: ColumnType, o: ExcelExportOptions): XCell {
        val raw = cell.raw.trim()
        if (raw.isEmpty()) return XCell.Blank
        when (type) {
            ColumnType.AMOUNT -> if (o.convertNumbers) {
                val p = AmountParser.parse(raw, o.numberStyle) ?: return XCell.Text(cell.raw)
                return XCell.Number(p.value, amountFormat(p, o.numberStyle))
            }
            ColumnType.DATE -> if (o.convertDates) {
                val d = DateParser.parse(raw, o.dateOrder) ?: return XCell.Text(cell.raw)
                return XCell.Date(DateParser.toExcelSerial(d), o.dateDisplayFormat)
            }
            ColumnType.TEXT -> Unit
        }
        return XCell.Text(cell.raw)
    }

    /** Number format that displays the value the way the PDF showed it (brackets, Dr/Cr, decimals). */
    fun amountFormat(p: ParsedAmount, style: NumberStyle): String {
        val zeros = if (p.decimals > 0) "." + "0".repeat(p.decimals) else ""
        val suffix = p.drCr?.let { " \"" + it.name.lowercase().replaceFirstChar { c -> c.uppercase() } + "\"" } ?: ""
        val indian = style == NumberStyle.INDIAN && p.indianGrouping
        return when {
            // Brackets: negative values shown as (1,234.00), as on the source document.
            p.bracketed -> "#,##0$zeros$suffix;(#,##0$zeros)$suffix"
            // Indian lakh/crore grouping for positive values (the common Excel idiom).
            indian -> "[>=10000000]##\\,##\\,##\\,##0$zeros$suffix;[>=100000]##\\,##\\,##0$zeros$suffix;##,##0$zeros$suffix"
            else -> "#,##0$zeros$suffix"
        }
    }
}
