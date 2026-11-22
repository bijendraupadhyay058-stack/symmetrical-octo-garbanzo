package com.cashbook.app.ui.transactions

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.Snapshot
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.CashbookSwitcher
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.TxnRow
import com.cashbook.app.ui.components.paymentModeLabel
import com.cashbook.app.ui.components.periodLabel
import com.cashbook.app.ui.components.sortLabel
import com.cashbook.app.ui.components.txnTypeLabel
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.nav.Routes
import com.cashbook.core.DateRange
import com.cashbook.core.Ledger
import com.cashbook.core.Money
import com.cashbook.core.PaymentMode
import com.cashbook.core.PeriodPreset
import com.cashbook.core.Periods
import com.cashbook.core.SortOrder
import com.cashbook.core.TxnChronological
import com.cashbook.core.TxnFilter
import com.cashbook.core.TxnQuery
import com.cashbook.core.TxnType
import java.time.LocalDate

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TransactionListScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val filter by vm.listFilter.collectAsStateWithLifecycle()
    val sort by vm.listSort.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    var showFilters by rememberSaveable { mutableStateOf(false) }
    var sortMenu by remember { mutableStateOf(false) }

    val scope = currentScope(snap, s)
    val base = snap.txnsOf(scope)
    val results = TxnQuery.sort(TxnQuery.apply(base, filter, snap.names, snap.withAttachments), sort)
    // Running balance: only meaningful for exactly one account in chronological order.
    val singleAccount = filter.accountIds.singleOrNull()?.let { snap.accountById[it] }
    val running: Map<Long, Long> = if (singleAccount != null && sort == SortOrder.OLDEST && filter.copy(accountIds = emptySet(), range = null).isActive.not()) {
        Ledger.running(singleAccount, base.filter { Ledger.touches(it, setOf(singleAccount.id)) }).associate { it.txn.id to it.balance }
    } else emptyMap()
    val totals = Ledger.totals(results, snap.accountsOf(scope).map { it.id }.toSet().let { all -> if (filter.accountIds.isEmpty()) all else filter.accountIds })

    AppScaffold(
        title = stringResource(R.string.nav_transactions),
        titleContent = {
            CashbookSwitcher(snap, s, stringResource(R.string.nav_transactions), onSelect = { id ->
                vm.updateSettings { it.copy(currentCashbookId = id) }; vm.listFilter.value = filter.copy(accountIds = emptySet())
            }, onManage = { nav.navigate(Routes.CASHBOOKS) })
        },
        actions = {
            IconButton(onClick = { sortMenu = true }) { Icon(Icons.AutoMirrored.Filled.Sort, stringResource(R.string.sort)) }
            DropdownMenu(sortMenu, { sortMenu = false }) {
                SortOrder.entries.forEach { o ->
                    DropdownMenuItem(text = { Text(sortLabel(o) + if (o == sort) "  ✓" else "") }, onClick = { vm.listSort.value = o; sortMenu = false })
                }
            }
            IconButton(onClick = { showFilters = true }) { Icon(Icons.Filled.FilterList, stringResource(R.string.filters)) }
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            OutlinedTextField(
                value = filter.query, onValueChange = { vm.listFilter.value = filter.copy(query = it) },
                leadingIcon = { Icon(Icons.Filled.Search, null) },
                trailingIcon = { if (filter.query.isNotEmpty()) IconButton(onClick = { vm.listFilter.value = filter.copy(query = "") }) { Icon(Icons.Filled.Close, stringResource(R.string.clear)) } },
                placeholder = { Text(stringResource(R.string.search_hint)) }, singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )
            if (filter.isActive) {
                Surface(color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.FilterList, null)
                        Text(stringResource(R.string.filtered_count, results.size, base.size), Modifier.weight(1f).padding(start = 8.dp), style = MaterialTheme.typography.bodySmall)
                        TextButton(onClick = { vm.listFilter.value = TxnFilter() }) { Text(stringResource(R.string.clear_filters)) }
                    }
                }
                ActiveFilterChips(filter, snap) { vm.listFilter.value = it }
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(stringResource(R.string.in_label) + " " + f.amount(totals.income), style = MaterialTheme.typography.labelMedium)
                Text(stringResource(R.string.out_label) + " " + f.amount(totals.expense), style = MaterialTheme.typography.labelMedium)
                Text(stringResource(R.string.sorted_by, sortLabel(sort)), style = MaterialTheme.typography.labelSmall)
            }
            if (singleAccount != null && running.isEmpty()) {
                Text(stringResource(R.string.running_balance_hint), style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp))
            }
            HorizontalDivider()
            if (results.isEmpty()) {
                EmptyState(Icons.AutoMirrored.Filled.ReceiptLong, stringResource(if (base.isEmpty()) R.string.no_transactions_yet else R.string.no_matches))
            } else {
                LazyColumn(Modifier.fillMaxSize()) {
                    items(results, key = { it.id }) { t ->
                        TxnRow(t, snap, onClick = { nav.navigate(Routes.txn(t.id)) }, runningBalance = running[t.id], showCashbook = scope.size > 1)
                        HorizontalDivider(Modifier.padding(start = 70.dp))
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }

    if (showFilters) {
        ModalBottomSheet(onDismissRequest = { showFilters = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            FilterSheet(snap, scope, filter, s.weekStart, onApply = { vm.listFilter.value = it; showFilters = false })
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ActiveFilterChips(filter: TxnFilter, snap: Snapshot, onChange: (TxnFilter) -> Unit) {
    val f = LocalUiFormat.current
    Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        filter.range?.let { r -> InputChip(true, { onChange(filter.copy(range = null)) }, { Text(r.label(f.dateFormat)) }, trailingIcon = { Icon(Icons.Filled.Close, null) }) }
        filter.accountIds.forEach { id -> InputChip(true, { onChange(filter.copy(accountIds = filter.accountIds - id)) }, { Text(snap.names.account(id)) }, trailingIcon = { Icon(Icons.Filled.Close, null) }) }
        filter.types.forEach { t -> InputChip(true, { onChange(filter.copy(types = filter.types - t)) }, { Text(txnTypeLabel(t)) }, trailingIcon = { Icon(Icons.Filled.Close, null) }) }
        filter.categoryIds.forEach { id -> InputChip(true, { onChange(filter.copy(categoryIds = filter.categoryIds - id)) }, { Text(snap.categoryName(id)) }, trailingIcon = { Icon(Icons.Filled.Close, null) }) }
        filter.partyIds.forEach { id -> InputChip(true, { onChange(filter.copy(partyIds = filter.partyIds - id)) }, { Text(snap.names.party(id)) }, trailingIcon = { Icon(Icons.Filled.Close, null) }) }
        filter.paymentModes.forEach { m -> InputChip(true, { onChange(filter.copy(paymentModes = filter.paymentModes - m)) }, { Text(paymentModeLabel(m)) }, trailingIcon = { Icon(Icons.Filled.Close, null) }) }
        if (filter.minAmount != null || filter.maxAmount != null) InputChip(true, { onChange(filter.copy(minAmount = null, maxAmount = null)) },
            { Text("${filter.minAmount?.let { f.amount(it) } ?: "…"} – ${filter.maxAmount?.let { f.amount(it) } ?: "…"}") }, trailingIcon = { Icon(Icons.Filled.Close, null) })
        if (filter.withAttachmentsOnly) InputChip(true, { onChange(filter.copy(withAttachmentsOnly = false)) }, { Text(stringResource(R.string.with_attachments)) }, trailingIcon = { Icon(Icons.Filled.Close, null) })
    }
}

/** Full filter editor; also used by the custom report. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FilterSheet(snap: Snapshot, scope: Set<Long>, initial: TxnFilter, weekStart: java.time.DayOfWeek, showRange: Boolean = true, applyLabel: String? = null, onApply: (TxnFilter) -> Unit) {
    var f by remember { mutableStateOf(initial) }
    var preset by remember { mutableStateOf(if (initial.range == null) PeriodPreset.ALL_TIME else PeriodPreset.CUSTOM) }
    var start by remember { mutableStateOf(initial.range?.start ?: LocalDate.now().withDayOfMonth(1)) }
    var end by remember { mutableStateOf(initial.range?.end ?: LocalDate.now()) }
    var min by remember { mutableStateOf(initial.minAmount?.let { Money.toPlain(it) } ?: "") }
    var max by remember { mutableStateOf(initial.maxAmount?.let { Money.toPlain(it) } ?: "") }
    val today = LocalDate.now()
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(stringResource(R.string.filters), style = MaterialTheme.typography.titleMedium)
        if (showRange) {
            Label(stringResource(R.string.date_range))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(PeriodPreset.ALL_TIME, PeriodPreset.TODAY, PeriodPreset.THIS_WEEK, PeriodPreset.THIS_MONTH, PeriodPreset.LAST_MONTH,
                    PeriodPreset.THIS_FY, PeriodPreset.LAST_FY, PeriodPreset.CUSTOM).forEach { p ->
                    FilterChip(preset == p, onClick = {
                        preset = p
                        if (p != PeriodPreset.CUSTOM && p != PeriodPreset.ALL_TIME) Periods.resolve(p, today, weekStart).let { start = it.start; end = it.end }
                    }, label = { Text(periodLabel(p)) })
                }
            }
            if (preset != PeriodPreset.ALL_TIME) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                DateField(stringResource(R.string.from_date), start, { start = it; preset = PeriodPreset.CUSTOM }, Modifier.weight(1f))
                DateField(stringResource(R.string.to_date), end, { end = it; preset = PeriodPreset.CUSTOM }, Modifier.weight(1f))
            }
        }
        Label(stringResource(R.string.transaction_type))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            TxnType.entries.forEach { t -> FilterChip(t in f.types, { f = f.copy(types = f.types.toggle(t)) }, { Text(txnTypeLabel(t)) }) }
        }
        Label(stringResource(R.string.accounts))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            snap.accountsOf(scope).forEach { a -> FilterChip(a.id in f.accountIds, { f = f.copy(accountIds = f.accountIds.toggle(a.id)) }, { Text(a.name) }) }
        }
        Label(stringResource(R.string.payment_mode))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            PaymentMode.entries.forEach { m -> FilterChip(m in f.paymentModes, { f = f.copy(paymentModes = f.paymentModes.toggle(m)) }, { Text(paymentModeLabel(m)) }) }
        }
        Label(stringResource(R.string.categories))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            snap.categories.filter { !it.archived || it.id in f.categoryIds }.forEach { c ->
                FilterChip(c.id in f.categoryIds, { f = f.copy(categoryIds = f.categoryIds.toggle(c.id)) }, { Text(snap.categoryName(c.id)) })
            }
        }
        if (snap.parties.isNotEmpty()) {
            Label(stringResource(R.string.parties))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                snap.parties.filter { !it.archived || it.id in f.partyIds }.forEach { p ->
                    FilterChip(p.id in f.partyIds, { f = f.copy(partyIds = f.partyIds.toggle(p.id)) }, { Text(p.name) })
                }
            }
        }
        Label(stringResource(R.string.amount_range))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MoneyField(min, { min = it }, stringResource(R.string.min_amount), Modifier.weight(1f))
            MoneyField(max, { max = it }, stringResource(R.string.max_amount), Modifier.weight(1f))
        }
        FilterChip(f.withAttachmentsOnly, { f = f.copy(withAttachmentsOnly = !f.withAttachmentsOnly) }, { Text(stringResource(R.string.with_attachments)) })
        Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { onApply(TxnFilter(query = initial.query)) }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.clear_filters)) }
            Button(onClick = {
                val range = if (!showRange || preset == PeriodPreset.ALL_TIME) null else DateRange(minOf(start, end), maxOf(start, end))
                fun amt(s: String) = (Money.parse(s) as? Money.ParseResult.Ok)?.paise
                onApply(f.copy(range = if (showRange) range else initial.range, minAmount = amt(min), maxAmount = amt(max)))
            }, modifier = Modifier.weight(1f)) { Text(applyLabel ?: stringResource(R.string.apply)) }
        }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable private fun Label(text: String) = Text(text, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)

private fun <T> Set<T>.toggle(v: T) = if (v in this) this - v else this + v
