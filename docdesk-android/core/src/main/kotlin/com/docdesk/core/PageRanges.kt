package com.docdesk.core

/** Parses user page selections such as "1-5, 8, 10–12" (1-based, inclusive). */
object PageRanges {

    class ParseException(message: String) : IllegalArgumentException(message)

    /** Returns 0-based page indices in the order typed (duplicates kept, so "1,1" duplicates a page). */
    fun parse(input: String, pageCount: Int): List<Int> = parseGroups(input, pageCount).flatten()

    /**
     * Returns each comma-separated part as its own group; used by "split by custom ranges"
     * where "1-5, 6-10" must produce two files.
     */
    fun parseGroups(input: String, pageCount: Int): List<List<Int>> {
        val text = input.trim()
        if (text.isEmpty() || text.equals("all", ignoreCase = true)) return listOf((0 until pageCount).toList())
        val normalised = text.replace('–', '-').replace('—', '-').replace(" to ", "-")
        val groups = mutableListOf<List<Int>>()
        for (rawPart in normalised.split(',', ';')) {
            val part = rawPart.trim()
            if (part.isEmpty()) continue
            val pieces = part.split('-').map { it.trim() }
            when (pieces.size) {
                1 -> {
                    val p = pieceToPage(pieces[0], pageCount, part)
                    groups.add(listOf(p - 1))
                }
                2 -> {
                    val start = if (pieces[0].isEmpty()) 1 else pieceToPage(pieces[0], pageCount, part)
                    val end = if (pieces[1].isEmpty()) pageCount else pieceToPage(pieces[1], pageCount, part)
                    if (start > end) throw ParseException("\"$part\": the first page must not be after the last page.")
                    groups.add((start - 1 until end).toList())
                }
                else -> throw ParseException("\"$part\" is not a valid range. Use a form like 1-5.")
            }
        }
        if (groups.isEmpty()) throw ParseException("Enter page numbers, for example 1-3, 5.")
        return groups
    }

    private fun pieceToPage(piece: String, pageCount: Int, part: String): Int {
        val n = piece.toIntOrNull() ?: throw ParseException("\"$part\" contains \"$piece\", which is not a page number.")
        if (n < 1 || n > pageCount) throw ParseException("Page $n does not exist. This document has $pageCount page${if (pageCount == 1) "" else "s"}.")
        return n
    }

    /**
     * Splits a document after the given 1-based pages. Splitting a 10-page file after 3 and 7
     * gives [1-3], [4-7], [8-10].
     */
    fun splitAfter(pagesAfter: Collection<Int>, pageCount: Int): List<List<Int>> {
        val cuts = pagesAfter.filter { it in 1 until pageCount }.distinct().sorted()
        val groups = mutableListOf<List<Int>>()
        var start = 0
        for (c in cuts) {
            groups.add((start until c).toList())
            start = c
        }
        groups.add((start until pageCount).toList())
        return groups.filter { it.isNotEmpty() }
    }

    /** Formats 0-based indices compactly as 1-based text, e.g. [0,1,2,4] -> "1-3, 5". */
    fun format(indices: List<Int>): String {
        if (indices.isEmpty()) return ""
        val sorted = indices.distinct().sorted()
        val parts = mutableListOf<String>()
        var s = sorted[0]
        var prev = s
        for (i in sorted.drop(1) + listOf(Int.MIN_VALUE)) {
            if (i == prev + 1) { prev = i; continue }
            parts.add(if (s == prev) "${s + 1}" else "${s + 1}-${prev + 1}")
            s = i; prev = i
        }
        return parts.joinToString(", ")
    }
}
