package com.docdesk.core

/** Format-neutral rich document model shared by PDF→Word, Word→PDF and the previews. */
data class DocRun(
    val text: String,
    val bold: Boolean = false,
    val italic: Boolean = false,
    val underline: Boolean = false,
    val strike: Boolean = false,
    /** Font size in points, or null for the paragraph default. */
    val sizePt: Float? = null,
    /** RRGGBB hex, or null for automatic. */
    val color: String? = null,
    val fontName: String? = null,
)

enum class Align { LEFT, CENTER, RIGHT, JUSTIFY }

sealed class DocBlock {
    data class Paragraph(
        val runs: List<DocRun>,
        /** 0 = normal text, 1..6 = heading levels, -1 = title. */
        val headingLevel: Int = 0,
        val align: Align = Align.LEFT,
        /** Bullet or number label shown before the text ("•", "1.", "a)"), or null. */
        val listLabel: String? = null,
        val listLevel: Int = 0,
        val indentLeftPt: Float = 0f,
        val firstLineIndentPt: Float = 0f,
        val spaceBeforePt: Float = 0f,
        val spaceAfterPt: Float = 6f,
        val pageBreakBefore: Boolean = false,
    ) : DocBlock() {
        val text: String get() = runs.joinToString("") { it.text }
    }

    data class Table(
        val rows: List<List<Cell>>,
        /** Relative column widths (any unit), or empty for equal widths. */
        val columnWidths: List<Float> = emptyList(),
        val bordered: Boolean = true,
    ) : DocBlock() {
        data class Cell(val blocks: List<DocBlock>, val colSpan: Int = 1, val shadeHex: String? = null)
    }

    data class Image(
        val bytes: ByteArray,
        /** "png" or "jpeg" */
        val format: String,
        val widthPt: Float,
        val heightPt: Float,
        val align: Align = Align.LEFT,
    ) : DocBlock()

    data object PageBreak : DocBlock()
}

data class PageSetup(
    val widthPt: Float = 595.3f,
    val heightPt: Float = 841.9f,
    val marginLeftPt: Float = 72f,
    val marginRightPt: Float = 72f,
    val marginTopPt: Float = 72f,
    val marginBottomPt: Float = 72f,
) {
    val contentWidth get() = widthPt - marginLeftPt - marginRightPt
    val contentHeight get() = heightPt - marginTopPt - marginBottomPt

    companion object {
        val A4 = PageSetup()
        val LETTER = PageSetup(612f, 792f)
    }
}

data class DocDocument(
    val blocks: List<DocBlock>,
    val page: PageSetup = PageSetup.A4,
    val header: List<DocBlock> = emptyList(),
    val footer: List<DocBlock> = emptyList(),
    val defaultFontSizePt: Float = 11f,
    /** Things the reader met but could not represent (text boxes, charts, equations...). */
    val unsupported: Map<String, Int> = emptyMap(),
    val fontsUsed: Set<String> = emptySet(),
)
