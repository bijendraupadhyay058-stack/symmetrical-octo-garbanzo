package com.docdesk.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class ImpositionTest {
    @Test fun gridsAndSlots() {
        assertEquals(Imposition.Grid(2, 1, true), Imposition.grid(2))
        assertEquals(Imposition.Grid(1, 2, false), Imposition.grid(2, sourceLandscape = true))
        val s = Imposition.slots(200f, 100f, Imposition.Grid(2, 2, false), 10f, 0f)
        assertEquals(4, s.size)
        assertArrayEquals(floatArrayOf(10f, 50f, 90f, 40f), s[0], 0.01f) // top-left first
        assertArrayEquals(floatArrayOf(100f, 10f, 90f, 40f), s[3], 0.01f) // bottom-right last
        // A4 portrait page into a wide slot: height-limited, centred horizontally.
        val f = Imposition.fit(100f, 200f, floatArrayOf(0f, 0f, 200f, 100f))
        assertArrayEquals(floatArrayOf(0.5f, 75f, 0f), f, 0.01f)
    }

    @Test fun bookletOrder() {
        assertEquals(listOf(7 to 0, 1 to 6, 5 to 2, 3 to 4), Imposition.booklet(8))
        // 5 pages pad to 8: blanks are -1.
        assertEquals(listOf(-1 to 0, 1 to -1, -1 to 2, 3 to 4), Imposition.booklet(5))
        assertEquals(listOf(-1 to 0, -1 to -1), Imposition.booklet(1))
    }

    @Test fun collateScans() {
        assertEquals(listOf(false to 0, true to 2, false to 1, true to 1, false to 2, true to 0), Imposition.collate(3, 3, true))
        assertEquals(listOf(false to 0, true to 0, false to 1, false to 2), Imposition.collate(3, 1, false))
    }
}
