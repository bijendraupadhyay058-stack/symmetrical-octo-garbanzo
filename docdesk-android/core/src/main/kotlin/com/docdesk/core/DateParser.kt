package com.docdesk.core

import java.time.LocalDate
import java.time.temporal.ChronoUnit

enum class DateOrder(val label: String) {
    DMY("Day/Month/Year (31/03/2025)"),
    MDY("Month/Day/Year (03/31/2025)"),
    YMD("Year-Month-Day (2025-03-31)"),
}

/** Parses the common date spellings found on Indian bank statements and invoices. */
object DateParser {
    private val months = mapOf(
        "jan" to 1, "feb" to 2, "mar" to 3, "apr" to 4, "may" to 5, "jun" to 6,
        "jul" to 7, "aug" to 8, "sep" to 9, "sept" to 9, "oct" to 10, "nov" to 11, "dec" to 12,
    )
    private val numeric = Regex("""^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})$""")
    private val named = Regex("""^(\d{1,2})[\s\-/.]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})$""")
    private val namedUs = Regex("""^([A-Za-z]{3,9})[\s\-/.]*(\d{1,2}),?[\s\-/.]*(\d{2,4})$""")

    fun parse(raw: String, order: DateOrder = DateOrder.DMY): LocalDate? {
        val s = raw.trim()
        numeric.find(s)?.let { m ->
            val (a, b, c) = m.destructured
            return when {
                a.length == 4 -> build(a.toInt(), b.toInt(), c.toInt())
                order == DateOrder.MDY -> build(year(c), a.toInt(), b.toInt())
                order == DateOrder.YMD && a.length == 2 && c.length == 2 -> build(year(a), b.toInt(), c.toInt())
                else -> build(year(c), b.toInt(), a.toInt())
            }
        }
        named.find(s)?.let { m ->
            val (d, mon, y) = m.destructured
            val mi = monthIndex(mon) ?: return null
            return build(year(y), mi, d.toInt())
        }
        namedUs.find(s)?.let { m ->
            val (mon, d, y) = m.destructured
            val mi = monthIndex(mon) ?: return null
            return build(year(y), mi, d.toInt())
        }
        return null
    }

    fun looksLikeDate(raw: String, order: DateOrder) = raw.length in 6..20 && parse(raw, order) != null

    private fun monthIndex(name: String): Int? {
        val l = name.lowercase()
        return months[l] ?: months[l.take(3)]?.takeIf { l.length == 3 || fullNames.any { f -> f.startsWith(l) } }
    }

    private val fullNames = listOf("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "sept")

    private fun year(y: String): Int {
        val n = y.toInt()
        return when (y.length) { 2 -> if (n < 70) 2000 + n else 1900 + n; 4 -> n; else -> -1 }
    }

    private fun build(y: Int, m: Int, d: Int): LocalDate? =
        if (y < 1900 || y > 2200) null else try { LocalDate.of(y, m, d) } catch (e: Exception) { null }

    /** Excel serial date (1900 date system, with Excel's leap-year bug offset). */
    fun toExcelSerial(date: LocalDate): Long = ChronoUnit.DAYS.between(LocalDate.of(1899, 12, 30), date)

    fun fromExcelSerial(serial: Double): LocalDate = LocalDate.of(1899, 12, 30).plusDays(kotlin.math.floor(serial).toLong())
}
