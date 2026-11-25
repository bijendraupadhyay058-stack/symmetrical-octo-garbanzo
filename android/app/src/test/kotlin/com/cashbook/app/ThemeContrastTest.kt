package com.cashbook.app

import androidx.compose.material3.ColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.luminance
import com.cashbook.app.ui.theme.DarkFinance
import com.cashbook.app.ui.theme.DarkScheme
import com.cashbook.app.ui.theme.FinanceColors
import com.cashbook.app.ui.theme.LightFinance
import com.cashbook.app.ui.theme.LightScheme
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * WCAG 2.1 AA contrast (4.5:1 for normal text) for every text colour the app puts on its backgrounds, in light and
 * dark theme — including status chips, which draw a colour on a 12 % tint of itself.
 */
class ThemeContrastTest {
    private fun ratio(fg: Color, bg: Color): Double {
        val a = fg.compositeOver(bg).luminance() + 0.05; val b = bg.luminance() + 0.05
        return maxOf(a, b).toDouble() / minOf(a, b)
    }

    private fun pairs(name: String, c: ColorScheme, f: FinanceColors): List<Triple<String, Color, Color>> {
        val backgrounds = listOf("surface" to c.surface, "background" to c.background, "surfaceVariant" to c.surfaceVariant)
        val texts = listOf("onSurface" to c.onSurface, "onSurfaceVariant" to c.onSurfaceVariant, "primary" to c.primary, "error" to c.error,
            "income" to f.income, "expense" to f.expense, "transfer" to f.transfer, "warning" to f.warning)   // outline is for borders and icons (3:1), not text
        return backgrounds.flatMap { (bn, bg) -> texts.map { (tn, fg) -> Triple("$name $tn on $bn", fg, bg) } } +
            // status chips: text in a colour over a 12 % tint of that colour on the card surface
            texts.drop(2).map { (tn, fg) -> Triple("$name $tn chip", fg, fg.copy(alpha = 0.12f).compositeOver(c.surface)) } +
            listOf(Triple("$name income on incomeBg", f.income, f.incomeBg), Triple("$name expense on expenseBg", f.expense, f.expenseBg),
                Triple("$name transfer on transferBg", f.transfer, f.transferBg), Triple("$name onHeader on header", f.onHeader, f.header),
                Triple("$name onPrimary on primary", c.onPrimary, c.primary),
                Triple("$name onSecondaryContainer on secondaryContainer", c.onSecondaryContainer, c.secondaryContainer),
                Triple("$name onPrimaryContainer on primaryContainer", c.onPrimaryContainer, c.primaryContainer))
    }

    @Test fun textMeetsAaContrast() {
        val all = pairs("light", LightScheme, LightFinance) + pairs("dark", DarkScheme, DarkFinance)
        val failing = all.map { (n, fg, bg) -> n to ratio(fg, bg) }.filter { it.second < 4.5 }
        println("CONTRAST failing: " + failing.joinToString { "%s %.2f".format(it.first, it.second) })
        assertEquals(failing.joinToString("\n") { "%s: %.2f:1".format(it.first, it.second) }, 0, failing.size)
    }
}
