package com.docdesk.core

import com.docdesk.core.Xml.attr
import com.docdesk.core.Xml.child
import com.docdesk.core.Xml.children
import java.io.InputStream

data class SheetCell(
    val display: String,
    val isNumeric: Boolean = false,
    val bold: Boolean = false,
    val italic: Boolean = false,
    val fontSizePt: Float = 11f,
    val colorHex: String? = null,
    val fillHex: String? = null,
    val align: Align? = null,
    val wrap: Boolean = false,
    val borderLeft: Boolean = false,
    val borderRight: Boolean = false,
    val borderTop: Boolean = false,
    val borderBottom: Boolean = false,
)

data class CellRange(val firstRow: Int, val firstCol: Int, val lastRow: Int, val lastCol: Int) {
    fun contains(r: Int, c: Int) = r in firstRow..lastRow && c in firstCol..lastCol

    companion object {
        /** Parses "A1:C10" (0-based result). */
        fun parse(ref: String): CellRange? {
            val clean = ref.replace("$", "").substringAfter('!')
            val parts = clean.split(':')
            val a = cellRef(parts[0]) ?: return null
            val b = if (parts.size > 1) cellRef(parts[1]) ?: return null else a
            return CellRange(minOf(a.first, b.first), minOf(a.second, b.second), maxOf(a.first, b.first), maxOf(a.second, b.second))
        }

        /** "B3" -> (row 2, col 1) */
        fun cellRef(ref: String): Pair<Int, Int>? {
            val m = Regex("""^([A-Za-z]{1,3})(\d+)$""").find(ref.trim()) ?: return null
            var col = 0
            for (ch in m.groupValues[1].uppercase()) col = col * 26 + (ch - 'A' + 1)
            return (m.groupValues[2].toInt() - 1) to (col - 1)
        }
    }
}

data class Sheet(
    val name: String,
    val cells: Map<Int, Map<Int, SheetCell>>,
    val maxRow: Int,
    val maxCol: Int,
    /** Column widths in Excel character units. */
    val columnWidths: Map<Int, Double>,
    val defaultColumnWidth: Double,
    val rowHeightsPt: Map<Int, Float>,
    val hiddenColumns: Set<Int>,
    val hiddenRows: Set<Int>,
    val merges: List<CellRange>,
    val printArea: CellRange?,
    val hidden: Boolean,
)

data class Workbook(val sheets: List<Sheet>, val warnings: List<String>)

/** Reads values and basic formatting from .xlsx files (cached results are used for formulas). */
object XlsxReader {

    private data class Xf(val numFmtId: Int, val fontId: Int, val fillId: Int, val borderId: Int, val align: Align?, val wrap: Boolean)
    private data class Font(val bold: Boolean, val italic: Boolean, val size: Float, val color: String?)
    private data class Border(val l: Boolean, val r: Boolean, val t: Boolean, val b: Boolean)

