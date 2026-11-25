package com.cashbook.core

import org.w3c.dom.Element
import java.io.ByteArrayInputStream
import java.math.BigDecimal
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.time.LocalDate
import java.util.zip.ZipInputStream
import javax.xml.parsers.DocumentBuilderFactory

/**
 * Turns a downloaded bank statement file into rows of text cells for [StatementImport]. Recognised by content, not by
 * file name: Excel .xlsx (a zip), the HTML tables many banks save with an ".xls" name, and CSV / tab / semicolon text
 * (UTF-8, UTF-16 with BOM, or Windows-1252). Old binary .xls files are reported so the user can re-save them.
 */
object StatementFiles {
    fun parse(bytes: ByteArray): StatementImport.Result = StatementImport.parseRows(rows(bytes))

    fun rows(bytes: ByteArray): List<List<String>> = when {
        bytes.size >= 4 && bytes[0] == 'P'.code.toByte() && bytes[1] == 'K'.code.toByte() -> XlsxReader.rows(bytes)
        bytes.size >= 8 && bytes[0] == 0xD0.toByte() && bytes[1] == 0xCF.toByte() && bytes[2] == 0x11.toByte() && bytes[3] == 0xE0.toByte() ->
            throw StatementImport.FormatException("This is an old Excel (.xls) file. Open it and save it as .xlsx or CSV.")
        else -> decode(bytes).let { t -> if (HtmlTable.looksLike(t)) HtmlTable.rows(t) else StatementImport.splitRows(t.removePrefix("﻿")) }
    }

    /** UTF-16 when there's a BOM, UTF-8 when it's valid, otherwise Windows-1252 (older Excel CSV exports). */
    fun decode(b: ByteArray): String {
        if (b.size >= 2 && b[0] == 0xFF.toByte() && b[1] == 0xFE.toByte()) return String(b, 2, b.size - 2, Charsets.UTF_16LE)
        if (b.size >= 2 && b[0] == 0xFE.toByte() && b[1] == 0xFF.toByte()) return String(b, 2, b.size - 2, Charsets.UTF_16BE)
        return try {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(b)).toString()
        } catch (e: CharacterCodingException) { String(b, charset("windows-1252")) }
    }
}

/** Minimal .xlsx reader: the first worksheet as text, with date-formatted numbers written as dd/MM/yyyy. */
object XlsxReader {
    fun rows(bytes: ByteArray): List<List<String>> {
        val files = HashMap<String, ByteArray>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { z ->
            while (true) { val e = z.nextEntry ?: break; if (!e.isDirectory) files[e.name.removePrefix("/")] = z.readBytes() }
        }
        val sheetPath = firstSheet(files) ?: throw StatementImport.FormatException("No worksheet in this Excel file")
        val shared = files["xl/sharedStrings.xml"]?.let { sharedStrings(it) } ?: emptyList()
        val dateStyles = files["xl/styles.xml"]?.let { dateStyles(it) } ?: emptySet()
        val doc = xml(files[sheetPath]!!)
        val out = ArrayList<List<String>>()
        var lastRow = 0
        for (row in doc.getElementsByTagName("row").elements()) {
            val rIndex = row.getAttribute("r").toIntOrNull() ?: (lastRow + 1)
            while (lastRow + 1 < rIndex) { out += emptyList<String>(); lastRow++ }     // keep blank rows so row numbers match Excel
            val cells = ArrayList<String>()
            var col = 0
            for (c in row.getElementsByTagName("c").elements()) {
                val ref = c.getAttribute("r")
                val ci = if (ref.isNotEmpty()) colIndex(ref) else col
                while (cells.size < ci) cells += ""
                cells += cellText(c, shared, dateStyles)
                col = ci + 1
            }
            out += cells; lastRow = rIndex
        }
        return out
    }

    private fun cellText(c: Element, shared: List<String>, dateStyles: Set<Int>): String {
        val t = c.getAttribute("t")
        val v = c.getElementsByTagName("v").elements().firstOrNull()?.textContent ?: ""
        return when (t) {
            "s" -> v.toIntOrNull()?.let { shared.getOrNull(it) } ?: ""
            "inlineStr" -> c.getElementsByTagName("t").elements().joinToString("") { it.textContent }
            "str", "b", "e" -> v
            else -> {
                if (v.isEmpty()) return ""
                val style = c.getAttribute("s").toIntOrNull() ?: 0
                val num = v.toBigDecimalOrNull() ?: return v
                if (style in dateStyles) serialToDate(num.toDouble())?.let { DateFormatOption.DD_MM_YYYY.format(it).replace('-', '/') } ?: v
                else num.stripTrailingZeros().toPlainString()
            }
        }
    }

    /** Excel serial day (1900 system, with its 1900 leap-year quirk) → date. */
    fun serialToDate(serial: Double): LocalDate? = if (serial < 1 || serial > 2_958_465) null else LocalDate.of(1899, 12, 30).plusDays(serial.toLong())

