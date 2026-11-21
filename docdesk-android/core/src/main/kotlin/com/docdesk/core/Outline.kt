package com.docdesk.core

/** An editable bookmark: [page] is 0-based, [level] 0 = top level. */
data class OutlineEntry(val title: String, val level: Int, val page: Int)

object Outline {
    const val MAX_LEVEL = 5

    /** Makes levels valid: the first entry is top level and no entry is more than one level below the one before it. */
    fun normalize(entries: List<OutlineEntry>): List<OutlineEntry> {
        var prev = -1
        return entries.map { e ->
            val lvl = e.level.coerceIn(0, minOf(prev + 1, MAX_LEVEL))
            prev = lvl
            e.copy(level = lvl, title = e.title.replace(Regex("""\s+"""), " ").trim().take(250))
        }
    }

    /** Index ranges of each entry's subtree (the entry plus the following deeper entries). */
    fun subtreeEnd(entries: List<OutlineEntry>, index: Int): Int {
        val lvl = entries[index].level
        var j = index + 1
        while (j < entries.size && entries[j].level > lvl) j++
        return j
    }

    /** Moves the entry at [index] (with its children) up or down past its neighbouring sibling block. */
    fun move(entries: List<OutlineEntry>, index: Int, up: Boolean): List<OutlineEntry> {
        val end = subtreeEnd(entries, index)
        val block = entries.subList(index, end)
        val lvl = entries[index].level
        return if (up) {
            // Previous sibling: nearest earlier entry with level <= lvl.
            var p = index - 1
            while (p >= 0 && entries[p].level > lvl) p--
            if (p < 0 || entries[p].level < lvl) return entries
            entries.subList(0, p) + block + entries.subList(p, index) + entries.subList(end, entries.size)
        } else {
            if (end >= entries.size || entries[end].level < lvl) return entries
            val nextEnd = subtreeEnd(entries, end)
            entries.subList(0, index) + entries.subList(end, nextEnd) + block + entries.subList(nextEnd, entries.size)
        }
    }

    /** Indents (+1) or outdents (-1) an entry together with its children. */
    fun shift(entries: List<OutlineEntry>, index: Int, delta: Int): List<OutlineEntry> {
        val end = subtreeEnd(entries, index)
        val maxLvl = if (index == 0) 0 else entries[index - 1].level + 1
        val newLvl = (entries[index].level + delta).coerceIn(0, minOf(maxLvl, MAX_LEVEL))
        val d = newLvl - entries[index].level
        if (d == 0) return entries
        return entries.mapIndexed { i, e -> if (i in index until end) e.copy(level = (e.level + d).coerceIn(0, MAX_LEVEL)) else e }.let(::normalize)
    }

    /** Removes an entry; its children move up one level. */
    fun remove(entries: List<OutlineEntry>, index: Int): List<OutlineEntry> {
        val end = subtreeEnd(entries, index)
        return normalize(entries.mapIndexedNotNull { i, e -> when { i == index -> null; i in index + 1 until end -> e.copy(level = e.level - 1); else -> e } })
    }
}

/** Finds headings in text pages, for automatic bookmarks. */
object HeadingFinder {
    /**
     * Headings are short lines printed noticeably larger than the body text (or bold at body size
     * when they stand alone on a line). Bigger headings become higher levels (max 3 levels).
     */
    fun find(pages: List<PageText>, maxPerPage: Int = 8): List<OutlineEntry> {
        val linesByPage = pages.associate { it.pageIndex to LineGrouper.group(it.words) }
        val sizeChars = HashMap<Int, Int>()
        linesByPage.values.flatten().forEach { l -> val k = Math.round(l.fontSize * 2); sizeChars[k] = (sizeChars[k] ?: 0) + l.text.length }
        if (sizeChars.isEmpty()) return emptyList()
        val body = sizeChars.maxBy { it.value }.key / 2f
        val heights = pages.associate { it.pageIndex to it.height }
        val repeated = repeatedLines(linesByPage, ::plain)
        val repeatedNum = repeatedLines(linesByPage, ::key)
        data class Cand(val page: Int, val text: String, val size: Float, val order: Int)
        val cands = mutableListOf<Cand>()
        for (p in pages.sortedBy { it.pageIndex }) {
            val lines = linesByPage[p.pageIndex].orEmpty()
            var n = 0
            for ((i, l) in lines.withIndex()) {
                val t = l.text.trim()
                val h = heights[p.pageIndex] ?: 842f
                val inMargin = l.top < h * 0.1f || l.bottom > h * 0.9f
                // Running headers/footers repeat on most pages ("Chapter 3 Overview" on every page is not a header unless it's in the margin).
                if (!isHeadingText(t) || plain(t) in repeated || (inMargin && key(t) in repeatedNum)) continue
                val big = l.fontSize >= body * 1.18f
                val boldAlone = l.allBold && l.fontSize >= body * 0.98f && t.length <= 70 && !t.endsWith(".")
                if (!big && !boldAlone) continue
                cands.add(Cand(p.pageIndex, t, if (big) l.fontSize else body, i))
                if (++n >= maxPerPage) break
            }
        }
        val sizes = cands.map { Math.round(it.size * 2) }.distinct().sortedDescending().take(3)
        return cands.map { c -> OutlineEntry(c.text.take(120), sizes.indexOf(Math.round(c.size * 2)).let { if (it < 0) 2 else it }, c.page) }.let(Outline::normalize)
    }

    /** One bookmark per page titled with the page's first meaningful line. */
    fun perPage(pages: List<PageText>): List<OutlineEntry> = pages.sortedBy { it.pageIndex }.map { p ->
        val first = LineGrouper.group(p.words).map { it.text.trim() }.firstOrNull { isHeadingText(it) }
        OutlineEntry("Page ${p.pageIndex + 1}" + (first?.let { " – " + it.take(60) } ?: ""), 0, p.pageIndex)
    }

    fun isHeadingText(t: String): Boolean {
        if (t.length < 2 || t.length > 120) return false
        val letters = t.count { it.isLetter() }
        if (letters < 2 || letters < t.length * 0.4) return false
        if (Regex("""^(page\s*)?\d+(\s*(of|/)\s*\d+)?$""", RegexOption.IGNORE_CASE).matches(t)) return false
        return true
    }

    private fun plain(s: String) = s.lowercase().replace(Regex("""\s+"""), " ").trim()
    private fun key(s: String) = s.lowercase().replace(Regex("""\d+"""), "#").replace(Regex("""\s+"""), " ").trim()

    /** Lines that appear on most pages (running headers/footers) are not headings. */
    private fun repeatedLines(lines: Map<Int, List<TextLine>>, key: (String) -> String): Set<String> {
        if (lines.size < 3) return emptySet()
        val counts = HashMap<String, Int>()
        lines.values.forEach { ls -> ls.map { key(it.text) }.toSet().forEach { counts[it] = (counts[it] ?: 0) + 1 } }
        return counts.filter { it.value >= lines.size * 0.6 }.keys
    }
}
