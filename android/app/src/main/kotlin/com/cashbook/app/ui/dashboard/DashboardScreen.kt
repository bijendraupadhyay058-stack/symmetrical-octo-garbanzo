package com.cashbook.app.ui.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.Backup
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.ReceiptLong
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.BreakdownBar
import com.cashbook.app.ui.components.CashbookSwitcher
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.IncomeExpenseChart
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MonthBar
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.TxnRow
import com.cashbook.app.ui.components.accountIcon
import com.cashbook.app.ui.components.accountTypeLabel
import com.cashbook.app.ui.components.periodLabel
import com.cashbook.app.ui.components.typeIcon
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.manage.budgetColor
import com.cashbook.app.ui.manage.budgetStatusText
import com.cashbook.app.ui.recurring.ruleTitle
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.nav.openTab
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.AccountType
import com.cashbook.core.Budgets
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.DateRange
import com.cashbook.core.Ledger
import com.cashbook.core.Money
import com.cashbook.core.PeriodPreset
import com.cashbook.core.Periods
import com.cashbook.core.TxnChronological
import com.cashbook.core.TxnType
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun DashboardScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val today = LocalDate.now()

    var preset by rememberSaveable { mutableStateOf(PeriodPreset.THIS_MONTH) }
    var customStart by rememberSaveable { mutableLongStateOf(today.withDayOfMonth(1).toEpochDay()) }
    var customEnd by rememberSaveable { mutableLongStateOf(today.toEpochDay()) }
    var accountFilter by rememberSaveable { mutableLongStateOf(0L) }

    val scope = currentScope(snap, s)
    val accounts = snap.accountsOf(scope)
    val selected = if (accountFilter == 0L || accounts.none { it.id == accountFilter }) accounts else accounts.filter { it.id == accountFilter }
    val ids = selected.map { it.id }.toSet()
    val txns = snap.txnsOf(scope)
    val range = Periods.resolve(preset, today, s.weekStart,
        DateRange(LocalDate.ofEpochDay(minOf(customStart, customEnd)), LocalDate.ofEpochDay(maxOf(customStart, customEnd))))
    val todayT = Ledger.totals(txns, ids, DateRange(today, today))
    val monthRange = Periods.resolve(PeriodPreset.THIS_MONTH, today)
    val monthT = Ledger.totals(txns, ids, monthRange)
    val periodT = Ledger.totals(txns, ids, range)
    val balanceDate = minOf(today, range.end)
    fun balanceOf(type: AccountType?) = selected.filter { type == null || it.type == type }.sumOf { Ledger.balanceAsOf(it, txns, balanceDate) }

    AppScaffold(
        title = stringResource(R.string.nav_dashboard),
        titleContent = {
            CashbookSwitcher(snap, s, stringResource(R.string.nav_dashboard), onSelect = { id -> vm.updateSettings { it.copy(currentCashbookId = id) } },
                onManage = { nav.navigate(Routes.CASHBOOKS) })
        },
        actions = {
            if (s.lockEnabled) IconButton(onClick = { vm.lockNow() }) { Icon(Icons.Filled.Lock, stringResource(R.string.lock_now)) }
        },
    ) { pad ->
        if (scope.isEmpty()) {
            EmptyState(Icons.Filled.ReceiptLong, stringResource(R.string.no_cashbook), Modifier.padding(pad)) {
                OutlinedButton(onClick = { nav.navigate(Routes.cashbook(0)) }) { Text(stringResource(R.string.create_cashbook)) }
            }
            return@AppScaffold
        }
        LazyColumn(Modifier.fillMaxSize().padding(pad), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            // ----- filters -----
            item {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(PeriodPreset.TODAY, PeriodPreset.THIS_WEEK, PeriodPreset.THIS_MONTH, PeriodPreset.THIS_FY, PeriodPreset.CUSTOM).forEach { p ->
                        FilterChip(selected = preset == p, onClick = { preset = p }, label = { Text(periodLabel(p)) })
                    }
                }
                if (preset == PeriodPreset.CUSTOM) {
                    Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        DateField(stringResource(R.string.from_date), LocalDate.ofEpochDay(customStart), { customStart = it.toEpochDay() }, Modifier.weight(1f))
                        DateField(stringResource(R.string.to_date), LocalDate.ofEpochDay(customEnd), { customEnd = it.toEpochDay() }, Modifier.weight(1f))
                    }
                }
                if (accounts.size > 1) {
                    val opts = listOf(0L) + accounts.filter { !it.archived }.map { it.id }
                    DropdownField(stringResource(R.string.account), opts, accountFilter.takeIf { it in opts } ?: 0L,
                        labelOf = { id -> if (id == 0L) stringResource(R.string.all_accounts) else snap.accountById[id]?.name ?: "" },
                        onSelect = { accountFilter = it }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                }
            }
            // ----- balance hero -----
            item {
                Card(colors = CardDefaults.cardColors(containerColor = fc.header), shape = MaterialTheme.shapes.large) {
                    Column(Modifier.fillMaxWidth().padding(20.dp)) {
                        Text(stringResource(R.string.total_balance), color = fc.onHeader.copy(alpha = 0.8f), style = MaterialTheme.typography.labelLarge)
                        Text(f.amount(balanceOf(null)), color = fc.onHeader, fontSize = 30.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                        Text(stringResource(R.string.as_of, f.date(balanceDate)), color = fc.onHeader.copy(alpha = 0.75f), style = MaterialTheme.typography.labelSmall)
                        Spacer(Modifier.height(14.dp))
                        // One row per account type: robust for long labels (Hindi) and large amounts.
                        listOf(AccountType.CASH, AccountType.BANK, AccountType.WALLET).forEach { t ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(accountIcon(t), null, Modifier.size(16.dp), tint = fc.onHeader.copy(alpha = 0.8f))
                                Spacer(Modifier.width(8.dp))
                                Text(accountTypeLabel(t), color = fc.onHeader.copy(alpha = 0.85f), style = MaterialTheme.typography.bodyMedium,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                                Text(f.amount(balanceOf(t)), color = fc.onHeader, style = MaterialTheme.typography.titleSmall, maxLines = 1)
                            }
                        }
                    }
                }
            }
            // ----- summary cards -----
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        StatCard(stringResource(R.string.today_income), todayT.income, TxnType.INCOME, Modifier.weight(1f))
                        StatCard(stringResource(R.string.today_expenses), todayT.expense, TxnType.EXPENSE, Modifier.weight(1f))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        StatCard(stringResource(R.string.month_income), monthT.income, TxnType.INCOME, Modifier.weight(1f))
                        StatCard(stringResource(R.string.month_expenses), monthT.expense, TxnType.EXPENSE, Modifier.weight(1f))
                    }
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.net_for_period, periodLabel(preset)), style = MaterialTheme.typography.labelLarge)
                                Text(range.label(s.dateFormat), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(stringResource(R.string.income_minus_expenses, f.amount(periodT.income), f.amount(periodT.expense)),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text(f.amount(periodT.net), style = MaterialTheme.typography.titleLarge, color = if (periodT.net < 0) fc.expense else fc.income)
                                Text(stringResource(if (periodT.net < 0) R.string.deficit else R.string.surplus), style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
            // ----- quick actions -----
            item {
                SectionCard(stringResource(R.string.quick_actions)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        QuickAction(stringResource(R.string.add_income), typeIcon(TxnType.INCOME), fc.income) { nav.navigate(Routes.newTxn(TxnType.INCOME)) }
                        QuickAction(stringResource(R.string.add_expense), typeIcon(TxnType.EXPENSE), fc.expense) { nav.navigate(Routes.newTxn(TxnType.EXPENSE)) }
                        QuickAction(stringResource(R.string.add_transfer), typeIcon(TxnType.TRANSFER), fc.transfer) { nav.navigate(Routes.newTxn(TxnType.TRANSFER)) }
                        QuickAction(stringResource(R.string.view_reports), Icons.Filled.Assessment, MaterialTheme.colorScheme.primary) { nav.openTab(Routes.REPORTS) }
                    }
                }
            }
            // ----- receivables & payables -----
            val openInvoices = snap.invoiceBalances(today).filter { it.invoice.cashbookId in scope && it.outstanding > 0 }
            if (openInvoices.isNotEmpty()) item {
                val sale = openInvoices.filter { it.invoice.kind == InvoiceKind.SALE }
                val purchase = openInvoices.filter { it.invoice.kind == InvoiceKind.PURCHASE }
                SectionCard(stringResource(R.string.receivables_payables), action = {
                    TextButton(onClick = { nav.navigate(Routes.INVOICES) }) { Text(stringResource(R.string.view_all)) }
                }) {
                    Row(Modifier.fillMaxWidth()) {
                        Column(Modifier.weight(1f)) {
                            Text(stringResource(R.string.to_receive), style = MaterialTheme.typography.labelLarge)
                            Text(f.amount(sale.sumOf { it.outstanding }), style = MaterialTheme.typography.titleMedium, color = fc.income)
                            Text(stringResource(R.string.n_overdue, sale.count { it.status == InvoiceStatus.OVERDUE }), style = MaterialTheme.typography.labelSmall,
                                color = if (sale.any { it.status == InvoiceStatus.OVERDUE }) fc.expense else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Column(Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                            Text(stringResource(R.string.to_pay), style = MaterialTheme.typography.labelLarge)
                            Text(f.amount(purchase.sumOf { it.outstanding }), style = MaterialTheme.typography.titleMedium, color = fc.expense)
                            Text(stringResource(R.string.n_overdue, purchase.count { it.status == InvoiceStatus.OVERDUE }), style = MaterialTheme.typography.labelSmall,
                                color = if (purchase.any { it.status == InvoiceStatus.OVERDUE }) fc.expense else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
            // ----- low stock -----
            val lowStock = snap.catalog.filter { it.tracksStock && !it.archived && it.reorderLevelMilli > 0 && snap.onHand(it) <= it.reorderLevelMilli }
            if (lowStock.isNotEmpty()) item {
                SectionCard(stringResource(R.string.low_stock), action = { TextButton(onClick = { nav.navigate(Routes.CATALOG) }) { Text(stringResource(R.string.view_all)) } }) {
                    lowStock.take(5).forEach { c ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                            Text(c.name, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(stringResource(R.string.stock_vs_reorder, com.cashbook.core.Gst.formatQuantity(snap.onHand(c)), com.cashbook.core.Gst.formatQuantity(c.reorderLevelMilli), c.unit),
                                color = fc.expense, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
            // ----- recurring entries waiting for confirmation -----
            val dueRules = snap.recurring.filter { it.cashbookId in scope && it.active && !it.autoPost && it.nextDate?.let { d -> !d.isAfter(today) } == true }
            if (dueRules.isNotEmpty()) item {
                val transferLabel = stringResource(R.string.type_transfer)
                SectionCard(stringResource(R.string.due_recurring), action = {
                    TextButton(onClick = { nav.navigate(Routes.RECURRING) }) { Text(stringResource(R.string.manage)) }
                }) {
                    dueRules.forEach { r ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(ruleTitle(r, snap, transferLabel), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(stringResource(R.string.due_on, f.date(r.nextDate!!)) + " · " + f.amount(r.amount), style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            TextButton(onClick = { vm.run { ledger.skipNextOccurrence(r.id) } }) { Text(stringResource(R.string.skip)) }
                            FilledTonalButton(onClick = { vm.run { ledger.postNextOccurrence(r.id) } }) { Text(stringResource(R.string.post)) }
                        }
                    }
                }
            }
            // ----- budgets -----
            val budgetProgress = Budgets.progress(snap.budgets.filter { it.cashbookId in scope }, txns, snap.categoryById, YearMonth.from(today))
            if (budgetProgress.isNotEmpty()) item {
                SectionCard(stringResource(R.string.budgets_this_month), action = {
                    TextButton(onClick = { nav.navigate(Routes.BUDGETS) }) { Text(stringResource(R.string.manage)) }
                }) {
                    budgetProgress.take(5).forEach { p ->
                        BreakdownBar(snap.categoryName(p.budget.categoryId), "${f.amount(p.spent)} / ${f.amount(p.budget.monthlyAmount)}", budgetStatusText(p),
                            p.fraction, budgetColor(p))
                    }
                }
            }
            // ----- chart -----
            item {
                var months by rememberSaveable { mutableStateOf(6) }
                val end = YearMonth.from(range.end.let { if (it.isAfter(today)) today else it })
                val fmt = DateTimeFormatter.ofPattern("MMM", Locale.getDefault())
                val bars = (months - 1 downTo 0).map { back ->
                    val m = end.minusMonths(back.toLong())
                    val t = Ledger.totals(txns, ids, DateRange(m.atDay(1), m.atEndOfMonth()))
                    MonthBar(m.format(fmt), t.income, t.expense)
                }
                val a11y = bars.joinToString("; ") { "${it.label}: ${f.amount(it.income)} / ${f.amount(it.expense)}" }
                SectionCard(stringResource(R.string.monthly_chart), action = {
                    Row { listOf(6, 12).forEach { n -> TextButton(onClick = { months = n }) { Text(stringResource(R.string.n_months, n), fontWeight = if (months == n) FontWeight.Bold else null) } } }
                }) {
                    IncomeExpenseChart(bars, stringResource(R.string.income), stringResource(R.string.expenses), a11y)
                }
            }
            // ----- expense breakdown -----
            item {
                val exp = txns.filter { it.type == TxnType.EXPENSE && it.date in range && it.accountId in ids }
                val total = exp.sumOf { it.amount }
                val top = exp.groupBy { it.categoryId }.map { (c, l) -> c to l.sumOf { it.amount } }.sortedByDescending { it.second }.take(5)
                SectionCard(stringResource(R.string.expense_breakdown)) {
                    if (top.isEmpty()) Text(stringResource(R.string.no_expenses_period), style = MaterialTheme.typography.bodySmall)
                    top.forEach { (c, amt) ->
                        BreakdownBar(snap.categoryName(c).ifBlank { stringResource(R.string.uncategorised) }, f.amount(amt), Money.percent(amt, total),
                            if (total == 0L) 0f else amt.toFloat() / total, fc.expense)
                    }
                }
            }
            // ----- account balances -----
            item {
                SectionCard(stringResource(R.string.account_balances), action = {
                    TextButton(onClick = { scope.singleOrNull()?.let { nav.navigate(Routes.accounts(it)) } ?: nav.navigate(Routes.CASHBOOKS) }) { Text(stringResource(R.string.manage)) }
                }) {
                    accounts.filter { !it.archived }.forEach { a ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(accountIcon(a.type), null, tint = MaterialTheme.colorScheme.primary)
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text(a.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(accountTypeLabel(a.type) + if (scope.size > 1) " · " + (snap.cashbookById[a.cashbookId]?.name ?: "") else "",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            val bal = Ledger.balanceAsOf(a, txns, today)
                            Text(f.amount(bal), style = MaterialTheme.typography.titleSmall, color = if (bal < 0) fc.expense else MaterialTheme.colorScheme.onSurface)
                        }
                    }
                    Text(stringResource(R.string.as_of, f.date(today)), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            // ----- recent -----
            item {
                val recent = txns.filter { Ledger.touches(it, ids) }.sortedWith(TxnChronological.reversed()).take(5)
                SectionCard(stringResource(R.string.recent_transactions), action = {
                    TextButton(onClick = { nav.openTab(Routes.TRANSACTIONS) }) { Text(stringResource(R.string.view_all)) }
                }) {
                    if (recent.isEmpty()) Text(stringResource(R.string.no_transactions_yet), style = MaterialTheme.typography.bodySmall)
                    recent.forEachIndexed { i, t ->
                        if (i > 0) HorizontalDivider()
                        Column(Modifier.padding(horizontal = 0.dp)) { TxnRow(t, snap, onClick = { nav.navigate(Routes.txn(t.id)) }, showCashbook = scope.size > 1) }
                    }
                }
            }
            // ----- backup status -----
            item {
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.Backup, null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(stringResource(R.string.backup_status), style = MaterialTheme.typography.labelLarge)
                            Text(if (s.lastBackupAt > 0) stringResource(R.string.last_backup, f.dateTime(s.lastBackupAt)) else stringResource(R.string.never_backed_up),
                                style = MaterialTheme.typography.bodySmall)
                        }
                        AssistChip(onClick = { nav.navigate(Routes.BACKUP) }, label = { Text(stringResource(R.string.backup_now)) })
                    }
                }
            }
        }
    }
}

@Composable
private fun StatCard(label: String, amount: Long, type: TxnType, modifier: Modifier) {
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val color = if (type == TxnType.INCOME) fc.income else fc.expense
    val bg = if (type == TxnType.INCOME) fc.incomeBg else fc.expenseBg
    Card(modifier, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), elevation = CardDefaults.cardElevation(1.dp)) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(typeIcon(type), null, Modifier.size(18.dp).background(bg, RoundedCornerShape(50)).padding(2.dp), tint = color)
                Spacer(Modifier.width(6.dp))
                Text(label, style = MaterialTheme.typography.labelMedium, maxLines = 2)
            }
            Spacer(Modifier.height(6.dp))
            Text(f.amount(amount), style = MaterialTheme.typography.titleMedium, color = color, maxLines = 1)
        }
    }
}

@Composable
private fun QuickAction(label: String, icon: ImageVector, color: Color, onClick: () -> Unit) {
    // The whole tile (icon + label) is one touch target with a single accessible label.
    Column(horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier.width(80.dp).clip(MaterialTheme.shapes.small).clickable(onClickLabel = label, role = Role.Button, onClick = onClick).padding(vertical = 4.dp)) {
        Box(Modifier.size(52.dp).background(MaterialTheme.colorScheme.secondaryContainer, CircleShape), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = color)
        }
        Spacer(Modifier.height(4.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, maxLines = 2, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}