    private fun firstSheet(files: Map<String, ByteArray>): String? {
        val wb = files["xl/workbook.xml"]?.let { xml(it) }
        val rid = wb?.getElementsByTagName("sheet")?.elements()?.firstOrNull()?.let { s ->
            s.getAttribute("r:id").ifEmpty { s.attributes.let { a -> (0 until a.length).map { a.item(it) }.firstOrNull { it.nodeName.endsWith(":id") }?.nodeValue ?: "" } }
        }
        val target = rid?.let { id -> files["xl/_rels/workbook.xml.rels"]?.let { xml(it) }?.getElementsByTagName("Relationship")?.elements()
            ?.firstOrNull { it.getAttribute("Id") == id }?.getAttribute("Target") }
        val fromRels = target?.let { if (it.startsWith("/")) it.removePrefix("/") else "xl/" + it.removePrefix("./") }
        return fromRels?.takeIf { it in files } ?: files.keys.filter { it.startsWith("xl/worksheets/sheet") && it.endsWith(".xml") }.minOrNull()
    }

    private fun sharedStrings(b: ByteArray) = xml(b).getElementsByTagName("si").elements().map { si ->
        si.getElementsByTagName("t").elements().joinToString("") { it.textContent }
    }

    /** Indexes of cell styles whose number format is a date (built-in 14–22, 45–47, or a custom code with d/m/y). */
    private fun dateStyles(b: ByteArray): Set<Int> {
        val doc = xml(b)
        val custom = doc.getElementsByTagName("numFmt").elements().associate { it.getAttribute("numFmtId").toInt() to it.getAttribute("formatCode") }
        fun isDate(id: Int) = id in 14..22 || id in 45..47 ||
            custom[id]?.replace(Regex("\"[^\"]*\"|\\[[^]]*]"), "")?.lowercase()?.let { f -> f.contains('d') || f.contains('y') || (f.contains('m') && !f.contains("0")) } == true
        val xfs = doc.getElementsByTagName("cellXfs").elements().firstOrNull()?.getElementsByTagName("xf")?.elements() ?: return emptySet()
        return xfs.mapIndexedNotNull { i, xf -> i.takeIf { isDate(xf.getAttribute("numFmtId").toIntOrNull() ?: 0) } }.toSet()
    }

    fun colIndex(ref: String): Int = ref.takeWhile { it.isLetter() }.fold(0) { acc, ch -> acc * 26 + (ch.uppercaseChar() - 'A' + 1) } - 1

    private fun xml(b: ByteArray) = DocumentBuilderFactory.newInstance().apply {
        isNamespaceAware = false
        // no DTDs / external entities from a downloaded file. Android's parser doesn't support this feature (and doesn't
        // resolve external entities anyway), so a refusal there is fine.
        runCatching { setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
        isExpandEntityReferences = false
    }.newDocumentBuilder().parse(ByteArrayInputStream(b))

    private fun org.w3c.dom.NodeList.elements(): List<Element> = (0 until length).map { item(it) }.filterIsInstance<Element>()
    private fun String.toBigDecimalOrNull() = runCatching { BigDecimal(this) }.getOrNull()
}

/** The HTML tables some banks save as ".xls": each <tr> becomes a row, each <td>/<th> a cell (tags stripped, entities decoded). */
object HtmlTable {
    fun looksLike(t: String) = t.trimStart().let { it.startsWith("<") } && Regex("<table", RegexOption.IGNORE_CASE).containsMatchIn(t)

    fun rows(html: String): List<List<String>> = Regex("<tr[^>]*>(.*?)</tr>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)).findAll(html).map { tr ->
        Regex("<t[dh][^>]*>(.*?)</t[dh]>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)).findAll(tr.groupValues[1]).map { clean(it.groupValues[1]) }.toList()
    }.toList()

    private fun clean(s: String) = s.replace(Regex("<br\\s*/?>", RegexOption.IGNORE_CASE), " ").replace(Regex("<[^>]+>"), "")
        .replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&#39;", "'")
        .replace(Regex("&#(\\d+);")) { it.groupValues[1].toInt().toChar().toString() }
        .replace(Regex("&#x([0-9a-fA-F]+);")) { it.groupValues[1].toInt(16).toChar().toString() }
        .replace(Regex("\\s+"), " ").trim()
}

/** "Lines that read like this go in that category", learned when you categorise an imported statement line. */
data class CategoryRule(val id: Long, val key: String, val categoryId: Long)

object CategoryRules {
    /** Month names change every month ("Electricity bill May" / "… June"), so they're not part of the wording. */
    private val MONTHS = setOf("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
        "JANUARY", "FEBRUARY", "MARCH", "APRIL", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")

    /** Words of letters (two or more), upper-case, without month names. */
    fun words(description: String): List<String> =
        description.uppercase().split(Regex("[^\\p{L}]+")).filter { it.length >= 2 && it !in MONTHS }

    /**
     * The stable part of a narration: its first three words of letters, upper-case, no months. Reference numbers, dates
     * and amounts change every month, the wording doesn't: "SMS CHARGES INCL GST 0525" → "SMS CHARGES INCL",
     * "UPI/ACME TRADERS/4521987/PAYMENT" → "UPI ACME TRADERS". Blank when there are no words.
     */
    fun key(description: String): String = words(description).take(3).joinToString(" ")

    /**
     * The rule whose words begin this description's words ("SMS CHARGES" fits "SMS CHARGES INCL GST"); the longest
     * such rule wins, so a specific rule beats a general one.
     */
    fun find(rules: List<CategoryRule>, description: String): CategoryRule? {
        val w = words(description)
        if (w.isEmpty()) return null
        return rules.mapNotNull { r -> r.key.split(' ').let { rk -> if (rk.size <= w.size && w.subList(0, rk.size) == rk) r to rk.size else null } }
            .maxByOrNull { it.second }?.first
    }
}