    fun read(input: InputStream): Workbook {
        val pkg = OoxmlPackage.read(input)
        val wbPath = "xl/workbook.xml"
        val wbBytes = pkg[wbPath] ?: throw UnsupportedDocumentException("This file does not contain an Excel workbook.")
        val wb = Xml.parse(wbBytes).documentElement
        val rels = pkg.relationships(wbPath)
        val date1904 = wb.child("workbookPr")?.attr("date1904")?.let { it == "1" || it == "true" } ?: false
        val shared = readSharedStrings(pkg)
        val styles = readStyles(pkg)
        val warnings = mutableListOf<String>()
        if (date1904) warnings.add("This workbook uses the 1904 date system; dates are converted accordingly.")

        val sheetEls = wb.child("sheets")?.children("sheet") ?: emptyList()
        val printAreas = HashMap<Int, CellRange>()
        wb.child("definedNames")?.children("definedName")?.forEach { dn ->
            if (dn.attr("name") == "_xlnm.Print_Area") {
                val idx = dn.attr("localSheetId")?.toIntOrNull() ?: return@forEach
                // Only the first area of a multi-area print range is used.
                CellRange.parse(dn.textContent.split(',').first())?.let { printAreas[idx] = it }
            }
        }
        var formulasWithoutValue = 0
        var unsupportedFeatures = mutableSetOf<String>()
        val sheets = sheetEls.mapIndexedNotNull { idx, s ->
            val path = rels[s.attr("id")] ?: return@mapIndexedNotNull null
            val bytes = pkg[path] ?: return@mapIndexedNotNull null
            val root = Xml.parse(bytes).documentElement
            if (root.child("drawing") != null) unsupportedFeatures.add("charts, pictures or shapes")
            if (root.child("conditionalFormatting") != null) unsupportedFeatures.add("conditional formatting")
            if (root.child("dataValidations") != null) Unit
            val cols = HashMap<Int, Double>()
            val hiddenCols = HashSet<Int>()
            root.child("cols")?.children("col")?.forEach { c ->
                val min = c.attr("min")?.toIntOrNull() ?: return@forEach
                val max = (c.attr("max")?.toIntOrNull() ?: min).coerceAtMost(min + 512)
                val w = c.attr("width")?.toDoubleOrNull()
                val hidden = c.attr("hidden") == "1" || c.attr("hidden") == "true"
                for (i in min..max) { if (w != null) cols[i - 1] = w; if (hidden) hiddenCols.add(i - 1) }
            }
            val defaultWidth = root.child("sheetFormatPr")?.attr("defaultColWidth")?.toDoubleOrNull()
                ?: root.child("sheetFormatPr")?.attr("baseColWidth")?.toDoubleOrNull()?.plus(0.71) ?: 8.43
            val cells = HashMap<Int, HashMap<Int, SheetCell>>()
            val rowHeights = HashMap<Int, Float>()
            val hiddenRows = HashSet<Int>()
            var maxRow = -1; var maxCol = -1
            root.child("sheetData")?.children("row")?.forEach { row ->
                val rIdx = (row.attr("r")?.toIntOrNull() ?: (maxRow + 2)) - 1
                row.attr("ht")?.toFloatOrNull()?.let { if (row.attr("customHeight") == "1") rowHeights[rIdx] = it }
                if (row.attr("hidden") == "1") hiddenRows.add(rIdx)
                var nextCol = 0
                row.children("c").forEach { c ->
                    val ref = c.attr("r")?.let { CellRange.cellRef(it) }
                    val col = ref?.second ?: nextCol
                    nextCol = col + 1
                    val t = c.attr("t")
                    val v = c.child("v")?.textContent
                    val hasFormula = c.child("f") != null
                    val xf = styles.xfs.getOrNull(c.attr("s")?.toIntOrNull() ?: 0)
                    var numeric = false
                    val display: String = when (t) {
                        "s" -> v?.toIntOrNull()?.let { shared.getOrNull(it) } ?: ""
                        "inlineStr" -> c.child("is")?.let { inlineText(it) } ?: ""
                        "str" -> v ?: ""
                        "b" -> if (v == "1") "TRUE" else "FALSE"
                        "e" -> v ?: "#ERROR"
                        else -> if (v.isNullOrEmpty()) "" else {
                            val d = v.toDoubleOrNull()
                            if (d == null) v else {
                                numeric = true
                                val fmtCode = xf?.let { styles.numFmts[it.numFmtId] ?: BUILTIN[it.numFmtId] } ?: "General"
                                NumberFormatter.format(d, fmtCode, date1904)
                            }
                        }
                    }
                    if (hasFormula && v.isNullOrEmpty()) formulasWithoutValue++
                    val font = xf?.let { styles.fonts.getOrNull(it.fontId) }
                    val border = xf?.let { styles.borders.getOrNull(it.borderId) }
                    if (display.isNotEmpty() || (xf != null && (xf.fillId > 1 || (xf.borderId > 0 && border != null && (border.l || border.r || border.t || border.b))))) {
                        cells.getOrPut(rIdx) { HashMap() }[col] = SheetCell(
                            display, numeric, font?.bold ?: false, font?.italic ?: false, font?.size ?: 11f, font?.color,
                            xf?.let { styles.fills.getOrNull(it.fillId) }, xf?.align, xf?.wrap ?: false,
                            border?.l ?: false, border?.r ?: false, border?.t ?: false, border?.b ?: false,
                        )
                        if (rIdx > maxRow) maxRow = rIdx
                        if (col > maxCol) maxCol = col
                    }
                }
            }
            val merges = root.child("mergeCells")?.children("mergeCell")?.mapNotNull { m -> m.attr("ref")?.let { CellRange.parse(it) } } ?: emptyList()
            val hidden = s.attr("state").let { it == "hidden" || it == "veryHidden" }
            Sheet(s.attr("name") ?: "Sheet${idx + 1}", cells, maxRow, maxCol, cols, defaultWidth, rowHeights, hiddenCols, hiddenRows, merges, printAreas[idx], hidden)
        }
        if (formulasWithoutValue > 0) warnings.add("$formulasWithoutValue formula cell(s) have no saved result and will appear empty. Open and re-save the file in Excel to store results.")
        if (unsupportedFeatures.isNotEmpty()) warnings.add("Not reproduced in the PDF: ${unsupportedFeatures.joinToString(", ")}.")
        if (styles.fonts.isNotEmpty()) warnings.add("Fonts are replaced with the phone's standard font, so text widths may differ slightly from Excel.")
        return Workbook(sheets, warnings)
    }

