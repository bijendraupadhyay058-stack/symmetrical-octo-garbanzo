package com.docdesk.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SelectionTest {
    private fun line(y: Float, text: String, x0: Float = 50f): List<TextWord> {
        var x = x0
        return text.split(" ").map { w -> TextWord(w, x, y, w.length * 5f, 10f, 10f).also { x += w.length * 5f + 3f } }
    }
    private val words = line(100f, "The quick brown fox") + line(115f, "jumps over the lazy dog") + line(130f, "and runs away")

    @Test fun singleLinePartial() {
        // From middle of "quick" to "brown"
        val r = TextSelection.select(words, 75f, 105f, 110f, 105f)
        assertEquals(1, r.size); assertEquals("quick brown", r[0].text)
    }

    @Test fun multiLineReadingOrder() {
        val r = TextSelection.select(words, 100f, 104f, 70f, 134f)
        assertEquals(listOf("brown fox", "jumps over the lazy dog", "and runs"), r.map { it.text })
    }

    @Test fun reversedDragSameResult() {
        assertEquals(TextSelection.select(words, 100f, 104f, 70f, 134f), TextSelection.select(words, 70f, 134f, 100f, 104f))
    }

    @Test fun noTextReturnsEmpty() = assertTrue(TextSelection.select(words, 300f, 400f, 350f, 420f).isEmpty())

    @Test fun lineAtPoint() = assertEquals("jumps over the lazy dog", TextSelection.lineAt(words, 80f, 120f)!!.text)

    @Test fun labels() {
        assertEquals("Page 3 of 10", LabelTemplate.render("Page {n} of {total}", 3, 10))
        assertEquals("INV-0042", LabelTemplate.render("INV-{n:4}", 42, 99))
        assertEquals("a.pdf 01-04-2025", LabelTemplate.render("{file} {date}", 1, 1, "01-04-2025", "a.pdf"))
    }
}
