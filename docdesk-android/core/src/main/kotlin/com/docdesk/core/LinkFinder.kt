package com.docdesk.core

/** A clickable target found in page text, with the rectangles (page units, top-left origin) it covers. */
data class FoundLink(val kind: Kind, val text: String, val target: String, val rects: List<FloatArray>) {
    enum class Kind { WEB, EMAIL, PHONE }
}

/** Finds web addresses, e-mail addresses and phone numbers in positioned text. */
object LinkFinder {
    private val email = Regex("""(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}(?![\w@])""")
    private val tlds = "com|org|net|in|co|gov|edu|io|info|biz|app|dev|uk|us|me|ai|nic|bank|int|eu|de|ca|au|sg|ae"
    private val web = Regex(
        """(?<![\w@./-])((https?://|www\.)[^\s<>"]+|[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.($tlds)(\.[a-z]{2})?(/[^\s<>"]*)?)(?![\w@])""",
        RegexOption.IGNORE_CASE,
    )
    // Indian mobiles (+91 / 0 prefix optional, 10 digits starting 6-9, may be split 5+5), landlines with STD code, toll-free 1800.
    private val phone = Regex("""(?<![\w+])(\+91[\s-]?|0)?([6-9]\d{4}[\s-]?\d{5}|[6-9]\d{9}|1800[\s-]?\d{3}[\s-]?\d{4}|0?\d{2,4}[\s-]\d{6,8})(?![\w])""")

    fun find(words: List<TextWord>, kinds: Set<FoundLink.Kind> = FoundLink.Kind.entries.toSet()): List<FoundLink> {
        val out = mutableListOf<FoundLink>()
        for (line in LineGrouper.group(words)) {
            // Line text with the character range of every word.
            val sb = StringBuilder(); val ranges = ArrayList<IntRange>()
            line.words.forEachIndexed { i, w -> if (i > 0) sb.append(' '); val s = sb.length; sb.append(w.text); ranges.add(s until sb.length) }
            val text = sb.toString()
            val taken = BooleanArray(text.length)
            fun add(kind: FoundLink.Kind, m: MatchResult, target: String) {
                var r = m.range
                if ((r.first..r.last).any { taken[it] }) return
                for (k in r) taken[k] = true
                val rects = ArrayList<FloatArray>()
                line.words.forEachIndexed { i, w ->
                    val wr = ranges[i]
                    val a = maxOf(wr.first, r.first); val b = minOf(wr.last, r.last)
                    if (a > b) return@forEachIndexed
                    val n = wr.last - wr.first + 1
                    val x0 = w.x + w.width * (a - wr.first) / n; val x1 = w.x + w.width * (b - wr.first + 1) / n
                    rects.add(floatArrayOf(x0, w.y, x1, w.bottom))
                }
                if (rects.isNotEmpty()) out.add(FoundLink(kind, m.value, target, mergeRects(rects)))
            }
            if (FoundLink.Kind.EMAIL in kinds) email.findAll(text).forEach { add(FoundLink.Kind.EMAIL, it, "mailto:" + it.value) }
            if (FoundLink.Kind.WEB in kinds) web.findAll(text).forEach { m0 ->
                val trimmed = m0.value.trimEnd('.', ',', ';', ':', ')', ']', '\'', '"', '!', '?')
                if (trimmed.length < 4 || !trimmed.contains('.')) return@forEach
                if (trimmed.contains('@')) return@forEach
                // Numbers like 1.5.2024 or 12.50 are not domains.
                if (trimmed.substringBefore('/').split('.').last().all { it.isDigit() }) return@forEach
                val m = object : MatchResult by m0 { override val range = m0.range.first until m0.range.first + trimmed.length; override val value = trimmed }
                val url = if (Regex("^https?://", RegexOption.IGNORE_CASE).containsMatchIn(trimmed)) trimmed else "https://$trimmed"
                add(FoundLink.Kind.WEB, m, url)
            }
            if (FoundLink.Kind.PHONE in kinds) phone.findAll(text).forEach { m ->
                val digits = m.value.filter { it.isDigit() || it == '+' }
                val n = digits.trimStart('+').let { if (it.startsWith("91") && it.length == 12) it.drop(2) else it.trimStart('0') }
                if (n.length !in 10..11) return@forEach
                add(FoundLink.Kind.PHONE, m, "tel:" + digits)
            }
        }
        return out
    }

    /** Joins rectangles on the same line that touch, so a link spanning several words is one box. */
    private fun mergeRects(r: List<FloatArray>): List<FloatArray> {
        val out = ArrayList<FloatArray>()
        for (x in r.sortedBy { it[0] }) {
            val last = out.lastOrNull()
            if (last != null && x[0] - last[2] < (last[3] - last[1]) && kotlin.math.abs(x[1] - last[1]) < (last[3] - last[1]) / 2)
                out[out.size - 1] = floatArrayOf(last[0], minOf(last[1], x[1]), maxOf(last[2], x[2]), maxOf(last[3], x[3]))
            else out.add(x)
        }
        return out
    }
}
