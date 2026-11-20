package com.docdesk.core

/**
 * Text-snapping for highlight/underline/strikethrough, and line lookup for "Edit text".
 * Coordinates are page units, top-left origin (same as [TextWord]).
 */
object TextSelection {
    data class LineRect(val x: Float, val top: Float, val right: Float, val bottom: Float, val text: String)

    /**
     * Words selected by dragging from ([x1],[y1]) to ([x2],[y2]) in reading order, like
     * selecting text in Acrobat: the first line from the start point, middle lines fully,
     * the last line up to the end point. Returns one rectangle per line, or empty when the
     * drag does not touch text (caller then falls back to an area markup).
     */
    fun select(words: List<TextWord>, x1: Float, y1: Float, x2: Float, y2: Float): List<LineRect> {
        val lines = LineGrouper.group(words)
        if (lines.isEmpty()) return emptyList()
        fun lineAt(y: Float): Int? = lines.indexOfFirst { y >= it.top - 2 && y <= it.bottom + 2 }.takeIf { it >= 0 }
            ?: lines.indices.minByOrNull { i -> kotlin.math.abs((lines[i].top + lines[i].bottom) / 2 - y) }
                ?.takeIf { i -> kotlin.math.abs((lines[i].top + lines[i].bottom) / 2 - y) < lines[i].height * 1.5f }
        var (sx, sy, ex, ey) = listOf(x1, y1, x2, y2)
        if (sy > ey || (kotlin.math.abs(sy - ey) < 2 && sx > ex)) { val t = sx; sx = ex; ex = t; val u = sy; sy = ey; ey = u }
        val first = lineAt(sy) ?: return emptyList()
        val last = lineAt(ey) ?: return emptyList()
        val (a, b) = if (first <= last) first to last else last to first
        val out = mutableListOf<LineRect>()
        for (i in a..b) {
            val l = lines[i]
            val chosen = l.words.filter { w ->
                val cx = w.x + w.width / 2
                when {
                    a == b -> cx >= minOf(sx, ex) && cx <= maxOf(sx, ex) || (w.x <= minOf(sx, ex) && w.right >= maxOf(sx, ex))
                    i == a -> cx >= sx || w.right >= sx && w.x <= sx
                    i == b -> cx <= ex || w.x <= ex && w.right >= ex
                    else -> true
                }
            }
            if (chosen.isNotEmpty()) out.add(LineRect(chosen.minOf { it.x }, chosen.minOf { it.y }, chosen.maxOf { it.right }, chosen.maxOf { it.bottom }, chosen.joinToString(" ") { it.text }))
        }
        return out
    }

    /** The text line under a point, for "Edit text". */
    fun lineAt(words: List<TextWord>, x: Float, y: Float, slop: Float = 3f): TextLine? =
        LineGrouper.group(words).filter { y >= it.top - slop && y <= it.bottom + slop && x >= it.x - 20 && x <= it.right + 20 }
            .minByOrNull { kotlin.math.abs((it.top + it.bottom) / 2 - y) }
}

/** Page-number / header / footer text templates: {n}, {total}, {date}, {file}, and Bates-style {n:4}. */
object LabelTemplate {
    private val token = Regex("""\{(n|total|date|file)(?::(\d{1,2}))?}""")

    fun render(template: String, pageNumber: Int, total: Int, date: String = "", fileName: String = ""): String =
        token.replace(template) { m ->
            val pad = m.groupValues[2].toIntOrNull()
            when (m.groupValues[1]) {
                "n" -> if (pad != null) pageNumber.toString().padStart(pad, '0') else pageNumber.toString()
                "total" -> total.toString()
                "date" -> date
                else -> fileName
            }
        }
}
