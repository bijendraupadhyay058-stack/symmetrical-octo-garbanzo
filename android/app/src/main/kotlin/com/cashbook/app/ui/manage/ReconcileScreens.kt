package com.cashbook.app.ui.manage

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.AccountType
import com.cashbook.core.CashCount
import com.cashbook.core.Ledger
import com.cashbook.core.Money
import com.cashbook.core.Reconcile
import java.time.LocalDate

/** "55,500", "-1,200.50" or "0" → paise; null when it isn't an amount. A statement balance can be zero or overdrawn. */
fun parseSignedAmount(text: String): Long? {
    val t = text.trim().replace(" ", "")
    if (t.isEmpty()) return null
    val neg = t.startsWith("-")
    val abs = t.removePrefix("-")
    if (Regex("^0+([.,]0{1,2})?$").matches(abs)) return 0
    return (Money.parse(abs) as? Money.ParseResult.Ok)?.paise?.let { if (neg) -it else it }
}

/**
 * Bank reconciliation: pick the account, enter the statement date and closing balance, tick the entries that are on
 * the statement. When the difference is zero, Finish marks them cleared.
 */
@Composable
fun ReconcileScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val accounts = snap.accountsOf(currentScope(snap, s)).filter { !it.archived }.let { all -> all.filter { it.type != AccountType.CASH }.ifEmpty { all } }
    var accountId by rememberSaveable { mutableStateOf(accounts.firstOrNull()?.id ?: 0L) }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var balanceText by rememberSaveable { mutableStateOf("") }
    var ticked by rememberSaveable { mutableStateOf(listOf<Long>()) }
    val account = accounts.firstOrNull { it.id == accountId }
    val msgDone = stringResource(R.string.reconcile_done)
    AppScaffold(title = stringResource(R.string.bank_reconciliation), onBack = { nav.popBackStack() }) { pad ->
        if (account == null) { EmptyState(Icons.Filled.Info, stringResource(R.string.no_accounts_to_reconcile), Modifier.padding(pad)); return@AppScaffold }
        val statementDate = LocalDate.ofEpochDay(date)
        val open = Reconcile.uncleared(account, snap.txns, statementDate)
        val tickedTxns = open.filter { it.id in ticked }
        val statement = parseSignedAmount(balanceText)
        val cleared = Reconcile.clearedBalance(account, snap.txns) + tickedTxns.sumOf { Ledger.effect(it, account.id) }
        val diff = statement?.let { Reconcile.difference(it, account, snap.txns, tickedTxns) }
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    InfoBanner(stringResource(R.string.reconcile_intro), icon = Icons.Filled.Info)
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        accounts.forEach { a -> FilterChip(a.id == accountId, { accountId = a.id; ticked = emptyList() }, { Text(a.name) }) }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        DateField(stringResource(R.string.statement_date), statementDate, { date = it.toEpochDay(); ticked = emptyList() }, Modifier.weight(1f))
                        OutlinedTextField(balanceText, { v -> balanceText = v.filter { it.isDigit() || it in ".,-" }.take(16) },
                            label = { Text(stringResource(R.string.statement_balance)) }, prefix = { Text("₹ ") }, singleLine = true,
                            isError = balanceText.isNotBlank() && statement == null, modifier = Modifier.weight(1f),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text))
                    }
                    SectionCard {
                        SummaryLine(stringResource(R.string.cleared_balance), f.amount(cleared))
                        SummaryLine(stringResource(R.string.statement_balance), statement?.let { f.amount(it) } ?: "—")
                        val done = diff == 0L
                        SummaryLine(stringResource(R.string.difference), diff?.let { if (done) stringResource(R.string.reconciled_ok) else f.amount(it) } ?: "—",
                            if (done) fc.income else if (diff != null) fc.expense else null)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(R.string.uncleared_x, open.size), Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
                        TextButton(onClick = { ticked = open.map { it.id } }) { Text(stringResource(R.string.tick_all)) }
                        TextButton(onClick = { ticked = emptyList() }) { Text(stringResource(R.string.clear_ticks)) }
                    }
                }
            }
            if (open.isEmpty()) item { EmptyState(Icons.Filled.CheckCircle, stringResource(R.string.all_cleared)) }
            items(open, key = { it.id }) { t ->
                val e = Ledger.effect(t, account.id)
                Row(Modifier.fillMaxWidth().clickable { ticked = if (t.id in ticked) ticked - t.id else ticked + t.id }.padding(horizontal = 8.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(t.id in ticked, { ticked = if (it) ticked + t.id else ticked - t.id })
                    Column(Modifier.weight(1f)) {
                        Text(t.description.ifBlank { snap.categoryName(t.categoryId).ifBlank { snap.names.party(t.partyId) } }.ifBlank { "—" },
                            style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(f.date(t.date) + (if (t.reference.isNotBlank()) " · ${t.reference}" else ""), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text((if (e >= 0) "+" else "−") + f.amount(kotlin.math.abs(e)), color = if (e >= 0) fc.income else fc.expense,
                        style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(end = 8.dp))
                }
                HorizontalDivider()
            }
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(enabled = diff == 0L && tickedTxns.isNotEmpty(), onClick = {
                        vm.run(onError = { e ->
                            vm.toast((e as? LedgerRepository.ReconcileException)?.takeIf { it.reason == LedgerRepository.ReconcileException.Reason.DIFFERENCE }
                                ?.let { f.amount(it.difference) } ?: e.localizedMessage ?: "")
                        }) {
                            ledger.reconcile(account.id, statementDate, statement!!, tickedTxns.map { it.id })
                            kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { ticked = emptyList(); vm.toast(msgDone) }
                        }
                    }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.finish_reconcile, tickedTxns.size)) }
                    val history = snap.reconciliations.filter { it.accountId == account.id }.take(6)
                    if (history.isNotEmpty()) SectionCard(stringResource(R.string.reconcile_history)) {
                        history.forEach { r ->
                            SummaryLine("${f.date(r.statementDate)} · ${stringResource(R.string.entries_x, r.entries)}", f.amount(r.statementBalance))
                        }
                    }
                    Box(Modifier.padding(16.dp))
                }
            }
        }
    }
}