    private fun inlineText(e: org.w3c.dom.Element): String {
        e.child("t")?.let { return it.textContent }
        return e.children("r").joinToString("") { it.child("t")?.textContent ?: "" }
    }

    private fun readSharedStrings(pkg: OoxmlPackage): List<String> {
        val bytes = pkg["xl/sharedStrings.xml"] ?: return emptyList()
        return Xml.parse(bytes).documentElement.children("si").map { inlineText(it) }
    }

    private class Styles(val xfs: List<Xf>, val numFmts: Map<Int, String>, val fonts: List<Font>, val fills: List<String?>, val borders: List<Border>)

    private fun readStyles(pkg: OoxmlPackage): Styles {
        val bytes = pkg["xl/styles.xml"] ?: return Styles(emptyList(), emptyMap(), emptyList(), emptyList(), emptyList())
        val root = Xml.parse(bytes).documentElement
        val numFmts = root.child("numFmts")?.children("numFmt")?.associate { (it.attr("numFmtId")?.toIntOrNull() ?: -1) to (it.attr("formatCode") ?: "General") } ?: emptyMap()
        val fonts = root.child("fonts")?.children("font")?.map { f ->
            fun has(tag: String) = f.child(tag)?.let { val v = it.attr("val"); v == null || v == "1" || v == "true" } ?: false
            Font(has("b"), has("i"), f.child("sz")?.attr("val")?.toFloatOrNull() ?: 11f, f.child("color")?.attr("rgb")?.takeLast(6)?.takeIf { it.length == 6 && it != "000000" })
        } ?: emptyList()
        val fills = root.child("fills")?.children("fill")?.map { f ->
            val pf = f.child("patternFill")
            if (pf?.attr("patternType") == "solid") pf.child("fgColor")?.attr("rgb")?.takeLast(6)?.takeIf { it.length == 6 } else null
        } ?: emptyList()
        val borders = root.child("borders")?.children("border")?.map { b ->
            fun side(tag: String) = b.child(tag)?.attr("style")?.let { it != "none" } ?: false
            Border(side("left") || side("start"), side("right") || side("end"), side("top"), side("bottom"))
        } ?: emptyList()
        val xfs = root.child("cellXfs")?.children("xf")?.map { x ->
            val al = x.child("alignment")
            val align = when (al?.attr("horizontal")) { "center", "centerContinuous" -> Align.CENTER; "right" -> Align.RIGHT; "left" -> Align.LEFT; "justify" -> Align.JUSTIFY; else -> null }
            Xf(x.attr("numFmtId")?.toIntOrNull() ?: 0, x.attr("fontId")?.toIntOrNull() ?: 0, x.attr("fillId")?.toIntOrNull() ?: 0, x.attr("borderId")?.toIntOrNull() ?: 0, align, al?.attr("wrapText") == "1")
        } ?: emptyList()
        return Styles(xfs, numFmts, fonts, fills, borders)
    }

    val BUILTIN = mapOf(
        0 to "General", 1 to "0", 2 to "0.00", 3 to "#,##0", 4 to "#,##0.00", 9 to "0%", 10 to "0.00%", 11 to "0.00E+00",
        14 to "dd-mm-yyyy", 15 to "d-mmm-yy", 16 to "d-mmm", 17 to "mmm-yy", 18 to "h:mm AM/PM", 19 to "h:mm:ss AM/PM",
        20 to "h:mm", 21 to "h:mm:ss", 22 to "dd-mm-yyyy h:mm", 37 to "#,##0 ;(#,##0)", 38 to "#,##0 ;[Red](#,##0)",
        39 to "#,##0.00;(#,##0.00)", 40 to "#,##0.00;[Red](#,##0.00)", 45 to "mm:ss", 46 to "[h]:mm:ss", 47 to "mmss.0", 48 to "##0.0E+0", 49 to "@",
    )
}

/** Renders a numeric cell value with an Excel number format code (common subset). */
object NumberFormatter {
    private val monthsShort = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    private val monthsLong = listOf("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")

