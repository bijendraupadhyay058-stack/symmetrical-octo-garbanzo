package com.docdesk.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LayoutTest {
    private fun w(t: String, x: Float, y: Float, size: Float = 10f, bold: Boolean = false) = TextWord(t, x, y, t.length * size * 0.5f, size, size, bold)

    private fun lineOf(text: String, x: Float, y: Float, size: Float = 10f, bold: Boolean = false): List<TextWord> {
        var cx = x
        return text.split(" ").map { s -> w(s, cx, y, size, bold).also { cx += s.length * size * 0.5f + size * 0.3f } }
    }

    @Test fun paragraphsHeadingsBullets() {
        val words = lineOf("Quarterly Summary", 72f, 72f, 20f, bold = true) +
            lineOf("This report covers the first quarter and explains the", 72f, 110f) +
            lineOf("main results for the business.", 72f, 122f) +
            lineOf("• Revenue increased", 72f, 150f) +
            lineOf("• Costs were stable", 72f, 164f)
        val doc = PdfToDocBuilder.build(listOf(PageContent(PageText(0, 595f, 842f, words, TextSource.PDF_TEXT))), WordMode.EDITABLE)
        val paras = doc.blocks.filterIsInstance<DocBlock.Paragraph>()
        assertEquals(1, paras[0].headingLevel)
        assertEquals("This report covers the first quarter and explains the main results for the business.", paras[1].text)
        assertEquals("•", paras[2].listLabel)
        assertEquals("Revenue increased", paras[2].text)
        assertEquals(4, paras.size)
    }

    @Test fun repeatedHeaderFooterDetected() {
        val pages = (0 until 4).map { i ->
            val words = lineOf("ACME Pvt Ltd - Confidential", 200f, 20f) + lineOf("Body text for page ${i + 1}", 72f, 300f) + lineOf("Page ${i + 1} of 4", 260f, 800f)
            PageContent(PageText(i, 595f, 842f, words, TextSource.PDF_TEXT))
        }
        val doc = PdfToDocBuilder.build(pages, WordMode.EDITABLE)
        assertEquals("ACME Pvt Ltd - Confidential", (doc.header.single() as DocBlock.Paragraph).text)
        assertTrue(doc.blocks.filterIsInstance<DocBlock.Paragraph>().none { it.text.contains("Confidential") })
        assertEquals(3, doc.blocks.count { it is DocBlock.PageBreak })
    }

    @Test fun layoutModeKeepsLines() {
        val words = lineOf("Line one", 72f, 100f) + lineOf("Indented line two", 120f, 112f)
        val doc = PdfToDocBuilder.build(listOf(PageContent(PageText(0, 595f, 842f, words, TextSource.PDF_TEXT))), WordMode.LAYOUT)
        val paras = doc.blocks.filterIsInstance<DocBlock.Paragraph>()
        assertEquals(2, paras.size)
        assertEquals(48f, paras[1].indentLeftPt, 0.01f)
    }

    @Test fun sheetPagination() {
        val sheet = Sheet("S", mapOf(0 to mapOf(0 to SheetCell("x"))), 99, 19, emptyMap(), 10.0, emptyMap(), emptySet(), emptySet(), emptyList(), null, false)
        val actual = SheetPaginator.paginate(sheet, SheetPrintOptions(scaling = Scaling.ACTUAL))
        assertTrue(actual.size > 1)
        val fit = SheetPaginator.paginate(sheet, SheetPrintOptions(scaling = Scaling.FIT_COLUMNS))
        assertTrue(fit.all { it.cols.size == 20 })
        val one = SheetPaginator.paginate(sheet, SheetPrintOptions(scaling = Scaling.FIT_SHEET))
        assertEquals(1, one.size)
        val area = SheetPaginator.paginate(sheet.copy(printArea = CellRange(0, 0, 9, 2)), SheetPrintOptions())
        assertEquals(1, area.size); assertEquals(3, area[0].cols.size); assertEquals(10, area[0].rows.size)
    }
}
