package com.docdesk.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SizeSplitterTest {
    @Test fun grouping() {
        assertEquals(listOf(listOf(0, 1), listOf(2), listOf(3, 4)), SizeSplitter.groups(listOf(4, 5, 9, 2, 3), 10))
        assertEquals(listOf(listOf(0), listOf(1), listOf(2)), SizeSplitter.groups(listOf(20, 20, 1), 10)) // oversized pages stand alone
        assertEquals(listOf(listOf(0, 1)), SizeSplitter.groups(listOf(3, 3), 10, overhead = 4))
    }

    @Test fun parse() {
        assertEquals(2L * 1024 * 1024, SizeSplitter.parseSize("2 MB"))
        assertEquals(500L * 1024, SizeSplitter.parseSize("500kb"))
        assertEquals((1.5 * 1024 * 1024).toLong(), SizeSplitter.parseSize("1,5"))
        assertNull(SizeSplitter.parseSize("abc")); assertNull(SizeSplitter.parseSize("1 kb")) // below the 20 KB minimum
    }
}
