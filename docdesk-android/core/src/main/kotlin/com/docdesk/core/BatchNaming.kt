package com.docdesk.core

import java.time.LocalDate

/** Output names for batch jobs from a pattern such as "{name} - {action} {n}". */
object BatchNaming {
    const val DEFAULT = "{name} ({action})"
    val tokens = listOf("{name}" to "original file name", "{n}" to "number in the list (01, 02…)", "{date}" to "today, e.g. 2025-11-21", "{action}" to "what was done, e.g. compressed", "{part}" to "part number when splitting")

    /** Builds a safe file name (without extension). Unknown text is kept; characters not allowed in file names become "_". */
    fun name(pattern: String, original: String, index: Int, total: Int, action: String, date: LocalDate, part: Int? = null): String {
        val width = maxOf(2, total.toString().length)
        var s = pattern.ifBlank { DEFAULT }
            .replace("{name}", original).replace("{n}", (index + 1).toString().padStart(width, '0'))
            .replace("{date}", date.toString()).replace("{action}", action)
            .replace("{part}", part?.toString() ?: "")
        if (part != null && !pattern.contains("{part}")) s += " part $part"
        s = s.replace(Regex("""[\\/:*?"<>|\u0000-\u001f]"""), "_").replace(Regex("""\s+"""), " ").trim().trim('.')
        return s.ifEmpty { original }.take(150)
    }

    /** Makes names unique within one batch by adding " (2)", " (3)"… before the extension. */
    fun unique(names: List<String>): List<String> {
        val seen = HashMap<String, Int>()
        return names.map { n ->
            val key = n.lowercase()
            val c = (seen[key] ?: 0) + 1; seen[key] = c
            if (c == 1) n else n.substringBeforeLast('.', n) + " ($c)" + (if (n.contains('.')) "." + n.substringAfterLast('.') else "")
        }
    }
}
