package com.docdesk.core

/** One text line of a document for comparison: page, position in that page's line list, text. */
data class DiffLine(val page: Int, val index: Int, val text: String)

sealed class Change {
    data class Added(val new: DiffLine) : Change()
    data class Removed(val old: DiffLine) : Change()
    /** Same line edited; the word indexes that differ are given for precise highlighting. */
    data class Modified(val old: DiffLine, val new: DiffLine, val oldWords: Set<Int>, val newWords: Set<Int>) : Change()
}

/**
 * Compares two documents line by line (longest common subsequence), then pairs neighbouring
 * removed/added lines that are similar into "modified" lines with word-level differences –
 * so a changed amount in an agreement is pinpointed instead of the whole paragraph.
 */
object TextDiff {
    private const val MAX_CELLS = 30_000_000L

    fun norm(s: String) = s.replace(Regex("""\s+"""), " ").trim()

    fun diff(old: List<DiffLine>, new: List<DiffLine>, ignoreCase: Boolean = false): List<Change> {
        val a = old.map { key(it.text, ignoreCase) }
        val b = new.map { key(it.text, ignoreCase) }
        val ops = if (a.size.toLong() * b.size > MAX_CELLS) chunked(a, b) else lcsOps(a, b)
        // Group runs of removals/additions between equal lines and pair them up.
        val out = mutableListOf<Change>()
        val removed = mutableListOf<DiffLine>(); val added = mutableListOf<DiffLine>()
        fun flush() {
            var ri = 0; var ai = 0
            while (ri < removed.size || ai < added.size) {
                val r = removed.getOrNull(ri); val ad = added.getOrNull(ai)
                if (r != null && ad != null && similarity(r.text, ad.text, ignoreCase) >= 0.4) {
                    val (ow, nw) = wordDiff(r.text, ad.text, ignoreCase)
                    out.add(Change.Modified(r, ad, ow, nw)); ri++; ai++
                } else if (r != null && (ad == null || removed.size - ri >= added.size - ai)) { out.add(Change.Removed(r)); ri++ }
                else if (ad != null) { out.add(Change.Added(ad)); ai++ }
            }
            removed.clear(); added.clear()
        }
        for (op in ops) when (op) {
            is Op.Eq -> flush()
            is Op.Del -> removed.add(old[op.i])
            is Op.Ins -> added.add(new[op.j])
        }
        flush()
        return out
    }

    private fun key(s: String, ic: Boolean) = norm(s).let { if (ic) it.lowercase() else it }

    private sealed class Op { data class Eq(val i: Int, val j: Int) : Op(); data class Del(val i: Int) : Op(); data class Ins(val j: Int) : Op() }

    private fun lcsOps(a: List<String>, b: List<String>, offA: Int = 0, offB: Int = 0): List<Op> {
        val n = a.size; val m = b.size
        val dp = Array(n + 1) { IntArray(m + 1) }
        for (i in n - 1 downTo 0) for (j in m - 1 downTo 0) dp[i][j] = if (a[i] == b[j]) dp[i + 1][j + 1] + 1 else maxOf(dp[i + 1][j], dp[i][j + 1])
        val ops = mutableListOf<Op>()
        var i = 0; var j = 0
        while (i < n && j < m) {
            when {
                a[i] == b[j] -> { ops.add(Op.Eq(i + offA, j + offB)); i++; j++ }
                dp[i + 1][j] >= dp[i][j + 1] -> { ops.add(Op.Del(i + offA)); i++ }
                else -> { ops.add(Op.Ins(j + offB)); j++ }
            }
        }
        while (i < n) { ops.add(Op.Del(i + offA)); i++ }
        while (j < m) { ops.add(Op.Ins(j + offB)); j++ }
        return ops
    }

    /** Very large documents: compare in aligned blocks to bound memory. */
    private fun chunked(a: List<String>, b: List<String>): List<Op> {
        val size = 2000
        val ops = mutableListOf<Op>()
        var i = 0; var j = 0
        while (i < a.size || j < b.size) {
            val ea = minOf(a.size, i + size); val eb = minOf(b.size, j + size)
            ops.addAll(lcsOps(a.subList(i, ea), b.subList(j, eb), i, j))
            i = ea; j = eb
        }
        return ops
    }

    private fun words(s: String, ic: Boolean) = norm(s).split(' ').filter { it.isNotEmpty() }.map { if (ic) it.lowercase() else it }

    fun similarity(x: String, y: String, ic: Boolean = false): Double {
        val a = words(x, ic).toSet(); val b = words(y, ic).toSet()
        if (a.isEmpty() && b.isEmpty()) return 1.0
        return (a intersect b).size.toDouble() / (a union b).size
    }

    /** Indexes of words (as split by spaces) that differ between two versions of a line. */
    fun wordDiff(x: String, y: String, ic: Boolean = false): Pair<Set<Int>, Set<Int>> {
        val ops = lcsOps(words(x, ic), words(y, ic))
        return ops.filterIsInstance<Op.Del>().map { it.i }.toSet() to ops.filterIsInstance<Op.Ins>().map { it.j }.toSet()
    }
}
