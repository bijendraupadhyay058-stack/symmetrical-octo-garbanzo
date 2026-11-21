package com.docdesk.core

/** Groups consecutive pages so each part stays under a size limit (sizes are estimates in bytes). */
object SizeSplitter {
    /** Greedy: keep adding pages while the estimate fits; a page larger than the limit gets its own part. */
    fun groups(pageSizes: List<Long>, limit: Long, overhead: Long = 0): List<List<Int>> {
        val out = mutableListOf<List<Int>>()
        var cur = mutableListOf<Int>(); var used = overhead
        pageSizes.forEachIndexed { i, s ->
            if (cur.isNotEmpty() && used + s > limit) { out.add(cur); cur = mutableListOf(); used = overhead }
            cur.add(i); used += s
        }
        if (cur.isNotEmpty()) out.add(cur)
        return out
    }

    /** Parses "2 MB", "500kb", "1.5" (MB) → bytes; null if invalid. */
    fun parseSize(text: String): Long? {
        val m = Regex("""^\s*(\d+(?:[.,]\d+)?)\s*(kb|k|mb|m)?\s*$""", RegexOption.IGNORE_CASE).find(text) ?: return null
        val v = m.groupValues[1].replace(',', '.').toDoubleOrNull() ?: return null
        val mult = when (m.groupValues[2].lowercase()) { "kb", "k" -> 1024.0; else -> 1024.0 * 1024.0 }
        return (v * mult).toLong().takeIf { it in 20L * 1024..2L * 1024 * 1024 * 1024 }
    }
}
