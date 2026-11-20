package com.docdesk.core

import java.io.OutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** A minimal, dependency-free writer for Office Open XML spreadsheets (.xlsx). */
sealed class XCell {
    data class Text(val value: String) : XCell()
    data class Number(val value: java.math.BigDecimal, val format: String? = null) : XCell()
    data class Date(val serial: Long, val format: String = "dd-mm-yyyy") : XCell()
    data object Blank : XCell()
}

data class XStyledCell(val cell: XCell, val bold: Boolean = false, val highlight: Boolean = false, val wrap: Boolean = false)

data class XSheet(
    val name: String,
    val rows: List<List<XStyledCell>>,
    val columnWidths: List<Double> = emptyList(),
    val freezeTopRow: Boolean = false,
)

object XlsxWriter {

    fun write(sheets: List<XSheet>, out: OutputStream) {
        require(sheets.isNotEmpty()) { "A workbook needs at least one sheet" }
        val names = uniqueSheetNames(sheets.map { it.name })
        val styles = StyleTable()
        // Pre-register styles so sheet XML can reference indices.
        val sheetXml = sheets.map { sheetXml(it, styles) }
        ZipOutputStream(out).use { zip ->
            fun put(path: String, content: String) {
                zip.putNextEntry(ZipEntry(path)); zip.write(content.toByteArray(Charsets.UTF_8)); zip.closeEntry()
            }
            put("[Content_Types].xml", buildString {
                append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">""")
                append("""<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>""")
                append("""<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>""")
                append("""<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>""")
                sheets.indices.forEach { append("""<Override PartName="/xl/worksheets/sheet${it + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>""") }
                append("""<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>""")
                append("</Types>")
            })
            put("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>""")
            put("docProps/app.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>DocDesk</Application></Properties>""")
            put("xl/workbook.xml", buildString {
                append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>""")
                names.forEachIndexed { i, n -> append("""<sheet name="${Xml.esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>""") }
                append("</sheets></workbook>")
            })
            put("xl/_rels/workbook.xml.rels", buildString {
                append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">""")
                sheets.indices.forEach { append("""<Relationship Id="rId${it + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${it + 1}.xml"/>""") }
                append("""<Relationship Id="rId${sheets.size + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>""")
                append("</Relationships>")
            })
            put("xl/styles.xml", styles.xml())
            sheetXml.forEachIndexed { i, x -> put("xl/worksheets/sheet${i + 1}.xml", x) }
        }
    }

    fun uniqueSheetNames(names: List<String>): List<String> {
        val used = HashSet<String>()
        return names.map { raw ->
            var base = raw.replace(Regex("""[\[\]:*?/\\]"""), " ").trim().trim('\'').ifEmpty { "Sheet" }.take(31)
            var name = base
            var n = 2
            while (!used.add(name.lowercase())) {
                val suffix = " ($n)"; n++
                name = base.take(31 - suffix.length) + suffix
            }
            name
        }
    }

    fun columnName(index: Int): String {
        var i = index + 1
        val sb = StringBuilder()
        while (i > 0) { val r = (i - 1) % 26; sb.append('A' + r); i = (i - 1) / 26 }
        return sb.reverse().toString()
    }

    private fun sheetXml(sheet: XSheet, styles: StyleTable): String = buildString {
        append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">""")
        if (sheet.freezeTopRow && sheet.rows.size > 1) {
            append("""<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>""")
        }
        if (sheet.columnWidths.isNotEmpty()) {
            append("<cols>")
            sheet.columnWidths.forEachIndexed { i, w -> append("""<col min="${i + 1}" max="${i + 1}" width="${"%.1f".format(java.util.Locale.ROOT, w)}" customWidth="1"/>""") }
            append("</cols>")
        }
        append("<sheetData>")
        sheet.rows.forEachIndexed { ri, row ->
            append("""<row r="${ri + 1}">""")
            row.forEachIndexed { ci, sc ->
                val ref = columnName(ci) + (ri + 1)
                val fmt = when (val c = sc.cell) { is XCell.Number -> c.format; is XCell.Date -> c.format; else -> null }
                val s = styles.index(fmt, sc.bold, sc.highlight, sc.wrap || (sc.cell as? XCell.Text)?.value?.contains('\n') == true)
                val sAttr = if (s != 0) """ s="$s"""" else ""
                when (val c = sc.cell) {
                    is XCell.Text -> append("""<c r="$ref" t="inlineStr"$sAttr><is><t xml:space="preserve">${Xml.esc(c.value)}</t></is></c>""")
                    is XCell.Number -> append("""<c r="$ref"$sAttr><v>${c.value.toPlainString()}</v></c>""")
                    is XCell.Date -> append("""<c r="$ref"$sAttr><v>${c.serial}</v></c>""")
                    XCell.Blank -> if (s != 0) append("""<c r="$ref"$sAttr/>""")
                }
            }
            append("</row>")
        }
        append("</sheetData>")
        append("""<pageMargins left="0.5" right="0.5" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>""")
        append("</worksheet>")
    }

    private class StyleTable {
        private val formats = LinkedHashMap<String, Int>() // code -> numFmtId (custom ids from 164)
        private val xfs = mutableListOf(Key(0, false, false, false))

        data class Key(val numFmtId: Int, val bold: Boolean, val fill: Boolean, val wrap: Boolean)

        fun index(format: String?, bold: Boolean, fill: Boolean, wrap: Boolean): Int {
            val id = when (format) {
                null -> 0
                "0" -> 1
                "0.00" -> 2
                "#,##0" -> 3
                "#,##0.00" -> 4
                else -> formats.getOrPut(format) { 164 + formats.size }
            }
            val key = Key(id, bold, fill, wrap)
            val i = xfs.indexOf(key)
            if (i >= 0) return i
            xfs.add(key)
            return xfs.lastIndex
        }

        fun xml(): String = buildString {
            append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">""")
            if (formats.isNotEmpty()) {
                append("""<numFmts count="${formats.size}">""")
                formats.forEach { (code, id) -> append("""<numFmt numFmtId="$id" formatCode="${Xml.esc(code)}"/>""") }
                append("</numFmts>")
            }
            append("""<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>""")
            append("""<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFF2B3"/><bgColor indexed="64"/></patternFill></fill></fills>""")
            append("""<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>""")
            append("""<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>""")
            append("""<cellXfs count="${xfs.size}">""")
            for (k in xfs) {
                append("""<xf numFmtId="${k.numFmtId}" fontId="${if (k.bold) 1 else 0}" fillId="${if (k.fill) 2 else 0}" borderId="0" xfId="0"""")
                if (k.numFmtId != 0) append(""" applyNumberFormat="1"""")
                if (k.bold) append(""" applyFont="1"""")
                if (k.fill) append(""" applyFill="1"""")
                if (k.wrap) append(""" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>""") else append("/>")
            }
            append("</cellXfs>")
            append("""<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>""")
            append("</styleSheet>")
        }
    }
}
