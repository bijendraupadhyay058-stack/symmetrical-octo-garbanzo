package com.docdesk.core

/**
 * Maps a point on a page *as displayed* (after /Rotate is applied) to PDF user space.
 * Display space "D": origin at the bottom-left of the displayed page, y up, units = points.
 * Returned matrix (a, b, c, d, e, f) satisfies x = a·X + c·Y + e, y = b·X + d·Y + f,
 * which is the operand order of the PDF "cm" operator.
 */
object PageTransform {
    data class Affine(val a: Float, val b: Float, val c: Float, val d: Float, val e: Float, val f: Float) {
        fun apply(x: Float, y: Float) = (a * x + c * y + e) to (b * x + d * y + f)
    }

    /** Size of the page as displayed, given its crop box size and rotation. */
    fun displaySize(boxW: Float, boxH: Float, rotation: Int): Pair<Float, Float> =
        if (normalise(rotation) % 180 == 0) boxW to boxH else boxH to boxW

    fun normalise(rotation: Int) = ((rotation % 360) + 360) % 360

    fun displayToPdf(x0: Float, y0: Float, w: Float, h: Float, rotation: Int): Affine = when (normalise(rotation)) {
        90 -> Affine(0f, 1f, -1f, 0f, x0 + w, y0)
        180 -> Affine(-1f, 0f, 0f, -1f, x0 + w, y0 + h)
        270 -> Affine(0f, -1f, 1f, 0f, x0, y0 + h)
        else -> Affine(1f, 0f, 0f, 1f, x0, y0)
    }

    /**
     * Converts margins measured on the page AS DISPLAYED (left, top, right, bottom) into margins
     * on the unrotated PDF box sides (left, bottom, right, top) for the given /Rotate.
     */
    fun displayMarginsToBox(rotation: Int, left: Float, top: Float, right: Float, bottom: Float): FloatArray = when (normalise(rotation)) {
        90 -> floatArrayOf(top, left, bottom, right)    // display top = box left, display left = box bottom
        180 -> floatArrayOf(right, top, left, bottom)
        270 -> floatArrayOf(bottom, right, top, left)
        else -> floatArrayOf(left, bottom, right, top)
    }

    /**
     * Finds the content box in a greyscale image (0 = black, 255 = white): the area that is not
     * near-white. Returns normalised (left, top, right, bottom) or null for a blank page.
     */
    fun contentBounds(pixels: IntArray, width: Int, height: Int, threshold: Int = 235): FloatArray? {
        var minX = width; var minY = height; var maxX = -1; var maxY = -1
        for (y in 0 until height) for (x in 0 until width) {
            if (pixels[y * width + x] < threshold) { if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y }
        }
        if (maxX < 0) return null
        return floatArrayOf(minX.toFloat() / width, minY.toFloat() / height, (maxX + 1f) / width, (maxY + 1f) / height)
    }
}
