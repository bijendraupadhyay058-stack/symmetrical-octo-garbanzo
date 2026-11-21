package com.docdesk.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CropMathTest {
    @Test fun marginsFollowRotation() {
        // Display margins L=1, T=2, R=3, B=4 → box (left, bottom, right, top)
        assertArrayEquals(floatArrayOf(1f, 4f, 3f, 2f), PageTransform.displayMarginsToBox(0, 1f, 2f, 3f, 4f), 0f)
        assertArrayEquals(floatArrayOf(2f, 1f, 4f, 3f), PageTransform.displayMarginsToBox(90, 1f, 2f, 3f, 4f), 0f)
        assertArrayEquals(floatArrayOf(3f, 2f, 1f, 4f), PageTransform.displayMarginsToBox(180, 1f, 2f, 3f, 4f), 0f)
        assertArrayEquals(floatArrayOf(4f, 3f, 2f, 1f), PageTransform.displayMarginsToBox(270, 1f, 2f, 3f, 4f), 0f)
    }

    /** Cross-check the 90° mapping against the display→PDF transform used for annotations. */
    @Test fun consistentWithDisplayTransform() {
        val w = 600f; val h = 800f
        val t = PageTransform.displayToPdf(0f, 0f, w, h, 90) // displayed size is h × w
        // A point 10 pt below the displayed top edge, in the middle.
        val (x, _) = t.apply(h / 2, w - 10f)
        // Display top margin maps to the box LEFT side: x should be 10 from the left edge.
        org.junit.Assert.assertEquals(10f, x, 0.01f)
    }

    @Test fun contentBounds() {
        val w = 10; val h = 10
        val px = IntArray(w * h) { 255 }
        px[3 * w + 2] = 0; px[6 * w + 7] = 0
        assertArrayEquals(floatArrayOf(0.2f, 0.3f, 0.8f, 0.7f), PageTransform.contentBounds(px, w, h), 1e-6f)
        assertNull(PageTransform.contentBounds(IntArray(4) { 255 }, 2, 2))
    }
}
