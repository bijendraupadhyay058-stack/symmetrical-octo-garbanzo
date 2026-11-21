package com.docdesk.core

import kotlin.math.abs

enum class WordMode(val label: String, val description: String) {
    EDITABLE("Editable text", "Joins lines into paragraphs, detects headings, lists and tables. Best for editing."),
    LAYOUT("Layout-focused", "Keeps each line, its indentation and font size. Looks closer to the PDF but is harder to edit."),
}

/** An image found on a PDF page, positioned in the same top-left coordinate space as words. */
data class PageImage(val bytes: ByteArray, val format: String, val x: Float, val y: Float, val width: Float, val height: Float)

data class PageContent(val text: PageText, val images: List<PageImage> = emptyList())

/** Builds a Word document model from positioned PDF text. */
object PdfToDocBuilder {
    private val bulletChars = setOf("•", "●", "▪", "■", "◦", "○", "–", "-", "*", "", "·", "➢", "✓", "►")
    private val numberedLabel = Regex("""^(\(?[0-9]{1,3}[.)]|\(?[a-zA-Z][.)]|\(?[ivxIVX]{1,5}[.)])$""")

    fun build(pages: List<PageContent>, mode: WordMode, detectTables: Boolean = true): DocDocument {
        val first = pages.firstOrNull()?.text
        val setup = if (first != null) PageSetup(first.width, first.height, 54f, 54f, 54f, 54f) else PageSetup.A4
        val allLines = pages.associate { it.text.pageIndex to LineGrouper.group(it.text.words) }
        val bodySize = allLines.values.flatten().flatMap { l -> l.words.map { it.fontSize } }.let { s -> if (s.isEmpty()) 11f else s.sorted()[s.size / 2] }
        val (headerKeys, footerKeys) = repeatedMargins(pages, allLines)

        val blocks = mutableListOf<DocBlock>()
        var headerBlocks: List<DocBlock> = emptyList()
        var footerBlocks: List<DocBlock> = emptyList()
        pages.forEachIndexed { pi, page ->
            if (pi > 0) blocks.add(DocBlock.PageBreak)
            val lines = allLines[page.text.pageIndex].orEmpty()
            val body = mutableListOf<TextLine>()
            for (l in lines) {
                val key = normKey(l.text)
                val inTop = l.top < page.text.height * 0.1f
                val inBottom = l.bottom > page.text.height * 0.9f
                when {
                    inTop && key in headerKeys -> { if (headerBlocks.isEmpty()) headerBlocks = listOf(para(l, Align.CENTER)) }
                    inBottom && key in footerKeys -> { if (footerBlocks.isEmpty()) footerBlocks = listOf(para(l, Align.CENTER)) }
                    else -> body.add(l)
                }
            }
            // Tables: lines belonging to a detected table (≥3 columns, ≥3 rows) become Table blocks.
            val tables = if (detectTables) TableExtractor.extract(page.text.copy(words = body.flatMap { it.words }), TableOptions(mergeWrappedRows = mode == WordMode.EDITABLE, minRows = 3))
                .filter { it.columnCount >= 3 } else emptyList()
            val tableSpans = tables.map { t -> spanOf(t, body) }
            val items = mutableListOf<Pair<Float, Any>>() // y -> TextLine | ExtractedTable | PageImage
            body.forEach { l -> if (tableSpans.none { (a, b) -> l.top >= a - 0.5f && l.bottom <= b + 0.5f }) items.add(l.top to l) }
            tables.forEachIndexed { i, t -> items.add(tableSpans[i].first to t) }
            page.images.forEach { items.add(it.y to it) }
            items.sortBy { it.first }

            val leftMargin = body.minOfOrNull { it.x } ?: 0f
            var pendingLines = mutableListOf<TextLine>()
            fun flush() {
                if (pendingLines.isEmpty()) return
                blocks.addAll(if (mode == WordMode.EDITABLE) paragraphs(pendingLines, bodySize, leftMargin, page.text.width) else layoutLines(pendingLines, leftMargin, bodySize))
                pendingLines = mutableListOf()
            }
            for ((_, item) in items) {
                when (item) {
                    is TextLine -> pendingLines.add(item)
                    is ExtractedTable -> { flush(); blocks.add(toDocTable(item)) }
                    is PageImage -> { flush(); blocks.add(DocBlock.Image(item.bytes, item.format, item.width, item.height, alignOf(item.x, item.width, page.text.width))) }
                }
            }
            flush()
        }
        return DocDocument(blocks, setup, headerBlocks, footerBlocks, defaultFontSizePt = bodySize.coerceIn(8f, 14f))
    }