    fun format(value: Double, code: String, date1904: Boolean = false): String {
        if (code.equals("General", true) || code.isBlank()) return general(value)
        if (code == "@") return general(value)
        val sections = splitSections(code)
        // Conditional sections like [>=100000] (used for Indian grouping) are evaluated in order.
        val conditional = sections.any { condition(it) != null }
        val section: String
        var v = value
        if (conditional) {
            section = sections.firstOrNull { s -> condition(s)?.invoke(value) ?: false }
                ?: sections.lastOrNull { condition(it) == null } ?: sections.last()
        } else {
            section = when {
                value < 0 && sections.size >= 2 -> { v = -value; sections[1] }
                value == 0.0 && sections.size >= 3 -> sections[2]
                else -> sections[0]
            }
        }
        val clean = section.replace(Regex("""\[(?:Red|Black|Blue|Green|White|Yellow|Cyan|Magenta|Color\d+|[<>=]+-?[\d.]+)]""", RegexOption.IGNORE_CASE), "")
            .replace(Regex("""\[\$([^\]-]*)(?:-[^\]]*)?]"""), "$1")
        if (isDate(clean)) {
            return formatDate(if (date1904) value + 1462 else value, clean)
        }
        return formatNumber(v, clean, negativeHandled = v != value)
    }

    private fun condition(section: String): ((Double) -> Boolean)? {
        val m = Regex("""\[([<>=]+)(-?[\d.]+)]""").find(section) ?: return null
        val n = m.groupValues[2].toDoubleOrNull() ?: return null
        return when (m.groupValues[1]) {
            ">=" -> { x -> x >= n }; ">" -> { x -> x > n }; "<=" -> { x -> x <= n }; "<" -> { x -> x < n }; "=" -> { x -> x == n }; "<>" -> { x -> x != n }
            else -> null
        }
    }

    private fun splitSections(code: String): List<String> {
        val out = mutableListOf<String>(); val sb = StringBuilder(); var q = false; var esc = false
        for (ch in code) {
            when {
                esc -> { sb.append(ch); esc = false }
                ch == '\\' -> { sb.append(ch); esc = true }
                ch == '"' -> { q = !q; sb.append(ch) }
                ch == ';' && !q -> { out.add(sb.toString()); sb.clear() }
                else -> sb.append(ch)
            }
        }
        out.add(sb.toString())
        return out
    }

