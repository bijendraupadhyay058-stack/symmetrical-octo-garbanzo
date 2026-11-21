package com.docdesk.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LinkFinderTest {
    private fun line(t: String, y: Float = 100f) = t.split(" ").let { ws -> var x = 50f; ws.map { w -> TextWord(w, x, y, w.length * 6f, 12f, 10f).also { x += w.length * 6f + 4f } } }

    @Test fun findsWebEmailPhone() {
        val words = line("Visit www.example.com/help, or https://gst.gov.in. Mail support@acme.co.in today.") +
            line("Call +91 98765 43210 or 1800 123 4567. Paid 12.50 on 1.5.2024 version 2.0", 120f)
        val f = LinkFinder.find(words)
        val got = f.map { "${it.kind}:${it.target}" }
        assertEquals(listOf("EMAIL:mailto:support@acme.co.in", "WEB:https://www.example.com/help", "WEB:https://gst.gov.in",
            "PHONE:tel:+919876543210", "PHONE:tel:18001234567"), got)
        // "+91 98765 43210" spans three words but becomes one rectangle.
        val ph = f.first { it.kind == FoundLink.Kind.PHONE }
        assertEquals(1, ph.rects.size)
        assertTrue(ph.rects[0][2] - ph.rects[0][0] > 80f)
        // The trailing comma is not part of the link box.
        val help = f.first { it.target.endsWith("/help") }
        assertEquals(50f + 5 * 6f + 4f + 20 * 6f, help.rects[0][2], 0.5f)
    }

    @Test fun ignoresNonLinks() {
        assertEquals(emptyList<FoundLink>(), LinkFinder.find(line("Total Rs. 1,234.50 on 01.02.2024 Ref no. A.B. 123456")))
        assertEquals(listOf(FoundLink.Kind.WEB), LinkFinder.find(line("see docs.python.org"), setOf(FoundLink.Kind.WEB)).map { it.kind })
        assertEquals(emptyList<FoundLink>(), LinkFinder.find(line("mail a@b.com"), setOf(FoundLink.Kind.WEB)))
    }
}