    private fun spanOf(t: ExtractedTable, lines: List<TextLine>): Pair<Float, Float> {
        // Find lines whose text appears in the table rows (by first cell texts) to get its vertical span.
        val texts = t.rows.flatMap { r -> r.cells.map { it.raw } }.filter { it.isNotBlank() }.toSet()
        val hits = lines.filter { l -> l.words.any { w -> texts.any { it.contains(w.text) } } && l.words.size >= 1 }
        val rowsTexts = t.rows.map { r -> r.cells.firstOrNull { !it.isBlank }?.raw ?: "" }
        val firstLine = lines.firstOrNull { l -> rowsTexts.firstOrNull()?.let { l.text.contains(it) } == true } ?: hits.firstOrNull()
        val lastLine = lines.lastOrNull { l -> t.rows.last().cells.filter { !it.isBlank }.any { c -> l.text.contains(c.raw.split(' ').last()) } } ?: hits.lastOrNull()
        return (firstLine?.top ?: 0f) to (lastLine?.bottom ?: 0f)
    }

    private fun toDocTable(t: ExtractedTable): DocBlock.Table = DocBlock.Table(
        t.rows.map { r ->
            r.cells.mapIndexed { i, c ->
                val align = if (t.columnTypes.getOrNull(i) == ColumnType.AMOUNT) Align.RIGHT else Align.LEFT
                DocBlock.Table.Cell(listOf(DocBlock.Paragraph(listOf(DocRun(c.raw, bold = r.isHeader)), align = align, spaceAfterPt = 0f)), shadeHex = if (r.isHeader) "E7EEF8" else null)
            }
        },
    )

    private fun alignOf(x: Float, w: Float, pageW: Float): Align {
        val center = x + w / 2
        return when {
            abs(center - pageW / 2) < pageW * 0.08f -> Align.CENTER
            x > pageW * 0.55f -> Align.RIGHT
            else -> Align.LEFT
        }
    }

    private fun normKey(s: String) = s.lowercase().replace(Regex("""\d+"""), "#").replace(Regex("""\s+"""), " ").trim()

    /** Lines that repeat at the top/bottom of at least half of the pages (page headers/footers). */
    private fun repeatedMargins(pages: List<PageContent>, lines: Map<Int, List<TextLine>>): Pair<Set<String>, Set<String>> {
        if (pages.size < 3) return emptySet<String>() to emptySet()
        val top = HashMap<String, Int>(); val bottom = HashMap<String, Int>()
        for (p in pages) {
            val ls = lines[p.text.pageIndex].orEmpty()
            ls.filter { it.top < p.text.height * 0.1f }.map { normKey(it.text) }.toSet().forEach { top[it] = (top[it] ?: 0) + 1 }
            ls.filter { it.bottom > p.text.height * 0.9f }.map { normKey(it.text) }.toSet().forEach { bottom[it] = (bottom[it] ?: 0) + 1 }
        }
        val min = (pages.size + 1) / 2
        return top.filter { it.value >= min && it.key.isNotBlank() }.keys to bottom.filter { it.value >= min && it.key.isNotBlank() }.keys
    }

    private fun para(l: TextLine, align: Align) = DocBlock.Paragraph(runs(l.words, null), align = align, spaceAfterPt = 0f)

    /** Merge adjacent words with identical styling into runs; sizes are kept only when they differ from body text. */
    private fun runs(words: List<TextWord>, bodySize: Float?, forceSize: Boolean = false): List<DocRun> {
        val out = mutableListOf<DocRun>()
        for ((i, w) in words.withIndex()) {
            val size = if (forceSize || bodySize == null || abs(w.fontSize - bodySize) > 0.6f) (Math.round(w.fontSize * 2) / 2f) else null
            val text = (if (i > 0) " " else "") + w.text
            val last = out.lastOrNull()
            if (last != null && last.bold == w.bold && last.italic == w.italic && last.sizePt == size) out[out.lastIndex] = last.copy(text = last.text + text)
            else out.add(DocRun(text, w.bold, w.italic, sizePt = size))
        }
        return out
    }

