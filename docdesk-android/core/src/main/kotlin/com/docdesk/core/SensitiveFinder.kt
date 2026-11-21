package com.docdesk.core

enum class SensitiveKind(val label: String) {
    PAN("PAN numbers"), AADHAAR("Aadhaar numbers"), GSTIN("GSTIN"), IFSC("IFSC codes"),
    MOBILE("Mobile numbers"), EMAIL("Email addresses"), CARD("Card numbers"), ACCOUNT("Bank account numbers (9–18 digits)"),
    CUSTOM("Your search words"),
}

/** A match on a page: what it is, the text, and one rectangle per line it covers (page units). */
data class SensitiveMatch(val kind: SensitiveKind, val text: String, val page: Int, val rects: List<FloatArray>)

/**
 * Finds personal and financial identifiers in positioned page text. Numbers with a checksum
 * (Aadhaar – Verhoeff, GSTIN – mod 36, cards – Luhn) are validated, so random numbers are not
 * reported. Results are suggestions for the user to confirm before redacting.
 */
object SensitiveFinder {
    private val patterns: Map<SensitiveKind, Regex> = mapOf(
        SensitiveKind.PAN to Regex("""\b[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z]\b"""),
        SensitiveKind.GSTIN to Regex("""\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"""),
        SensitiveKind.AADHAAR to Regex("""(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)"""),
        SensitiveKind.IFSC to Regex("""\b[A-Z]{4}0[A-Z0-9]{6}\b"""),
        SensitiveKind.MOBILE to Regex("""(?<![\d+])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)"""),
        SensitiveKind.EMAIL to Regex("""\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"""),
        SensitiveKind.CARD to Regex("""(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"""),
        SensitiveKind.ACCOUNT to Regex("""(?<![\d,.])\d{9,18}(?![\d,.])"""),
    )

    fun find(page: PageText, kinds: Set<SensitiveKind>, terms: List<String> = emptyList()): List<SensitiveMatch> {
        val out = mutableListOf<SensitiveMatch>()
        for (line in LineGrouper.group(page.words)) {
            // Rebuild the line with word offsets so a match maps back to word boxes.
            val sb = StringBuilder(); val starts = IntArray(line.words.size)
            line.words.forEachIndexed { i, w -> if (i > 0) sb.append(' '); starts[i] = sb.length; sb.append(w.text) }
            val text = sb.toString()
            val taken = mutableListOf<IntRange>()
            fun add(kind: SensitiveKind, range: IntRange) {
                if (taken.any { it.first <= range.last && range.first <= it.last }) return
                taken.add(range)
                val idx = line.words.indices.filter { i -> val s = starts[i]; val e = s + line.words[i].text.length - 1; s <= range.last && range.first <= e }
                if (idx.isEmpty()) return
                val ws = idx.map { line.words[it] }
                out.add(SensitiveMatch(kind, text.substring(range), page.pageIndex, listOf(floatArrayOf(ws.minOf { it.x }, ws.minOf { it.y }, ws.maxOf { it.right }, ws.maxOf { it.bottom }))))
            }
            // Order matters: specific formats first so a GSTIN is not also reported as a PAN.
            for (kind in listOf(SensitiveKind.GSTIN, SensitiveKind.PAN, SensitiveKind.EMAIL, SensitiveKind.IFSC, SensitiveKind.AADHAAR, SensitiveKind.CARD, SensitiveKind.MOBILE, SensitiveKind.ACCOUNT)) {
                if (kind !in kinds) continue
                for (m in patterns.getValue(kind).findAll(text)) {
                    val digits = m.value.filter(Char::isDigit)
                    val ok = when (kind) {
                        SensitiveKind.AADHAAR -> digits.length == 12 && verhoeff(digits)
                        SensitiveKind.GSTIN -> gstinValid(m.value)
                        SensitiveKind.CARD -> digits.length in 13..19 && luhn(digits)
                        else -> true
                    }
                    if (ok) add(kind, m.range)
                }
            }
            if (SensitiveKind.CUSTOM in kinds || terms.isNotEmpty()) for (t in terms.map { it.trim() }.filter { it.isNotEmpty() }) {
                var i = text.indexOf(t, ignoreCase = true)
                while (i >= 0) { add(SensitiveKind.CUSTOM, i until i + t.length); i = text.indexOf(t, i + t.length, ignoreCase = true) }
            }
        }
        return out
    }

    private val vd = arrayOf(
        intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), intArrayOf(1, 2, 3, 4, 0, 6, 7, 8, 9, 5), intArrayOf(2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
        intArrayOf(3, 4, 0, 1, 2, 8, 9, 5, 6, 7), intArrayOf(4, 0, 1, 2, 3, 9, 5, 6, 7, 8), intArrayOf(5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
        intArrayOf(6, 5, 9, 8, 7, 1, 0, 4, 3, 2), intArrayOf(7, 6, 5, 9, 8, 2, 1, 0, 4, 3), intArrayOf(8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
        intArrayOf(9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
    )
    private val vp = arrayOf(
        intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), intArrayOf(1, 5, 7, 6, 2, 8, 3, 0, 9, 4), intArrayOf(5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
        intArrayOf(8, 9, 1, 6, 0, 4, 3, 5, 2, 7), intArrayOf(9, 4, 5, 3, 1, 2, 6, 8, 7, 0), intArrayOf(4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
        intArrayOf(2, 7, 9, 3, 8, 0, 6, 4, 1, 5), intArrayOf(7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
    )

    fun verhoeff(num: String): Boolean {
        var c = 0
        num.reversed().forEachIndexed { i, ch -> c = vd[c][vp[i % 8][ch - '0']] }
        return c == 0
    }

    fun luhn(num: String): Boolean {
        var sum = 0
        num.reversed().forEachIndexed { i, ch -> var d = ch - '0'; if (i % 2 == 1) { d *= 2; if (d > 9) d -= 9 }; sum += d }
        return sum % 10 == 0
    }

    fun gstinValid(g: String): Boolean {
        if (g.length != 15) return false
        val chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        var sum = 0
        for (i in 0 until 14) {
            val v = chars.indexOf(g[i]); if (v < 0) return false
            val p = v * (if (i % 2 == 0) 1 else 2)
            sum += p / 36 + p % 36
        }
        val check = (36 - sum % 36) % 36
        return chars[check] == g[14]
    }
}
