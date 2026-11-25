package com.cashbook.app.ui.recurring

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.EventRepeat
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.Snapshot
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AmountText
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.ConfirmDialog
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.PickItem
import com.cashbook.app.ui.components.PickerField
import com.cashbook.app.ui.components.SearchPickerSheet
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.components.TypeAvatar
import com.cashbook.app.ui.components.accountIcon
import com.cashbook.app.ui.components.accountTypeLabel
import com.cashbook.app.ui.components.categoryIcon
import com.cashbook.app.ui.components.paymentModeLabel
import com.cashbook.app.ui.components.txnTypeLabel
import com.cashbook.app.ui.components.typeIcon
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.transactions.amountError
import com.cashbook.app.ui.transactions.TxnFormViewModel
import com.cashbook.core.CategoryKind
import com.cashbook.core.Frequency
import com.cashbook.core.Money
import com.cashbook.core.PaymentMode
import com.cashbook.core.RecurringRule
import com.cashbook.core.TxnType
import java.time.LocalDate

@Composable
fun frequencyLabel(f: Frequency, interval: Int = 1): String = when {
    interval <= 1 -> stringResource(when (f) {
        Frequency.DAILY -> R.string.freq_daily; Frequency.WEEKLY -> R.string.freq_weekly; Frequency.MONTHLY -> R.string.freq_monthly
        Frequency.QUARTERLY -> R.string.freq_quarterly; Frequency.YEARLY -> R.string.freq_yearly })
    else -> stringResource(when (f) {
        Frequency.DAILY -> R.string.freq_every_n_days; Frequency.WEEKLY -> R.string.freq_every_n_weeks; Frequency.MONTHLY -> R.string.freq_every_n_months
        Frequency.QUARTERLY -> R.string.freq_every_n_quarters; Frequency.YEARLY -> R.string.freq_every_n_years }, interval)
}

fun ruleTitle(r: RecurringRule, snap: Snapshot, transferLabel: String) = r.description.ifBlank {
    if (r.type == TxnType.TRANSFER) "$transferLabel: ${snap.names.account(r.accountId)} → ${snap.names.account(r.toAccountId)}" else snap.categoryName(r.categoryId)
}

@Composable
fun RecurringListScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val scope = currentScope(snap, s)
    val rules = snap.recurring.filter { it.cashbookId in scope }.sortedWith(compareBy({ !it.active || it.finished }, { it.nextDate }))
    val transfer = stringResource(R.string.type_transfer)
    AppScaffold(title = stringResource(R.string.recurring_entries), onBack = { nav.popBackStack() }, floating = {
        com.cashbook.app.ui.components.AppFab(stringResource(R.string.new_recurring), onClick = { nav.navigate(Routes.recurringEdit(0)) })
    }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item { InfoBanner(stringResource(R.string.recurring_intro), Modifier.padding(16.dp), icon = Icons.Filled.Info) }
            if (rules.isEmpty()) item { EmptyState(Icons.Filled.EventRepeat, stringResource(R.string.no_recurring)) }
            items(rules, key = { it.id }) { r ->
                val inactive = !r.active || r.finished
                Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.recurringEdit(r.id)) }.padding(horizontal = 16.dp, vertical = 12.dp).alpha(if (inactive) 0.55f else 1f),
                    verticalAlignment = Alignment.CenterVertically) {
                    TypeAvatar(r.type, snap.categoryById[r.categoryId]?.let { categoryIcon(it.icon) })
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(ruleTitle(r, snap, transfer), style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                        Text(frequencyLabel(r.frequency, r.interval) + " · " + snap.names.account(r.accountId), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(when {
                            r.finished -> stringResource(R.string.recurring_finished)
                            !r.active -> stringResource(R.string.paused)
                            else -> stringResource(if (r.autoPost) R.string.next_auto else R.string.next_confirm, f.date(r.nextDate!!))
                        }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                    }
                    AmountText(r.amount, r.type)
                }
                HorizontalDivider(Modifier.padding(start = 70.dp))
            }
            item { Box(Modifier.padding(40.dp)) }
        }
    }
}

