package com.cashbook.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cashbook.app.data.ThemeMode

val Navy = Color(0xFF1A2B5C)
val NavyDark = Color(0xFF101C40)

/** Semantic colours. Always paired with an icon/label so meaning never relies on colour alone. */
@Immutable
data class FinanceColors(val income: Color, val expense: Color, val transfer: Color, val incomeBg: Color, val expenseBg: Color,
                         val transferBg: Color, val header: Color, val onHeader: Color, val warning: Color)

private val LightFinance = FinanceColors(
    income = Color(0xFF1B7F3B), expense = Color(0xFFC62828), transfer = Color(0xFF5E35B1),
    incomeBg = Color(0xFFE3F4E8), expenseBg = Color(0xFFFCE4E4), transferBg = Color(0xFFEDE7F6),
    header = Navy, onHeader = Color.White, warning = Color(0xFFB26A00),
)
private val DarkFinance = FinanceColors(
    income = Color(0xFF7BD89A), expense = Color(0xFFFF8A80), transfer = Color(0xFFC3B1F0),
    incomeBg = Color(0xFF173524), expenseBg = Color(0xFF3B1C1C), transferBg = Color(0xFF2A2140),
    header = Color(0xFF17213F), onHeader = Color(0xFFE6EAF5), warning = Color(0xFFFFC266),
)

val LocalFinanceColors = staticCompositionLocalOf { LightFinance }

private val LightScheme = lightColorScheme(
    primary = Navy, onPrimary = Color.White, primaryContainer = Color(0xFFDCE3F7), onPrimaryContainer = NavyDark,
    secondary = Color(0xFF3D5A99), onSecondary = Color.White, secondaryContainer = Color(0xFFDDE5FA), onSecondaryContainer = Color(0xFF14254F),
    tertiary = Color(0xFF5E35B1), background = Color(0xFFF4F6FA), onBackground = Color(0xFF151A24),
    surface = Color.White, onSurface = Color(0xFF151A24), surfaceVariant = Color(0xFFEDF0F6), onSurfaceVariant = Color(0xFF4A5060),
    surfaceContainer = Color(0xFFF0F2F7), surfaceContainerHigh = Color(0xFFE9ECF3), surfaceContainerLow = Color.White,
    outline = Color(0xFF7A8091), outlineVariant = Color(0xFFD3D8E2), error = Color(0xFFB3261E),
)
private val DarkScheme = darkColorScheme(
    primary = Color(0xFFB2C5FF), onPrimary = Color(0xFF0E1B3D), primaryContainer = Color(0xFF2A3D73), onPrimaryContainer = Color(0xFFDCE3F7),
    secondary = Color(0xFFBCC7E8), onSecondary = Color(0xFF1F2A44), secondaryContainer = Color(0xFF34405E), onSecondaryContainer = Color(0xFFDDE5FA),
    tertiary = Color(0xFFC3B1F0), background = Color(0xFF0E121B), onBackground = Color(0xFFE3E6EE),
    surface = Color(0xFF151A25), onSurface = Color(0xFFE3E6EE), surfaceVariant = Color(0xFF242B3A), onSurfaceVariant = Color(0xFFC2C7D3),
    surfaceContainer = Color(0xFF1A2030), surfaceContainerHigh = Color(0xFF222939), surfaceContainerLow = Color(0xFF151A25),
    outline = Color(0xFF8C92A2), outlineVariant = Color(0xFF3A4152), error = Color(0xFFFFB4AB),
)

private val AppTypography = Typography().let { t ->
    t.copy(
        headlineSmall = t.headlineSmall.copy(fontWeight = FontWeight.SemiBold),
        titleLarge = t.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = t.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        labelLarge = t.labelLarge.copy(fontWeight = FontWeight.SemiBold),
    )
}

val AmountStyle = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 16.sp)

@Composable
fun CashbookTheme(mode: ThemeMode, content: @Composable () -> Unit) {
    val dark = when (mode) { ThemeMode.SYSTEM -> isSystemInDarkTheme(); ThemeMode.LIGHT -> false; ThemeMode.DARK -> true }
    CompositionLocalProvider(LocalFinanceColors provides if (dark) DarkFinance else LightFinance) {
        MaterialTheme(
            colorScheme = if (dark) DarkScheme else LightScheme,
            typography = AppTypography,
            shapes = Shapes(small = RoundedCornerShape(10.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(22.dp)),
            content = content,
        )
    }
}

@Composable
fun isDarkTheme(mode: ThemeMode) = when (mode) { ThemeMode.SYSTEM -> isSystemInDarkTheme(); ThemeMode.LIGHT -> false; ThemeMode.DARK -> true }
