package com.docdesk.app.edit

/**
 * Annotation model. Positions are normalised (0..1) to the page AS DISPLAYED, so they are
 * independent of zoom and of the page's /Rotate value. Sizes (stroke, text) are in points.
 */
enum class Tool(val label: String) {
    SELECT("Select / move"), HIGHLIGHT("Highlight"), UNDERLINE("Underline"), STRIKE("Strikethrough"),
    PEN("Draw"), RECT("Rectangle"), ELLIPSE("Ellipse"), LINE("Line"), ARROW("Arrow"),
    TEXT("Text box"), NOTE("Sticky note"), IMAGE("Image"), SIGNATURE("Signature"), WHITEOUT("Cover (white-out)"),
}

data class NPoint(val x: Float, val y: Float)

data class NRect(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    val width get() = right - left
    val height get() = bottom - top
    fun offset(dx: Float, dy: Float) = NRect(left + dx, top + dy, right + dx, bottom + dy)
    fun contains(p: NPoint, slop: Float = 0f) = p.x in (left - slop)..(right + slop) && p.y in (top - slop)..(bottom + slop)

    companion object {
        fun of(a: NPoint, b: NPoint) = NRect(minOf(a.x, b.x), minOf(a.y, b.y), maxOf(a.x, b.x), maxOf(a.y, b.y))
    }
}

sealed class Annot {
    abstract val id: Long
    abstract val page: Int
    abstract val color: Int
    abstract fun bounds(): NRect
    abstract fun moved(dx: Float, dy: Float): Annot

    enum class BoxKind { HIGHLIGHT, UNDERLINE, STRIKE, RECT, ELLIPSE, WHITEOUT }

    data class Box(override val id: Long, override val page: Int, val kind: BoxKind, val rect: NRect, override val color: Int, val strokePt: Float) : Annot() {
        override fun bounds() = rect
        override fun moved(dx: Float, dy: Float) = copy(rect = rect.offset(dx, dy))
    }

    data class Line(override val id: Long, override val page: Int, val a: NPoint, val b: NPoint, val arrow: Boolean, override val color: Int, val strokePt: Float) : Annot() {
        override fun bounds() = NRect.of(a, b)
        override fun moved(dx: Float, dy: Float) = copy(a = NPoint(a.x + dx, a.y + dy), b = NPoint(b.x + dx, b.y + dy))
    }

    data class Ink(override val id: Long, override val page: Int, val points: List<NPoint>, override val color: Int, val strokePt: Float) : Annot() {
        override fun bounds() = NRect(points.minOf { it.x }, points.minOf { it.y }, points.maxOf { it.x }, points.maxOf { it.y })
        override fun moved(dx: Float, dy: Float) = copy(points = points.map { NPoint(it.x + dx, it.y + dy) })
    }

    /** Text drawn on the page. [origin] is the top-left of the first line. */
    data class TextBox(override val id: Long, override val page: Int, val origin: NPoint, val text: String, val sizePt: Float, override val color: Int) : Annot() {
        override fun bounds() = NRect(origin.x, origin.y, origin.x + 0.05f + text.lines().maxOf { it.length } * sizePt * 0.0009f, origin.y + text.lines().size * sizePt * 0.0016f)
        override fun moved(dx: Float, dy: Float) = copy(origin = NPoint(origin.x + dx, origin.y + dy))
    }

    /** A PDF comment (sticky note): stays editable in other PDF apps. */
    data class Note(override val id: Long, override val page: Int, val at: NPoint, val text: String, override val color: Int) : Annot() {
        override fun bounds() = NRect(at.x, at.y, at.x + 0.05f, at.y + 0.035f)
        override fun moved(dx: Float, dy: Float) = copy(at = NPoint(at.x + dx, at.y + dy))
    }

    data class Picture(override val id: Long, override val page: Int, val rect: NRect, val path: String, val signature: Boolean) : Annot() {
        override val color: Int get() = 0
        override fun bounds() = rect
        override fun moved(dx: Float, dy: Float) = copy(rect = rect.offset(dx, dy))
    }
}
