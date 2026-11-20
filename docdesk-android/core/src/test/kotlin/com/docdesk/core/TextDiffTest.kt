package com.docdesk.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TextDiffTest {
    private fun doc(vararg lines: String) = lines.mapIndexed { i, t -> DiffLine(0, i, t) }

    @Test fun identical() = assertTrue(TextDiff.diff(doc("a b", "c d"), doc("a  b", "c d")).isEmpty())

    @Test fun changedAmountIsPinpointed() {
        val c = TextDiff.diff(
            doc("AGREEMENT", "The monthly rent shall be Rs. 25,000 payable on the 5th.", "Signed"),
            doc("AGREEMENT", "The monthly rent shall be Rs. 27,500 payable on the 5th.", "Signed"),
        )
        assertEquals(1, c.size)
        val m = c[0] as Change.Modified
        assertEquals(setOf(6), m.oldWords); assertEquals(setOf(6), m.newWords) // "25,000" -> "27,500"
    }

    @Test fun addedAndRemoved() {
        val c = TextDiff.diff(doc("one", "two", "three"), doc("one", "three", "four entirely new clause"))
        assertTrue(c.any { it is Change.Removed && it.old.text == "two" })
        assertTrue(c.any { it is Change.Added && it.new.text == "four entirely new clause" })
    }

    @Test fun ignoreCase() = assertTrue(TextDiff.diff(doc("Total Amount"), doc("TOTAL AMOUNT"), ignoreCase = true).isEmpty())
}