    private fun paragraphs(lines: List<TextLine>, bodySize: Float, leftMargin: Float, pageW: Float): List<DocBlock> {
        val out = mutableListOf<DocBlock>()
        var cur = mutableListOf<TextLine>()
        fun emit() {
            if (cur.isEmpty()) return
            val first = cur.first()
            val words = cur.flatMap { it.words }
            val size = first.fontSize
            val text = cur.joinToString(" ") { it.text }
            val heading = when {
                size >= bodySize * 1.6f -> 1
                size >= bodySize * 1.3f -> 2
                size >= bodySize * 1.12f && text.length < 120 -> 3
                first.allBold && cur.size == 1 && text.length < 90 && !text.trimEnd().endsWith('.') -> 4
                else -> 0
            }
            val firstWord = first.words.first().text
            val isBullet = firstWord in bulletChars || (firstWord.length == 1 && firstWord[0].code in 0xF000..0xF0FF)
            val isNumbered = numberedLabel.matches(firstWord)
            val center = (first.x + first.right) / 2
            val align = if (cur.size <= 2 && abs(center - pageW / 2) < pageW * 0.05f && first.x > leftMargin + 20) Align.CENTER else Align.LEFT
            val indent = ((first.x - leftMargin).coerceAtLeast(0f)).let { if (it < 6f) 0f else it }
            when {
                // A clearly larger font wins over a "1." label: "1. Summary" in 13pt is a heading.
                heading in 1..3 -> out.add(DocBlock.Paragraph(runs(words, bodySize), headingLevel = heading, align = align))
                isBullet -> out.add(DocBlock.Paragraph(runs(words.drop(1), bodySize), listLabel = "•", listLevel = if (indent > 30) 1 else 0))
                isNumbered -> out.add(DocBlock.Paragraph(runs(words.drop(1), bodySize), listLabel = firstWord, indentLeftPt = 18f + indent, firstLineIndentPt = -18f))
                heading != 0 -> out.add(DocBlock.Paragraph(runs(words, bodySize).map { it.copy(bold = it.bold || heading == 4) }, headingLevel = heading, align = align))
                else -> {
                    // Hanging/first-line indent from the second line's position.
                    val second = cur.getOrNull(1)
                    val firstIndent = if (second != null) (first.x - second.x) else 0f
                    val leftIndent = if (second != null) (second.x - leftMargin).coerceAtLeast(0f) else indent
                    out.add(DocBlock.Paragraph(runs(words, bodySize), align = align, indentLeftPt = if (leftIndent < 6f) 0f else leftIndent, firstLineIndentPt = if (abs(firstIndent) < 6f) 0f else firstIndent))
                }
            }
            cur = mutableListOf()
        }
        // Typical gap between consecutive lines of the same size on this page. Text heights from
        // PDFs are cap-height based, so absolute thresholds misjudge normal line spacing.
        val gaps = lines.zipWithNext().filter { (a, b) -> abs(a.fontSize - b.fontSize) < 0.8f }.map { (a, b) -> b.top - a.bottom }.filter { it > 0 }.sorted()
        val typicalGap = if (gaps.isEmpty()) 0f else gaps[gaps.size / 2]
        for ((i, l) in lines.withIndex()) {
            if (cur.isEmpty()) { cur.add(l); continue }
            val prev = lines[i - 1]
            val gap = l.top - prev.bottom
            val closeEnough = gap <= maxOf(typicalGap * 1.35f, prev.fontSize * 0.5f) && gap < prev.fontSize * 1.6f
            val sameSize = abs(l.fontSize - prev.fontSize) < 0.8f
            val startsList = l.words.first().text.let { it in bulletChars || numberedLabel.matches(it) }
            val prevEndsSentence = prev.text.trimEnd().let { it.endsWith('.') || it.endsWith(':') || it.endsWith('?') || it.endsWith('!') }
            val prevShort = prev.right < (lines.maxOf { it.right }) * 0.75f
            val aligned = abs(l.x - prev.x) < 4f || (cur.size == 1 && l.x < prev.x) || abs(l.x - cur.last().x) < 4f
            val continuation = closeEnough && sameSize && !startsList && aligned && !(prevEndsSentence && prevShort) && prev.allBold == l.allBold
            if (continuation) cur.add(l) else { emit(); cur.add(l) }
        }
        emit()
        return out
    }

    private fun layoutLines(lines: List<TextLine>, leftMargin: Float, bodySize: Float): List<DocBlock> {
        val out = mutableListOf<DocBlock>()
        var prevBottom: Float? = null
        for (l in lines) {
            val gap = prevBottom?.let { (l.top - it).coerceAtLeast(0f) } ?: 0f
            // Preserve big horizontal gaps inside a line with tabs.
            val runs = mutableListOf<DocRun>()
            var prevRight: Float? = null
            for (w in l.words) {
                val sep = when { prevRight == null -> ""; w.x - prevRight > w.fontSize * 1.5f -> "\t"; else -> " " }
                val size = Math.round(w.fontSize * 2) / 2f
                val last = runs.lastOrNull()
                if (last != null && last.bold == w.bold && last.italic == w.italic && last.sizePt == size) runs[runs.lastIndex] = last.copy(text = last.text + sep + w.text)
                else runs.add(DocRun(sep + w.text, w.bold, w.italic, sizePt = size))
                prevRight = w.right
            }
            out.add(DocBlock.Paragraph(runs, indentLeftPt = (l.x - leftMargin).coerceAtLeast(0f), spaceBeforePt = minOf(gap, 36f), spaceAfterPt = 0f))
            prevBottom = l.bottom
        }
        return out
    }
}
