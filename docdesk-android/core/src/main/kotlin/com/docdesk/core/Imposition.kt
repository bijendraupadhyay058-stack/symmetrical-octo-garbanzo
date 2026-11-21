package com.docdesk.core

/** Page-layout maths for printing: several pages per sheet, booklets, double-sided scan collation. */
object Imposition {
    /** Columns × rows for [n] pages per sheet, and whether the sheet should be landscape (portrait source pages assumed). */
    data class Grid(val cols: Int, val rows: Int, val landscape: Boolean)

    fun grid(n: Int, sourceLandscape: Boolean = false): Grid {
        val g = when (n) {
            2 -> Grid(2, 1, true)
            4 -> Grid(2, 2, false)
            6 -> Grid(3, 2, true)
            8 -> Grid(4, 2, true)
            9 -> Grid(3, 3, false)
            16 -> Grid(4, 4, false)
            else -> throw IllegalArgumentException("Unsupported pages per sheet: $n")
        }
        // Landscape source pages fit better when the grid is turned (2-up landscape pages stack vertically on a portrait sheet).
        return if (sourceLandscape) Grid(g.rows, g.cols, !g.landscape) else g
    }

    /** Slot rectangles [x, y, w, h] in PDF space (origin bottom-left), in reading order: left→right, top→bottom. */
    fun slots(sheetW: Float, sheetH: Float, g: Grid, margin: Float, gap: Float): List<FloatArray> {
        val w = (sheetW - 2 * margin - gap * (g.cols - 1)) / g.cols
        val h = (sheetH - 2 * margin - gap * (g.rows - 1)) / g.rows
        require(w > 0 && h > 0) { "Margins too large" }
        return (0 until g.rows).flatMap { r -> (0 until g.cols).map { c -> floatArrayOf(margin + c * (w + gap), sheetH - margin - (r + 1) * h - r * gap, w, h) } }
    }

    /** Scale and offset to fit a [pw]×[ph] page centred in a slot. Returns [scale, x, y]. */
    fun fit(pw: Float, ph: Float, slot: FloatArray): FloatArray {
        val s = minOf(slot[2] / pw, slot[3] / ph)
        return floatArrayOf(s, slot[0] + (slot[2] - pw * s) / 2, slot[1] + (slot[3] - ph * s) / 2)
    }

    /**
     * Booklet order for saddle-stitching: the page count is padded to a multiple of 4 with blanks (-1).
     * Returns sheet sides in printing order, each as (left page, right page). Print double-sided,
     * flip on the short edge, fold the stack in half.
     */
    fun booklet(pageCount: Int): List<Pair<Int, Int>> {
        require(pageCount > 0)
        val n = (pageCount + 3) / 4 * 4
        fun p(i: Int) = if (i < pageCount) i else -1
        return (0 until n / 4).flatMap { s -> listOf(p(n - 1 - 2 * s) to p(2 * s), p(2 * s + 1) to p(n - 2 - 2 * s)) }
    }

    /**
     * Collates separately scanned fronts and backs. A document feeder scans backs in reverse when the stack
     * is turned over, so [backsReversed] is usually true. Returns (isBack, index) in final order; extra
     * pages on either side are appended at the end.
     */
    fun collate(fronts: Int, backs: Int, backsReversed: Boolean): List<Pair<Boolean, Int>> {
        val out = ArrayList<Pair<Boolean, Int>>()
        for (i in 0 until maxOf(fronts, backs)) {
            if (i < fronts) out.add(false to i)
            if (i < backs) out.add(true to if (backsReversed) backs - 1 - i else i)
        }
        return out
    }
}
