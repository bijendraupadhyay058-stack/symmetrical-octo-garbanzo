package com.docdesk.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.docdesk.app.data.ThemeMode

// Brand colours chosen for WCAG AA contrast on both light and dark surfaces.
private val Light = lightColorScheme(
    primary = Color(0xFF1E4FA3), onPrimary = Color.White,
    primaryContainer = Color(0xFFD9E2FF), onPrimaryContainer = Color(0xFF001A43),
    secondary = Color(0xFF00696B), onSecondary = Color.White,
    secondaryContainer = Color(0xFFB9ECEC), onSecondaryContainer = Color(0xFF002020),
    tertiary = Color(0xFF8A5100), tertiaryContainer = Color(0xFFFFDCBE), onTertiaryContainer = Color(0xFF2C1600),
    error = Color(0xFFBA1A1A), errorContainer = Color(0xFFFFDAD6), onErrorContainer = Color(0xFF410002),
    background = Color(0xFFF9F9FF), surface = Color(0xFFF9F9FF), surfaceVariant = Color(0xFFE1E2EC),
    surfaceContainer = Color(0xFFEEEDF4), surfaceContainerHigh = Color(0xFFE8E7EF), surfaceContainerLow = Color(0xFFF3F3FA),
    onSurface = Color(0xFF1A1B21), onSurfaceVariant = Color(0xFF44474F), outline = Color(0xFF74777F),
)

private val Dark = darkColorScheme(
    primary = Color(0xFFB0C6FF), onPrimary = Color(0xFF002D6C),
    primaryContainer = Color(0xFF00429A), onPrimaryContainer = Color(0xFFD9E2FF),
    secondary = Color(0xFF9DCFD0), onSecondary = Color(0xFF003738),
    secondaryContainer = Color(0xFF004F50), onSecondaryContainer = Color(0xFFB9ECEC),
    tertiary = Color(0xFFFFB870), tertiaryContainer = Color(0xFF693C00), onTertiaryContainer = Color(0xFFFFDCBE),
    error = Color(0xFFFFB4AB), errorContainer = Color(0xFF93000A), onErrorContainer = Color(0xFFFFDAD6),
    background = Color(0xFF121318), surface = Color(0xFF121318), surfaceVariant = Color(0xFF44474F),
    surfaceContainer = Color(0xFF1E1F25), surfaceContainerHigh = Color(0xFF292A2F), surfaceContainerLow = Color(0xFF1A1B21),
    onSurface = Color(0xFFE3E2E9), onSurfaceVariant = Color(0xFFC4C6D0), outline = Color(0xFF8E9099),
)

private val AppTypography = Typography().let { t ->
    t.copy(
        titleLarge = t.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = t.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        bodyLarge = t.bodyLarge.copy(fontSize = 16.sp, lineHeight = 24.sp),
        labelLarge = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Medium, lineHeight = 20.sp),
    )
}

@Composable
fun DocDeskTheme(mode: ThemeMode, content: @Composable () -> Unit) {
    val dark = when (mode) { ThemeMode.SYSTEM -> isSystemInDarkTheme(); ThemeMode.LIGHT -> false; ThemeMode.DARK -> true }
    MaterialTheme(colorScheme = if (dark) Dark else Light, typography = AppTypography, content = content)
}