/** Create / edit a recurring rule. [fromTxn] pre-fills the form from an existing entry ("Make recurring"). */
@Composable
fun RecurringEditScreen(vm: AppViewModel, nav: NavHostController, id: Long, fromTxn: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    var type by rememberSaveable { mutableStateOf(TxnType.EXPENSE) }
    var cashbookId by rememberSaveable { mutableStateOf(0L) }
    var amount by rememberSaveable { mutableStateOf("") }
    var categoryId by rememberSaveable { mutableStateOf(0L) }
    var accountId by rememberSaveable { mutableStateOf(0L) }
    var toAccountId by rememberSaveable { mutableStateOf(0L) }
    var partyId by rememberSaveable { mutableStateOf(0L) }
    var mode by rememberSaveable { mutableStateOf(PaymentMode.CASH) }
    var description by rememberSaveable { mutableStateOf("") }
    var reference by rememberSaveable { mutableStateOf("") }
    var frequency by rememberSaveable { mutableStateOf(Frequency.MONTHLY) }
    var interval by rememberSaveable { mutableStateOf("1") }
    var start by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var hasEnd by rememberSaveable { mutableStateOf(false) }
    var end by rememberSaveable { mutableStateOf(LocalDate.now().plusYears(1).toEpochDay()) }
    var autoPost by rememberSaveable { mutableStateOf(true) }
    var active by rememberSaveable { mutableStateOf(true) }
    var loaded by rememberSaveable { mutableStateOf(false) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    var picker by rememberSaveable { mutableStateOf<String?>(null) }
    var confirmDelete by remember { mutableStateOf(false) }

    LaunchedEffect(snap.loaded) {
        if (loaded || !snap.loaded) return@LaunchedEffect
        val rule = snap.recurring.firstOrNull { it.id == id }
        val txn = snap.txns.firstOrNull { it.id == fromTxn }
        when {
            rule != null -> {
                type = rule.type; cashbookId = rule.cashbookId; amount = Money.toPlain(rule.amount); categoryId = rule.categoryId ?: 0
                accountId = rule.accountId; toAccountId = rule.toAccountId ?: 0; partyId = rule.partyId ?: 0; mode = rule.paymentMode
                description = rule.description; reference = rule.reference; frequency = rule.frequency; interval = rule.interval.toString()
                start = rule.startDate.toEpochDay(); hasEnd = rule.endDate != null; rule.endDate?.let { end = it.toEpochDay() }
                autoPost = rule.autoPost; active = rule.active
            }
            txn != null -> {
                type = txn.type; cashbookId = txn.cashbookId; amount = Money.toPlain(txn.amount); categoryId = txn.categoryId ?: 0
                accountId = txn.accountId; toAccountId = txn.toAccountId ?: 0; partyId = txn.partyId ?: 0; mode = txn.paymentMode
                description = txn.description; start = startAfterEntry(txn.date).toEpochDay()
            }
            else -> {
                val scope = currentScope(snap, s)
                cashbookId = if (s.defaultCashbookId in scope) s.defaultCashbookId else scope.firstOrNull() ?: 0
                accountId = snap.accounts.firstOrNull { it.cashbookId == cashbookId && !it.archived }?.id ?: 0
            }
        }
        loaded = true
    }

    val parsed = Money.parse(amount)
    val intervalN = interval.toIntOrNull()?.takeIf { it in 1..365 }
    val accounts = snap.accounts.filter { it.cashbookId == cashbookId && (!it.archived || it.id == accountId || it.id == toAccountId) }
    val errAmount = (parsed as? Money.ParseResult.Error)?.let { it.reason }
    val errCategory = type != TxnType.TRANSFER && snap.categoryById[categoryId] == null
    val errAccount = accounts.none { it.id == accountId }
    val errTo = type == TxnType.TRANSFER && (accounts.none { it.id == toAccountId } || toAccountId == accountId)
    val errEnd = hasEnd && end < start
    val valid = errAmount == null && !errCategory && !errAccount && !errTo && intervalN != null && !errEnd && cashbookId != 0L

    AppScaffold(title = stringResource(if (id == 0L) R.string.new_recurring else R.string.edit_recurring), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                TxnType.entries.forEachIndexed { i, t ->
                    SegmentedButton(selected = type == t, onClick = { type = t; categoryId = 0 }, shape = SegmentedButtonDefaults.itemShape(i, 3),
                        icon = { Icon(typeIcon(t), null) }) { Text(txnTypeLabel(t), maxLines = 1) }
                }
            }
            val cbs = snap.cashbooks.filter { !it.archived || it.id == cashbookId }
            if (cbs.size > 1) DropdownField(stringResource(R.string.cashbook), cbs.map { it.id }, cashbookId.takeIf { it != 0L }, labelOf = { snap.cashbookById[it]?.name ?: "" },
                onSelect = { cashbookId = it; accountId = snap.accounts.firstOrNull { a -> a.cashbookId == it && !a.archived }?.id ?: 0; toAccountId = 0 })
            MoneyField(amount, { amount = it }, stringResource(R.string.amount_required),
                error = if (showErrors && errAmount != null) amountError(when (errAmount) {
                    Money.AmountError.EMPTY -> TxnFormViewModel.Err.AMOUNT_EMPTY; Money.AmountError.ZERO_OR_NEGATIVE -> TxnFormViewModel.Err.AMOUNT_ZERO
                    Money.AmountError.TOO_MANY_DECIMALS -> TxnFormViewModel.Err.AMOUNT_DECIMALS; Money.AmountError.TOO_LARGE -> TxnFormViewModel.Err.AMOUNT_LARGE
                    else -> TxnFormViewModel.Err.AMOUNT_INVALID }) else null)
            if (type == TxnType.TRANSFER) {
                PickerField(stringResource(R.string.from_account), snap.names.account(accountId.takeIf { it > 0 }), { picker = "account" }, isError = showErrors && errAccount,
                    leading = snap.accountById[accountId]?.let { accountIcon(it.type) })
                PickerField(stringResource(R.string.to_account), snap.names.account(toAccountId.takeIf { it > 0 }), { picker = "to" }, isError = showErrors && errTo,
                    supporting = if (showErrors && errTo) stringResource(R.string.err_same_account) else null, leading = snap.accountById[toAccountId]?.let { accountIcon(it.type) })
            } else {
                PickerField(stringResource(if (type == TxnType.INCOME) R.string.income_category else R.string.expense_category), snap.categoryName(categoryId.takeIf { it > 0 }),
                    { picker = "category" }, isError = showErrors && errCategory, supporting = if (showErrors && errCategory) stringResource(R.string.err_category) else null,
                    leading = snap.categoryById[categoryId]?.let { categoryIcon(it.icon) })
                PickerField(stringResource(if (type == TxnType.INCOME) R.string.receiving_account else R.string.paying_account), snap.names.account(accountId.takeIf { it > 0 }),
                    { picker = "account" }, isError = showErrors && errAccount, leading = snap.accountById[accountId]?.let { accountIcon(it.type) })
                PickerField(stringResource(if (type == TxnType.INCOME) R.string.received_from else R.string.paid_to),
                    snap.names.party(partyId.takeIf { it > 0 }).ifEmpty { stringResource(R.string.optional) }, { picker = "party" })
            }
            DropdownField(stringResource(R.string.payment_mode), PaymentMode.entries, mode, labelOf = { paymentModeLabel(it) }, onSelect = { mode = it })
            OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.description)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(reference, { reference = it }, label = { Text(stringResource(R.string.reference_number)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            HorizontalDivider()
            Text(stringResource(R.string.schedule), style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(interval, { interval = it.filter(Char::isDigit).take(3) }, label = { Text(stringResource(R.string.every)) }, singleLine = true,
                    isError = intervalN == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(0.6f))
                DropdownField(stringResource(R.string.repeats), Frequency.entries, frequency, labelOf = { frequencyLabel(it) }, onSelect = { frequency = it }, modifier = Modifier.weight(1.4f))
            }
            DateField(stringResource(R.string.first_date), LocalDate.ofEpochDay(start), { start = it.toEpochDay() },
                supporting = if (LocalDate.ofEpochDay(start).isBefore(LocalDate.now()) && id == 0L) stringResource(R.string.past_start_hint) else null)
            SwitchRow(stringResource(R.string.has_end_date), hasEnd, { hasEnd = it })
            if (hasEnd) DateField(stringResource(R.string.end_date), LocalDate.ofEpochDay(end), { end = it.toEpochDay() }, isError = errEnd)
            SwitchRow(stringResource(R.string.post_automatically), autoPost, { autoPost = it }, stringResource(if (autoPost) R.string.post_automatically_on else R.string.post_automatically_off))
            if (id != 0L) SwitchRow(stringResource(R.string.active), active, { active = it }, stringResource(R.string.active_desc))
            Button(onClick = {
                showErrors = true
                if (!valid) return@Button
                val rule = RecurringRule(id, cashbookId, type, (parsed as Money.ParseResult.Ok).paise, accountId, toAccountId.takeIf { it > 0 },
                    categoryId.takeIf { it > 0 }, partyId.takeIf { it > 0 }, mode, description, reference, "", "", frequency, intervalN!!,
                    LocalDate.ofEpochDay(start), if (hasEnd) LocalDate.ofEpochDay(end) else null, 0, autoPost, active)
                vm.run { saveRecurringAndPost(this, rule) }
                nav.popBackStack()
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
            if (id != 0L) OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
        }
    }

    when (picker) {
        "category" -> {
            val kind = if (type == TxnType.INCOME) CategoryKind.INCOME else CategoryKind.EXPENSE
            SearchPickerSheet(stringResource(R.string.select_category),
                snap.categoriesOf(kind).filter { !it.archived }.map { PickItem(it.id, snap.categoryName(it.id), icon = categoryIcon(it.icon), indent = it.parentId != null) },
                onPick = { categoryId = it?.id ?: 0; picker = null }, onDismiss = { picker = null })
        }
        "account", "to" -> SearchPickerSheet(stringResource(R.string.select_account),
            snap.accounts.filter { it.cashbookId == cashbookId && !it.archived }.map { PickItem(it.id, it.name, accountTypeLabel(it.type), accountIcon(it.type)) },
            onPick = { p -> if (picker == "to") toAccountId = p?.id ?: 0 else accountId = p?.id ?: 0; picker = null }, onDismiss = { picker = null })
        "party" -> SearchPickerSheet(stringResource(R.string.select_party), snap.parties.filter { !it.archived }.map { PickItem(it.id, it.name, it.mobile) },
            onPick = { partyId = it?.id ?: 0; picker = null }, onDismiss = { picker = null }, allowNone = stringResource(R.string.no_party))
    }
    if (confirmDelete) ConfirmDialog(stringResource(R.string.delete_recurring), stringResource(R.string.delete_recurring_text), stringResource(R.string.delete),
        onConfirm = { vm.run { ledger.deleteRecurring(id) }; nav.popBackStack() }, onDismiss = { confirmDelete = false }, destructive = true)
}

/** "Make recurring" from an entry: the schedule starts one month after that entry. */
private fun startAfterEntry(d: LocalDate): LocalDate = d.plusMonths(1)

private suspend fun saveRecurringAndPost(d: com.cashbook.app.Dependencies, rule: RecurringRule) {
    d.ledger.saveRecurring(rule)
    d.ledger.postDueRecurring()
}

