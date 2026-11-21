package com.docdesk.core

/**
 * A word (or OCR element) positioned on a page.
 * Coordinates are in page units (PDF points for text PDFs) with the origin at the TOP-LEFT
 * of the page as displayed, y increasing downwards.
 */
data class TextWord(
    val text: String,
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float,
    val fontSize: Float = height,
    val bold: Boolean = false,
    val italic: Boolean = false,
    /** OCR confidence in 0..1, or null when the text came from the PDF text layer (exact). */
    val confidence: Float? = null,
) {
    val right: Float get() = x + width
    val bottom: Float get() = y + height
    val centerY: Float get() = y + height / 2f
}

enum class TextSource { PDF_TEXT, OCR, NONE }

/** All words of one page plus its displayed size. */
data class PageText(
    val pageIndex: Int,
    val width: Float,
    val height: Float,
    val words: List<TextWord>,
    val source: TextSource,
)

/** A normalised rectangle (0..1 of page width/height), used for "manual table area". */
data class NormRect(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    fun containsCenterOf(w: TextWord, pageW: Float, pageH: Float): Boolean {
        val cx = (w.x + w.width / 2f) / pageW
        val cy = w.centerY / pageH
        return cx in left..right && cy in top..bottom
    }

    companion object {
        fun of(a: Float, b: Float, c: Float, d: Float) =
            NormRect(minOf(a, c).coerceIn(0f, 1f), minOf(b, d).coerceIn(0f, 1f), maxOf(a, c).coerceIn(0f, 1f), maxOf(b, d).coerceIn(0f, 1f))
    }
}

/** A visual line of text: words sharing the same baseline band, sorted left to right. */
data class TextLine(val words: List<TextWord>) {
    val x: Float = words.minOf { it.x }
    val right: Float = words.maxOf { it.right }
    val top: Float = words.minOf { it.y }
    val bottom: Float = words.maxOf { it.bottom }
    val height: Float get() = bottom - top
    val fontSize: Float = words.map { it.fontSize }.sorted()[words.size / 2]
    val text: String get() = words.joinToString(" ") { it.text }
    val allBold: Boolean get() = words.all { it.bold }
    val minConfidence: Float? get() = words.mapNotNull { it.confidence }.minOrNull()
}

object LineGrouper {
    /** Groups words into lines by vertical overlap of their centre bands. */
    fun group(words: List<TextWord>): List<TextLine> {
        if (words.isEmpty()) return emptyList()
        val sorted = words.filter { it.text.isNotBlank() }.sortedWith(compareBy({ it.centerY }, { it.x }))
        val lines = mutableListOf<MutableList<TextWord>>()
        var currentCenter = Float.NaN
        var currentHeight = 0f
        for (w in sorted) {
            val tol = maxOf(currentHeight, w.height) * 0.5f
            if (lines.isNotEmpty() && kotlin.math.abs(w.centerY - currentCenter) <= tol) {
                val line = lines.last()
                line.add(w)
                currentCenter = line.map { it.centerY }.average().toFloat()
                currentHeight = line.maxOf { it.height }
            } else {
                lines.add(mutableListOf(w))
                currentCenter = w.centerY
                currentHeight = w.height
            }
        }
        return lines.map { l -> TextLine(l.sortedBy { it.x }) }
    }
}
