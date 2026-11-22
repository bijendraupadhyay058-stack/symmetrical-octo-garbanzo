package com.cashbook.app.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.cashbook.app.ui.theme.LocalFinanceColors

data class MonthBar(val label: String, val income: Long, val expense: Long)

/**
 * Grouped bar chart of income vs expenses per month (drawn with Compose Canvas — no extra chart
 * dependency). A text description is exposed to screen readers.
 */
@Composable
fun IncomeExpenseChart(bars: List<MonthBar>, incomeLabel: String, expenseLabel: String, a11y: String) {
    val fc = LocalFinanceColors.current
    val grid = MaterialTheme.colorScheme.outlineVariant
    val max = (bars.maxOfOrNull { maxOf(it.income, it.expense) } ?: 0L).coerceAtLeast(1L)
    Column(Modifier.semantics { contentDescription = a11y }) {
        Canvas(Modifier.fillMaxWidth().height(150.dp)) {
            val n = bars.size.coerceAtLeast(1)
            val slot = size.width / n
            val barW = (slot * 0.32f).coerceAtMost(22.dp.toPx())
            for (i in 0..3) {
                val y = size.height * i / 4f
                drawLine(grid, Offset(0f, y), Offset(size.width, y), 1f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 6f)))
            }
            drawLine(grid, Offset(0f, size.height), Offset(size.width, size.height), 2f)
            bars.forEachIndexed { i, b ->
                val cx = slot * i + slot / 2
                val hi = size.height * (b.income.toFloat() / max)
                val he = size.height * (b.expense.toFloat() / max)
                drawRoundRect(fc.income, Offset(cx - barW - 2f, size.height - hi), Size(barW, hi), CornerRadius(6f, 6f))
                drawRoundRect(fc.expense, Offset(cx + 2f, size.height - he), Size(barW, he), CornerRadius(6f, 6f))
            }
        }
        Row(Modifier.fillMaxWidth()) {
            bars.forEach { Text(it.label, Modifier.weight(1f), style = MaterialTheme.typography.labelSmall, maxLines = 1,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center) }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Legend(fc.income, "▲ $incomeLabel"); Spacer(Modifier.width(16.dp)); Legend(fc.expense, "▼ $expenseLabel")
        }
    }
}

@Composable
private fun Legend(color: androidx.compose.ui.graphics.Color, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(10.dp).background(color, RoundedCornerShape(2.dp)))
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.labelSmall)
    }
}

/** Horizontal bar with label, value and percentage text. */
@Composable
fun BreakdownBar(label: String, value: String, percent: String, fraction: Float, color: androidx.compose.ui.graphics.Color) {
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("$value · $percent", style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(4.dp))
        Box(Modifier.fillMaxWidth().height(8.dp).background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(4.dp))) {
            Box(Modifier.fillMaxWidth(fraction.coerceIn(0.01f, 1f)).height(8.dp).background(color, RoundedCornerShape(4.dp)))
        }
    }
}