@Composable
private fun SummaryLine(label: String, value: String, color: Color? = null) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
        Text(value, style = MaterialTheme.typography.titleSmall, color = color ?: MaterialTheme.colorScheme.onSurface)
    }
}

/**
 * Cash count: notes and coins by denomination for a cash account, compared with its book balance on the date.
 * The difference can be recorded as a "Cash excess" income or "Cash shortage" expense so the books match the drawer.
 */
@Composable
fun CashCountScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val accounts = snap.accountsOf(currentScope(snap, s)).filter { !it.archived }.let { all -> all.filter { it.type == AccountType.CASH }.ifEmpty { all } }
    var accountId by rememberSaveable { mutableStateOf(accounts.firstOrNull()?.id ?: 0L) }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var countText by rememberSaveable { mutableStateOf(CashCount.DENOMINATIONS.map { "" }) }
    var record by rememberSaveable { mutableStateOf(true) }
    var note by rememberSaveable { mutableStateOf("") }
    val account = accounts.firstOrNull { it.id == accountId }
    val excess = stringResource(R.string.cat_cash_excess); val shortage = stringResource(R.string.cat_cash_shortage)
    val adjDesc = stringResource(R.string.cash_count_entry); val msgSaved = stringResource(R.string.cash_count_saved)
    AppScaffold(title = stringResource(R.string.cash_count), onBack = { nav.popBackStack() }) { pad ->
        if (account == null) { EmptyState(Icons.Filled.Info, stringResource(R.string.no_accounts_to_reconcile), Modifier.padding(pad)); return@AppScaffold }
        val day = LocalDate.ofEpochDay(date)
        val counts = CashCount.DENOMINATIONS.zip(countText).mapNotNull { (d, t) -> t.toIntOrNull()?.takeIf { it > 0 }?.let { d to it } }.toMap()
        val counted = CashCount.total(counts)
        val book = Ledger.balanceAsOf(account, snap.txns, day)
        val diff = counted - book
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        accounts.forEach { a -> FilterChip(a.id == accountId, { accountId = a.id }, { Text(a.name) }) }
                    }
                    DateField(stringResource(R.string.date), day, { date = it.toEpochDay() })
                }
            }
            items(CashCount.DENOMINATIONS.indices.toList(), key = { CashCount.DENOMINATIONS[it] }) { i ->
                val d = CashCount.DENOMINATIONS[i]
                val n = countText[i].toIntOrNull() ?: 0
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("₹$d ×", Modifier.width(72.dp), style = MaterialTheme.typography.titleSmall)
                    OutlinedTextField(countText[i], { v -> countText = countText.toMutableList().also { it[i] = v.filter { c -> c.isDigit() }.take(5) } },
                        label = { Text(stringResource(R.string.count_of_x, d)) }, singleLine = true, modifier = Modifier.weight(1f),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                    Text(f.amount(d * 100L * n), Modifier.width(120.dp).padding(start = 8.dp), style = MaterialTheme.typography.bodyMedium,
                        textAlign = androidx.compose.ui.text.style.TextAlign.End)
                }
            }
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SectionCard {
                        SummaryLine(stringResource(R.string.cash_counted), f.amount(counted))
                        SummaryLine(stringResource(R.string.book_balance), f.amount(book))
                        SummaryLine(stringResource(when { diff > 0 -> R.string.cash_excess; diff < 0 -> R.string.cash_shortage; else -> R.string.difference }),
                            if (diff == 0L) stringResource(R.string.cash_matches) else f.amount(kotlin.math.abs(diff)),
                            if (diff == 0L) fc.income else fc.expense)
                    }
                    if (diff != 0L) SwitchRow(stringResource(R.string.record_difference), record, { record = it },
                        stringResource(if (diff > 0) R.string.record_excess_desc else R.string.record_shortage_desc))
                    OutlinedTextField(note, { note = it.take(200) }, label = { Text(stringResource(R.string.notes)) }, modifier = Modifier.fillMaxWidth(), maxLines = 3)
                    Button(enabled = counts.isNotEmpty(), onClick = {
                        vm.run {
                            ledger.saveCashCount(account.id, day, counts, note, record, excess, shortage, adjDesc)
                            kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) {
                                countText = CashCount.DENOMINATIONS.map { "" }; note = ""; vm.toast(msgSaved)
                            }
                        }
                    }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save_cash_count)) }
                    val history = snap.cashCounts.filter { it.accountId == account.id }.take(8)
                    if (history.isNotEmpty()) SectionCard(stringResource(R.string.cash_count_history)) {
                        history.forEach { c ->
                            val label = when { c.difference > 0 -> stringResource(R.string.cash_excess_x, f.amount(c.difference))
                                c.difference < 0 -> stringResource(R.string.cash_shortage_x, f.amount(-c.difference)); else -> stringResource(R.string.cash_matches) }
                            SummaryLine("${f.date(c.date)} · $label", f.amount(c.counted), if (c.difference == 0L) null else fc.expense)
                        }
                    }
                    Box(Modifier.padding(16.dp))
                }
            }
        }
    }
}
