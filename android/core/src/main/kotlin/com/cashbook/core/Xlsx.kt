package com.cashbook.core

import java.io.OutputStream
import java.time.LocalDate
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Spreadsheet cell. Amounts are written as real numeric cells so they can be summed in Excel. */
sealed interface XCell {
    data class Str(val text: String, val bold: Boolean = false, val header: Boolean = false) : XCell
    /** [paise] is written exactly (e.g. 1250050 → 12500.50) using the Indian number format. */
    data class Money(val paise: Long, val bold: Boolean = false) : XCell
    data class Int(val value: Long, val bold: Boolean = false) : XCell
    data class Date(val date: LocalDate) : XCell
    data object Blank : XCell
}

class XSheet(name: String, val columnWidths: List<Double> = emptyList(), val freezeRows: kotlin.Int = 0) {
    val name: String = sanitize(name)
    val rows = ArrayList<List<XCell>>()
    fun row(vararg cells: XCell) { rows += cells.toList() }

    companion object {
        fun sanitize(n: String): String =
            n.replace(Regex("[\\\\/?*\\[\\]:]"), " ").trim().ifEmpty { "Sheet" }.take(31)
    }
}

/**
 * Minimal, dependency-free Office Open XML (.xlsx) writer. Produces files that open in
 * Microsoft Excel, Google Sheets, LibreOffice and WPS.
 */
object XlsxWriter {
    // Style indexes (see styles.xml below)
    private const val S_BOLD = 1
    private const val S_MONEY = 2
    private const val S_MONEY_BOLD = 3
    private const val S_DATE = 4
    private const val S_HEADER = 5
    private const val S_INT_BOLD = 6

    fun write(sheets: List<XSheet>, out: OutputStream) {
        require(sheets.isNotEmpty())
        val unique = LinkedHashSet<String>()
        val names = sheets.map { s ->
            var n = s.name; var i = 2
            while (!unique.add(n.lowercase())) { n = s.name.take(28) + " " + i++ }
            n
        }
        val zip = ZipOutputStream(out)
        fun put(path: String, body: String) {
            zip.putNextEntry(ZipEntry(path)); zip.write(body.toByteArray(Charsets.UTF_8)); zip.closeEntry()
        }
        put("[Content_Types].xml", buildString {
            append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">""")
            append("""<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>""")
            append("""<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>""")
            append("""<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>""")
            sheets.indices.forEach { append("""<Override PartName="/xl/worksheets/sheet${it + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>""") }
            append("</Types>")
        })
        put("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""")
        put("xl/workbook.xml", buildString {
            append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>""")
            names.forEachIndexed { i, n -> append("""<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>""") }
            append("</sheets></workbook>")
        })
        put("xl/_rels/workbook.xml.rels", buildString {
            append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">""")
            sheets.indices.forEach { append("""<Relationship Id="rId${it + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${it + 1}.xml"/>""") }
            append("""<Relationship Id="rId${sheets.size + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>""")
        })
        put("xl/styles.xml", STYLES)
        sheets.forEachIndexed { i, s -> put("xl/worksheets/sheet${i + 1}.xml", sheetXml(s)) }
        zip.finish()
        zip.flush()
    }

    private fun sheetXml(s: XSheet): String = buildString {
        append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">""")
        if (s.freezeRows > 0) {
            append("""<sheetViews><sheetView workbookViewId="0"><pane ySplit="${s.freezeRows}" topLeftCell="A${s.freezeRows + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>""")
        }
        if (s.columnWidths.isNotEmpty()) {
            append("<cols>")
            s.columnWidths.forEachIndexed { i, w -> append("""<col min="${i + 1}" max="${i + 1}" width="$w" customWidth="1"/>""") }
            append("</cols>")
        }
        append("<sheetData>")
        s.rows.forEachIndexed { r, cells ->
            append("""<row r="${r + 1}">""")
            cells.forEachIndexed { c, cell ->
                val ref = colName(c) + (r + 1)
                when (cell) {
                    is XCell.Str -> {
                        val st = when { cell.header -> S_HEADER; cell.bold -> S_BOLD; else -> 0 }
                        append("""<c r="$ref" t="inlineStr"${if (st != 0) " s=\"$st\"" else ""}><is><t xml:space="preserve">${esc(cell.text)}</t></is></c>""")
                    }
                    is XCell.Money -> append("""<c r="$ref" s="${if (cell.bold) S_MONEY_BOLD else S_MONEY}"><v>${com.cashbook.core.Money.toDecimalString(cell.paise)}</v></c>""")
                    is XCell.Int -> append("""<c r="$ref"${if (cell.bold) " s=\"$S_INT_BOLD\"" else ""}><v>${cell.value}</v></c>""")
                    is XCell.Date -> append("""<c r="$ref" s="$S_DATE"><v>${cell.date.toEpochDay() + 25569}</v></c>""")
                    XCell.Blank -> {}
                }
            }
            append("</row>")
        }
        append("</sheetData></worksheet>")
    }

    fun colName(index: kotlin.Int): String {
        var n = index + 1
        val sb = StringBuilder()
        while (n > 0) { val m = (n - 1) % 26; sb.insert(0, ('A' + m)); n = (n - 1) / 26 }
        return sb.toString()
    }

    fun esc(s: String): String {
        val sb = StringBuilder(s.length)
        for (ch in s) {
            when {
                ch == '&' -> sb.append("&amp;")
                ch == '<' -> sb.append("&lt;")
                ch == '>' -> sb.append("&gt;")
                ch == '"' -> sb.append("&quot;")
                ch == '\t' || ch == '\n' || ch == '\r' -> sb.append(ch)
                ch.code < 0x20 -> {}
                else -> sb.append(ch)
            }
        }
        return sb.toString()
    }

    // Indian grouping: 1,25,000.00 and 1,25,00,000.00
    private const val INDIAN_FMT = "[&gt;=10000000]##\\,##\\,##\\,##0.00;[&gt;=100000]##\\,##\\,##0.00;##,##0.00"
    private val STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">""" +
        """<numFmts count="2"><numFmt numFmtId="164" formatCode="$INDIAN_FMT"/><numFmt numFmtId="165" formatCode="dd\-mm\-yyyy"/></numFmts>""" +
        """<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>""" +
        """<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1A2B5C"/><bgColor indexed="64"/></patternFill></fill></fills>""" +
        """<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>""" +
        """<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>""" +
        """<cellXfs count="7">""" +
        """<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>""" +
        """<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>""" +
        """<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>""" +
        """<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>""" +
        """<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>""" +
        """<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>""" +
        """<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>""" +
        """</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>"""
}

