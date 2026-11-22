package com.cashbook.app.ui.manage

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.AppSettings
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.BreakdownBar
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.categoryIcon
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.BudgetProgress
import com.cashbook.core.BudgetStatus
import com.cashbook.core.Budgets
import com.cashbook.core.CategoryKind
import com.cashbook.core.Money
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun budgetColor(p: BudgetProgress): Color = LocalFinanceColors.current.let {
    when (p.status) { BudgetStatus.OK -> it.income; BudgetStatus.NEAR -> it.warning; BudgetStatus.OVER -> it.expense }
}

@Composable
fun budgetStatusText(p: BudgetProgress): String {
    val f = LocalUiFormat.current
    return when (p.status) {
        BudgetStatus.OVER -> stringResource(R.string.budget_over, f.amount(-p.remaining))
        else -> stringResource(R.string.budget_left, f.amount(p.remaining))
    }
}

/** Monthly budgets per expense category for one cashbook, with this month's progress. */
@Composable
fun BudgetsScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val scope = currentScope(snap, s)
    var cashbookId by rememberSaveable { mutableStateOf(if (s.currentCashbookId != AppSettings.ALL_CASHBOOKS) scope.firstOrNull() ?: 0L else s.defaultCashbookId) }
    if (snap.cashbookById[cashbookId] == null) cashbookId = scope.firstOrNull() ?: 0
    var month by rememberSaveable { mutableStateOf(YearMonth.now().toString()) }
    var editing by remember { mutableStateOf<Long?>(null) }
    val ym = YearMonth.parse(month)

    val budgets = snap.budgets.filter { it.cashbookId == cashbookId }
    val budgeted = budgets.map { it.categoryId }.toSet()
    // Budgeted categories first, then the rest alphabetically
    val expenseCats = snap.categoriesOf(CategoryKind.EXPENSE).filter { it.parentId == null && (!it.archived || it.id in budgeted) }
        .sortedWith(compareBy({ it.id !in budgeted }, { it.name.lowercase() }))
    val progress = Budgets.progress(budgets, snap.txns, snap.categoryById, ym).associateBy { it.budget.categoryId }
    val totalBudget = budgets.sumOf { it.monthlyAmount }
    val totalSpent = progress.values.sumOf { it.spent }

    AppScaffold(title = stringResource(R.string.budgets), onBack = { nav.popBackStack() }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item {
                Column(Modifier.padding(16.dp)) {
                    val cbs = snap.cashbooks.filter { !it.archived }
                    if (cbs.size > 1) DropdownField(stringResource(R.string.cashbook), cbs.map { it.id }, cashbookId, labelOf = { snap.cashbookById[it]?.name ?: "" },
                        onSelect = { cashbookId = it }, modifier = Modifier.fillMaxWidth())
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = { month = ym.minusMonths(1).toString() }) { Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, stringResource(R.string.previous_month)) }
                        Text(ym.format(DateTimeFormatter.ofPattern("MMMM yyyy", Locale.getDefault())), Modifier.weight(1f), style = MaterialTheme.typography.titleMedium,
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                        IconButton(onClick = { month = ym.plusMonths(1).toString() }) { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, stringResource(R.string.next_month)) }
                    }
                    if (totalBudget > 0) Text(stringResource(R.string.budget_total, f.amount(totalSpent), f.amount(totalBudget)), style = MaterialTheme.typography.bodyMedium)
                    InfoBanner(stringResource(R.string.budgets_intro), Modifier.padding(top = 8.dp), icon = Icons.Filled.Info)
                }
            }
            items(expenseCats, key = { it.id }) { c ->
                val p = progress[c.id]
                Column(Modifier.fillMaxWidth().clickable { editing = c.id }.padding(horizontal = 16.dp, vertical = 10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(categoryIcon(c.icon), null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(c.name, style = MaterialTheme.typography.bodyLarge)
                            Text(if (p == null) stringResource(R.string.no_budget_tap) else budgetStatusText(p), style = MaterialTheme.typography.bodySmall,
                                color = if (p == null) MaterialTheme.colorScheme.onSurfaceVariant else budgetColor(p))
                        }
                        Text(p?.let { f.amount(it.budget.monthlyAmount) } ?: "—", style = MaterialTheme.typography.titleSmall)
                    }
                    if (p != null) BreakdownBar(stringResource(R.string.spent), "${f.amount(p.spent)} / ${f.amount(p.budget.monthlyAmount)}", p.percent, p.fraction, budgetColor(p))
                }
                HorizontalDivider()
            }
        }
    }

    editing?.let { catId ->
        val current = budgets.firstOrNull { it.categoryId == catId }
        var text by remember(catId) { mutableStateOf(current?.let { Money.toPlain(it.monthlyAmount) } ?: "") }
        val parsed = Money.parseOpening(text)
        AlertDialog(
            onDismissRequest = { editing = null },
            title = { Text(snap.categoryName(catId)) },
            text = {
                Column {
                    MoneyField(text, { text = it }, stringResource(R.string.monthly_budget),
                        error = if (parsed is Money.ParseResult.Error) stringResource(R.string.err_amount_invalid) else null)
                    Text(stringResource(R.string.budget_zero_removes), style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                TextButton(enabled = parsed is Money.ParseResult.Ok, onClick = {
                    val amt = (parsed as Money.ParseResult.Ok).paise
                    vm.run { ledger.setBudget(cashbookId, catId, amt) }
                    editing = null
                }) { Text(stringResource(R.string.save)) }
            },
            dismissButton = { TextButton(onClick = { editing = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

