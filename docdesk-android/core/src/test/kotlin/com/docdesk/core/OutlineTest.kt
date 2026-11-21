package com.docdesk.core

import org.junit.Test
import org.junit.Assert.assertEquals

class OutlineTest {
    private fun e(t: String, l: Int, p: Int = 0) = OutlineEntry(t, l, p)
    private fun titles(l: List<OutlineEntry>) = l.joinToString(",") { "${it.title}${it.level}" }

    @Test fun normalizeFixesJumps() {
        assertEquals("A0,B1,C2,D1", titles(Outline.normalize(listOf(e("A", 2), e("B", 3), e("C", 5), e("D", 1)))))
    }

    @Test fun moveCarriesChildren() {
        val l = listOf(e("A", 0), e("A1", 1), e("B", 0), e("B1", 1), e("C", 0))
        assertEquals("B0,B11,A0,A11,C0", titles(Outline.move(l, 2, up = true)))
        assertEquals("B0,B11,A0,A11,C0", titles(Outline.move(l, 0, up = false)))
        assertEquals(l, Outline.move(l, 0, up = true))
        assertEquals(l, Outline.move(l, 4, up = false))
        assertEquals(l, Outline.move(l, 1, up = true)) // first child can't leave its parent this way
    }

    @Test fun shiftAndRemove() {
        val l = listOf(e("A", 0), e("B", 0), e("B1", 1), e("C", 0))
        assertEquals("A0,B1,B12,C0", titles(Outline.shift(l, 1, +1)))
        assertEquals(l, Outline.shift(l, 0, +1))
        assertEquals("A0,B11,C0", titles(Outline.remove(Outline.shift(l, 1, +1), 1)))
    }

    private fun w(t: String, y: Float, size: Float, bold: Boolean = false) =
        t.split(" ").mapIndexed { i, s -> TextWord(s, 50f + i * 40f, y, 35f, size * 1.2f, size, bold) }

    @Test fun findsHeadings() {
        val p0 = PageText(0, 595f, 842f, w("Annual Report", 40f, 24f) + w("Introduction", 100f, 16f) +
            (0 until 10).flatMap { w("body text line number $it here", 130f + it * 14f, 10f) } + w("Page 1", 800f, 10f), TextSource.PDF_TEXT)
        val p1 = PageText(1, 595f, 842f, w("Results", 40f, 16f) + w("Key Figures", 70f, 10f, bold = true) +
            (0 until 10).flatMap { w("more body text in this report $it", 100f + it * 14f, 10f) } + w("Page 2", 800f, 10f), TextSource.PDF_TEXT)
        val h = HeadingFinder.find(listOf(p0, p1))
        assertEquals("Annual Report0,Introduction1,Results1,Key Figures2", titles(h))
        assertEquals(listOf(0, 0, 1, 1), h.map { it.page })
        assertEquals("Page 1 – Annual Report", HeadingFinder.perPage(listOf(p0))[0].title)
    }

    @Test fun skipsRunningHeadersButKeepsNumberedChapters() {
        val pages = (0 until 3).map { n ->
            PageText(n, 595f, 842f, w("ACME Annual Report", 20f, 14f, bold = true) + w("Chapter ${n + 1} Overview", 100f, 16f) +
                (0 until 12).flatMap { w("ordinary body text sentence $it", 130f + it * 14f, 10f) }, TextSource.PDF_TEXT)
        }
        assertEquals(listOf("Chapter 1 Overview", "Chapter 2 Overview", "Chapter 3 Overview"), HeadingFinder.find(pages).map { it.title })
    }
}
