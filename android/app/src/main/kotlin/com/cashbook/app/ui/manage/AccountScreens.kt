package com.cashbook.app.ui.manage

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.accountIcon
import com.cashbook.app.ui.components.accountTypeLabel
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.nav.openTab
import com.cashbook.app.ui.settings.Header
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.AccountInfo
import com.cashbook.core.AccountType
import com.cashbook.core.Ledger
import com.cashbook.core.Money
import com.cashbook.core.TxnFilter
import java.time.LocalDate

@Composable
fun AccountsScreen(vm: AppViewModel, nav: NavHostController, cashbookId: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val cb = snap.cashbookById[cashbookId]
    val accounts = snap.accounts.filter { it.cashbookId == cashbookId }
    AppScaffold(title = stringResource(R.string.accounts) + (cb?.let { " · ${it.name}" } ?: ""), onBack = { nav.popBackStack() }, floating = {
        com.cashbook.app.ui.components.AppFab(stringResource(R.string.new_account), onClick = { nav.navigate(Routes.account(cashbookId, 0)) })
    }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item { InfoBanner(stringResource(R.string.account_vs_mode_info), Modifier.padding(16.dp), icon = Icons.Filled.Info) }
            items(accounts.filter { !it.archived }, key = { it.id }) { AccountRow(vm, nav, it) }
            if (accounts.any { it.archived }) item { Header(stringResource(R.string.archived)) }
            items(accounts.filter { it.archived }, key = { it.id }) { AccountRow(vm, nav, it) }
            item { Box(Modifier.padding(40.dp)) }
        }
    }
}

@Composable
private fun AccountRow(vm: AppViewModel, nav: NavHostController, a: AccountInfo) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val ctx = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    val today = LocalDate.now()
    val bal = Ledger.balanceAsOf(a, snap.txns, today)
    Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.account(a.cashbookId, a.id)) }.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(accountIcon(a.type), null, tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(a.name, style = MaterialTheme.typography.bodyLarge)
            Text(listOfNotNull(accountTypeLabel(a.type), a.bankName.takeIf { it.isNotBlank() }, a.last4.takeIf { it.isNotBlank() }?.let { "••$it" }).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(stringResource(R.string.opening_x_on_y, f.amount(a.openingBalance), f.date(a.openingDate)), style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(f.amount(bal), style = MaterialTheme.typography.titleSmall, color = if (bal < 0) fc.expense else MaterialTheme.colorScheme.onSurface)
            Text(stringResource(R.string.as_of, f.date(today)), style = MaterialTheme.typography.labelSmall)
        }
        Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, stringResource(R.string.more_options)) }
            DropdownMenu(menu, { menu = false }) {
                DropdownMenuItem(text = { Text(stringResource(R.string.view_transactions)) }, onClick = {
                    menu = false
                    vm.updateSettings { it.copy(currentCashbookId = a.cashbookId) }
                    vm.listFilter.value = TxnFilter(accountIds = setOf(a.id))
                    vm.listSort.value = com.cashbook.core.SortOrder.OLDEST
                    nav.openTab(Routes.TRANSACTIONS)
                })
                DropdownMenuItem(text = { Text(stringResource(if (a.archived) R.string.restore else R.string.archive)) }, onClick = {
                    menu = false; vm.run { ledger.setAccountArchived(a.id, !a.archived) }
                })
                DropdownMenuItem(text = { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }, onClick = {
                    menu = false
                    vm.run { if (!ledger.deleteAccount(a.id)) vm.toast(ctx.getString(R.string.account_in_use)) }
                })
            }
        }
    }
    HorizontalDivider(Modifier.padding(start = 52.dp))
}

@Composable
fun AccountEditScreen(vm: AppViewModel, nav: NavHostController, cashbookId: Long, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val existing = snap.accountById[id]
    var name by rememberSaveable { mutableStateOf("") }
    var type by rememberSaveable { mutableStateOf(AccountType.CASH) }
    var opening by rememberSaveable { mutableStateOf("") }
    var openingDate by rememberSaveable { mutableStateOf((snap.cashbookById[cashbookId]?.openingDate ?: LocalDate.now()).toEpochDay()) }
    var bankName by rememberSaveable { mutableStateOf("") }
    var last4 by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var loaded by rememberSaveable { mutableStateOf(id == 0L) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(existing) {
        if (!loaded && existing != null) {
            name = existing.name; type = existing.type; opening = Money.toPlain(existing.openingBalance); openingDate = existing.openingDate.toEpochDay()
            bankName = existing.bankName; last4 = existing.last4; description = existing.description; loaded = true
        }
    }
    val openingParsed = Money.parseOpening(opening)
    val earliestTxn = snap.txns.filter { it.accountId == id || it.toAccountId == id }.minOfOrNull { it.date }
    val dateError = earliestTxn != null && LocalDate.ofEpochDay(openingDate).isAfter(earliestTxn)
    AppScaffold(title = stringResource(if (id == 0L) R.string.new_account else R.string.edit_account), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.account_name)) }, singleLine = true, isError = showErrors && name.isBlank(), modifier = Modifier.fillMaxWidth())
            DropdownField(stringResource(R.string.account_type), AccountType.entries, type, labelOf = { accountTypeLabel(it) }, onSelect = { type = it })
            MoneyField(opening, { opening = it }, stringResource(R.string.opening_balance), error = if (openingParsed is Money.ParseResult.Error) stringResource(R.string.err_amount_invalid) else null)
            val f = LocalUiFormat.current
            DateField(stringResource(R.string.opening_date), LocalDate.ofEpochDay(openingDate), { openingDate = it.toEpochDay() }, isError = dateError,
                supporting = if (dateError) stringResource(R.string.err_opening_after_txn, f.date(earliestTxn!!)) else null)
            if (type == AccountType.BANK || type == AccountType.WALLET) {
                OutlinedTextField(bankName, { bankName = it }, label = { Text(stringResource(if (type == AccountType.BANK) R.string.bank_name_optional else R.string.provider_optional)) },
                    singleLine = true, modifier = Modifier.fillMaxWidth())
                if (type == AccountType.BANK) OutlinedTextField(last4, { v -> last4 = v.filter { it.isDigit() }.take(4) }, label = { Text(stringResource(R.string.last4_optional)) },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
            }
            OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.description_optional)) }, modifier = Modifier.fillMaxWidth())
            InfoBanner(stringResource(R.string.no_credentials_note), icon = Icons.Filled.Info)
            Button(onClick = {
                showErrors = true
                val ok = openingParsed as? Money.ParseResult.Ok ?: return@Button
                if (name.isBlank() || dateError) return@Button
                val acc = LedgerRepository.NewAccount(name, type, ok.paise, LocalDate.ofEpochDay(openingDate), bankName, last4)
                vm.run { if (id == 0L) ledger.addAccount(cashbookId, acc, description) else ledger.updateAccount(id, acc, description) }
                nav.popBackStack()
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
        }
    }
}
