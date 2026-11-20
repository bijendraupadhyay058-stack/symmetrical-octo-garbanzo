package com.docdesk.core

import java.math.BigDecimal

enum class NumberStyle(val label: String) {
    INDIAN("Indian (1,23,456.78)"),
    INTERNATIONAL("International (123,456.78)"),
    EUROPEAN("European (123.456,78)"),
}

enum class DrCr { DR, CR }

/**
 * A parsed money value. [value] is signed: amounts written with a leading minus, a trailing
 * minus or in brackets are negative. A Dr/Cr marker is kept separately and does NOT change the
 * sign, because whether "Dr" means negative depends on whose books the statement is from.
 */
data class ParsedAmount(
    val value: BigDecimal,
    val bracketed: Boolean,
    val drCr: DrCr?,
    val decimals: Int,
    val indianGrouping: Boolean,
    val raw: String,
)

object AmountParser {
    private val currencyPrefix = Regex("""^(₹|rs\.?|inr|\$|usd|€|eur|£)\s*""", RegexOption.IGNORE_CASE)
    private val currencySuffix = Regex("""\s*(₹|rs\.?|inr)$""", RegexOption.IGNORE_CASE)
    private val drCrSuffix = Regex("""\s*\(?\s*(dr|cr)\.?\s*\)?$""", RegexOption.IGNORE_CASE)

    /**
     * Parses [raw] as an amount, or returns null if it is not unambiguously an amount.
     * Values that look like identifiers (leading zeros, long digit strings without separators,
     * mixed letters) are rejected so that reference numbers are never turned into numbers.
     */
    fun parse(raw: String, style: NumberStyle = NumberStyle.INDIAN): ParsedAmount? {
        var s = raw.trim().replace(' ', ' ').replace('−', '-')
        if (s.isEmpty()) return null

        var drCr: DrCr? = null
        drCrSuffix.find(s)?.let { m ->
            drCr = if (m.groupValues[1].equals("dr", true)) DrCr.DR else DrCr.CR
            s = s.substring(0, m.range.first).trim()
        }
        var negative = false
        var bracketed = false
        if (s.startsWith("(") && s.endsWith(")")) {
            bracketed = true; negative = true; s = s.substring(1, s.length - 1).trim()
        }
        if (s.startsWith("-")) { negative = !negative; s = s.substring(1).trim() }
        if (s.startsWith("+")) s = s.substring(1).trim()
        s = currencyPrefix.replace(s, "")
        s = currencySuffix.replace(s, "")
        if (s.startsWith("-")) { negative = !negative; s = s.substring(1).trim() }
        if (s.endsWith("-")) { negative = !negative; s = s.dropLast(1).trim() }
        if (s.isEmpty() || !s[0].isDigit() && s[0] != '.' && s[0] != ',') return null

        val (decimalSep, groupSep) = if (style == NumberStyle.EUROPEAN) ',' to '.' else '.' to ','
        if (s.any { !it.isDigit() && it != decimalSep && it != groupSep && it != ' ' }) return null
        s = s.replace(" ", "")

        val decIdx = s.lastIndexOf(decimalSep)
        val intPart = if (decIdx >= 0) s.substring(0, decIdx) else s
        val fracPart = if (decIdx >= 0) s.substring(decIdx + 1) else ""
        if (fracPart.contains(groupSep) || fracPart.contains(decimalSep)) return null
        if (decIdx >= 0 && fracPart.isEmpty()) return null
        if (intPart.isEmpty() && fracPart.isEmpty()) return null

        var indian = false
        if (intPart.contains(groupSep)) {
            val groups = intPart.split(groupSep)
            if (groups.any { it.isEmpty() || !it.all(Char::isDigit) }) return null
            val last = groups.last()
            val middle = groups.drop(1).dropLast(1)
            if (last.length != 3 || groups.first().length !in 1..3) return null
            when {
                middle.all { it.length == 3 } -> Unit
                middle.all { it.length == 2 } && groups.first().length in 1..2 -> indian = true
                else -> return null
            }
            if (style == NumberStyle.INTERNATIONAL && indian) return null
        } else {
            if (!intPart.all(Char::isDigit)) return null
            // Leading zeros or very long digit strings without separators look like
            // account/reference numbers; keep them as text.
            if (intPart.length > 1 && intPart.startsWith("0")) return null
            if (intPart.length > 12) return null
        }
        val plain = intPart.replace(groupSep.toString(), "").ifEmpty { "0" } + if (fracPart.isNotEmpty()) ".$fracPart" else ""
        val value = try { BigDecimal(plain) } catch (e: NumberFormatException) { return null }
        return ParsedAmount(if (negative) value.negate() else value, bracketed, drCr, fracPart.length, indian, raw)
    }

    /** True when the text has an explicit amount shape (decimals or grouping), not a bare integer. */
    fun looksLikeMoney(raw: String, style: NumberStyle): Boolean {
        val p = parse(raw, style) ?: return false
        return p.decimals > 0 || raw.contains(if (style == NumberStyle.EUROPEAN) '.' else ',') || p.drCr != null || p.bracketed
    }

    /** Formats with Indian digit grouping: 1234567.5 -> "12,34,567.50". */
    fun formatIndian(v: BigDecimal, decimals: Int = 2): String {
        val neg = v.signum() < 0
        val s = v.abs().setScale(decimals, java.math.RoundingMode.HALF_UP).toPlainString()
        val int = s.substringBefore('.')
        val frac = if (decimals > 0) "." + s.substringAfter('.') else ""
        val grouped = if (int.length <= 3) int else {
            val head = int.dropLast(3)
            head.reversed().chunked(2).joinToString(",").reversed() + "," + int.takeLast(3)
        }
        return (if (neg) "-" else "") + grouped + frac
    }
}