    private fun isDate(code: String): Boolean {
        val stripped = code.replace(Regex(""""[^"]*""""), "").replace(Regex("""\\."""), "")
        return stripped.any { it in "dDyY" } || (stripped.contains('m', true) && (stripped.contains('h', true) || stripped.contains('s', true))) ||
            Regex("""(?i)^m{1,5}[-/ ]""").containsMatchIn(stripped)
    }

    fun general(v: Double): String {
        if (v == Math.floor(v) && kotlin.math.abs(v) < 1e15) return v.toLong().toString()
        val s = java.math.BigDecimal(v).round(java.math.MathContext(11)).stripTrailingZeros().toPlainString()
        return if (s.length > 15) String.format(java.util.Locale.ROOT, "%.5E", v) else s
    }

    private fun formatNumber(value: Double, code: String, negativeHandled: Boolean): String {
        // Split into prefix literal / numeric pattern / suffix literal.
        var percent = false
        val literalPrefix = StringBuilder(); val literalSuffix = StringBuilder(); val pattern = StringBuilder()
        var i = 0; var seenDigit = false
        while (i < code.length) {
            val ch = code[i]
            when {
                ch == '"' -> { val end = code.indexOf('"', i + 1).let { if (it < 0) code.length else it }; (if (seenDigit) literalSuffix else literalPrefix).append(code.substring(i + 1, end)); i = end }
                ch == '\\' && i + 1 < code.length -> { i++; val c = code[i]; if (seenDigit && (c == ',')) pattern.append(',') else (if (seenDigit) literalSuffix else literalPrefix).append(c) }
                ch == '_' -> { i++; (if (seenDigit) literalSuffix else literalPrefix).append(' ') }
                ch == '*' -> i++
                ch == '%' -> { percent = true; literalSuffix.append('%') }
                ch in "0#?.,," -> { seenDigit = true; pattern.append(ch) }
                ch == 'E' || ch == 'e' -> return String.format(java.util.Locale.ROOT, "%.2E", value)
                ch == '@' -> Unit
                else -> (if (seenDigit) literalSuffix else literalPrefix).append(ch)
            }
            i++
        }
        var v = if (percent) value * 100 else value
        val p = pattern.toString()
        if (p.isEmpty()) return literalPrefix.toString() + literalSuffix
        val decIdx = p.indexOf('.')
        val intPat = if (decIdx >= 0) p.substring(0, decIdx) else p
        val decPat = if (decIdx >= 0) p.substring(decIdx + 1).filter { it in "0#?" } else ""
        // Trailing commas scale by thousands.
        var scale = 0
        var ip = intPat
        while (ip.endsWith(",")) { scale++; ip = ip.dropLast(1) }
        repeat(scale) { v /= 1000.0 }
        val grouping = ip.contains(',')
        val indian = Regex("""#{2},#{2},""").containsMatchIn(intPat) || intPat.contains("##,##,##")
        val minInt = ip.count { it == '0' }
        val neg = v < 0 && !negativeHandled
        val abs = kotlin.math.abs(v)
        val bd = java.math.BigDecimal(abs).setScale(decPat.length, java.math.RoundingMode.HALF_UP)
        var intStr = bd.toBigInteger().toString()
        var fracStr = if (decPat.isNotEmpty()) bd.toPlainString().substringAfter('.', "").padEnd(decPat.length, '0') else ""
        // Optional decimals (#) drop trailing zeros.
        val requiredDec = decPat.count { it == '0' }
        while (fracStr.length > requiredDec && fracStr.endsWith('0')) fracStr = fracStr.dropLast(1)
        if (intStr == "0" && minInt == 0) intStr = ""
        intStr = intStr.padStart(minInt, '0')
        if (grouping && intStr.length > 3) {
            intStr = if (indian) AmountParser.formatIndian(java.math.BigDecimal(intStr), 0) else intStr.reversed().chunked(3).joinToString(",").reversed()
        }
        val num = intStr + if (fracStr.isNotEmpty() || (decIdx >= 0 && requiredDec > 0)) ".$fracStr" else ""
        return (if (neg) "-" else "") + literalPrefix + num + literalSuffix
    }

    private fun formatDate(serial: Double, code: String): String {
        val date = DateParser.fromExcelSerial(serial)
        val frac = serial - kotlin.math.floor(serial)
        var secs = Math.round(frac * 86400).toInt()
        val hh = secs / 3600; secs %= 3600; val mi = secs / 60; val ss = secs % 60
        val ampm = code.contains("AM/PM", true) || code.contains("A/P", true)
        val out = StringBuilder()
        val tokens = Regex("""(?i)"[^"]*"|\\.|yyyy|yy|mmmmm|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|AM/PM|A/P|.""").findAll(code).map { it.value }.toList()
        for ((idx, tk) in tokens.withIndex()) {
            val lower = tk.lowercase()
            // "m" after "h" or before "s" means minutes.
            val minuteContext = (tokens.subList(0, idx).lastOrNull { it.lowercase().startsWith("h") || it.lowercase().startsWith("d") || it.lowercase().startsWith("y") }?.lowercase()?.startsWith("h") == true) ||
                tokens.drop(idx + 1).firstOrNull { it.lowercase().let { l -> l.startsWith("s") || l.startsWith("d") || l.startsWith("y") || l.startsWith("h") } }?.lowercase()?.startsWith("s") == true
            when {
                tk.startsWith("\"") -> out.append(tk.trim('"'))
                tk.startsWith("\\") -> out.append(tk.drop(1))
                lower == "yyyy" -> out.append(date.year)
                lower == "yy" -> out.append("%02d".format(date.year % 100))
                lower == "mmmmm" -> out.append(monthsLong[date.monthValue - 1].first())
                lower == "mmmm" -> out.append(monthsLong[date.monthValue - 1])
                lower == "mmm" -> out.append(monthsShort[date.monthValue - 1])
                lower == "mm" -> out.append(if (minuteContext) "%02d".format(mi) else "%02d".format(date.monthValue))
                lower == "m" -> out.append(if (minuteContext) mi.toString() else date.monthValue.toString())
                lower == "dddd" -> out.append(date.dayOfWeek.getDisplayName(java.time.format.TextStyle.FULL, java.util.Locale.ENGLISH))
                lower == "ddd" -> out.append(date.dayOfWeek.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH))
                lower == "dd" -> out.append("%02d".format(date.dayOfMonth))
                lower == "d" -> out.append(date.dayOfMonth)
                lower == "hh" -> out.append("%02d".format(if (ampm) ((hh + 11) % 12 + 1) else hh))
                lower == "h" -> out.append(if (ampm) ((hh + 11) % 12 + 1) else hh)
                lower == "ss" -> out.append("%02d".format(ss))
                lower == "s" -> out.append(ss)
                lower == "am/pm" -> out.append(if (hh < 12) "AM" else "PM")
                lower == "a/p" -> out.append(if (hh < 12) "A" else "P")
                else -> out.append(tk)
            }
        }
        return out.toString()
    }
}