/** Converts a [ReportDocument] into workbook sheets: Summary, one sheet per table, Transactions. */
object ReportExcel {
    fun sheets(doc: ReportDocument, fmt: DateFormatOption, currencyLabel: String): List<XSheet> {
        val l = doc.labels
        val summary = XSheet(doc.title.take(31).ifBlank { "Summary" }, listOf(34.0, 22.0))
        summary.row(XCell.Str(doc.title, bold = true))
        summary.row(XCell.Str(l.cashbook), XCell.Str(doc.cashbookName))
        summary.row(XCell.Str("Period"), XCell.Str(doc.periodLabel))
        if (doc.filtersLabel.isNotBlank()) summary.row(XCell.Str("Filters"), XCell.Str(doc.filtersLabel))
        summary.row(XCell.Str("Generated"), XCell.Str(doc.generatedAt))
        summary.row(XCell.Str("Currency"), XCell.Str(currencyLabel))
        summary.row()
        doc.summary.forEach { summary.row(XCell.Str(it.label, bold = true), toX(it.value, false)) }
        if (doc.notes.isNotEmpty()) { summary.row(); doc.notes.forEach { summary.row(XCell.Str(it)) } }

        val out = mutableListOf(summary)
        doc.tables.forEachIndexed { i, t ->
            if (t.rows.isEmpty()) return@forEachIndexed
            val sheet = XSheet(t.title ?: "Report ${i + 1}", t.columns.map { (it.weight * 11.0).coerceIn(10.0, 45.0) }, freezeRows = 1)
            sheet.rows += t.columns.map { XCell.Str(it.title, header = true) }
            t.rows.forEach { r -> sheet.rows += r.cells.map { toX(it, r.style != RowStyle.NORMAL) } }
            out += sheet
        }
        val tx = XSheet("Transactions", listOf(12.0, 11.0, 18.0, 20.0, 22.0, 20.0, 32.0, 14.0, 16.0, 14.0, 14.0, 18.0, 18.0, 14.0), freezeRows = 1)
        tx.rows += doc.exportTable.columns.map { XCell.Str(it.title, header = true) }
        doc.exportTable.rows.forEach { r -> tx.rows += r.cells.map { toX(it, false) } }
        out += tx
        return out
    }

    private fun toX(c: Cell, bold: Boolean): XCell = when (c) {
        is Cell.Text -> XCell.Str(c.value, bold = bold)
        is Cell.Amount -> XCell.Money(c.paise, bold)
        is Cell.Count -> XCell.Int(c.value.toLong(), bold)
        is Cell.Day -> XCell.Date(c.date)
        Cell.Empty -> XCell.Blank
    }
}
