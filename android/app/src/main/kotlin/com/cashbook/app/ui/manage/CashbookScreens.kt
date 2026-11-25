package com.cashbook.app.ui.manage

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.nav.openTab
import com.cashbook.app.ui.settings.Header
import com.cashbook.core.CashbookInfo
import com.cashbook.core.Ledger
import kotlinx.coroutines.launch
import java.time.LocalDate

@Composable
fun CashbooksScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val scope = rememberCoroutineScope()
    var deleting by remember { mutableStateOf<Pair<CashbookInfo, LedgerRepository.DeleteImpact>?>(null) }
    val active = snap.cashbooks.filter { !it.archived }
    val archived = snap.cashbooks.filter { it.archived }

    AppScaffold(title = stringResource(R.string.cashbooks), onBack = { nav.popBackStack() }, floating = {
        com.cashbook.app.ui.components.AppFab(stringResource(R.string.new_cashbook), onClick = { nav.navigate(Routes.cashbook(0)) })
    }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (snap.cashbooks.isEmpty()) item { EmptyState(Icons.AutoMirrored.Filled.MenuBook, stringResource(R.string.no_cashbook)) }
            items(active, key = { it.id }) { cb -> CashbookCard(vm, nav, cb, s, onDelete = { scope.launch { vm.deps?.ledger?.cashbookDeleteImpact(cb.id)?.let { deleting = cb to it } } }) }
            if (archived.isNotEmpty()) item { Header(stringResource(R.string.archived)) }
            items(archived, key = { it.id }) { cb -> CashbookCard(vm, nav, cb, s, onDelete = { scope.launch { vm.deps?.ledger?.cashbookDeleteImpact(cb.id)?.let { deleting = cb to it } } }) }
            item { Box(Modifier.padding(40.dp)) }
        }
    }

    deleting?.let { (cb, impact) ->
        var typed by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text(stringResource(R.string.delete_cashbook_title, cb.name)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(stringResource(R.string.delete_cashbook_impact, impact.accounts, impact.transactions), color = MaterialTheme.colorScheme.error)
                    Text(stringResource(R.string.delete_cashbook_hint))
                    Text(stringResource(R.string.type_name_to_confirm, cb.name), style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(typed, { typed = it }, singleLine = true, modifier = Modifier.fillMaxWidth())
                }
            },
            confirmButton = {
                TextButton(enabled = typed.trim() == cb.name.trim(), onClick = {
                    val id = cb.id; deleting = null
                    vm.run {
                        ledger.deleteCashbooks(listOf(id))
                        val rest = snap.cashbooks.filter { it.id != id && !it.archived }
                        this.settings.update { st -> st.copy(
                            currentCashbookId = if (st.currentCashbookId == id) rest.firstOrNull()?.id ?: 0 else st.currentCashbookId,
                            defaultCashbookId = if (st.defaultCashbookId == id) rest.firstOrNull()?.id ?: 0 else st.defaultCashbookId) }
                    }
                }) { Text(stringResource(R.string.delete_permanently), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

@Composable
private fun CashbookCard(vm: AppViewModel, nav: NavHostController, cb: CashbookInfo, s: AppSettings, onDelete: () -> Unit) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    var menu by remember { mutableStateOf(false) }
    val accounts = snap.accounts.filter { it.cashbookId == cb.id }
    val txns = snap.txns.filter { it.cashbookId == cb.id }
    val total = accounts.sumOf { Ledger.currentBalance(it, txns) }
    val isCurrent = s.currentCashbookId == cb.id
    Card(Modifier.fillMaxWidth().clickable { vm.updateSettings { it.copy(currentCashbookId = cb.id) }; nav.openTab(Routes.DASHBOARD) },
        colors = CardDefaults.cardColors(containerColor = if (isCurrent) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface)) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(cb.name, style = MaterialTheme.typography.titleMedium)
                    if (s.defaultCashbookId == cb.id) Icon(Icons.Filled.Star, stringResource(R.string.default_label), Modifier.padding(start = 4.dp), tint = MaterialTheme.colorScheme.primary)
                }
                if (cb.description.isNotBlank()) Text(cb.description, style = MaterialTheme.typography.bodySmall)
                Text(stringResource(R.string.cashbook_meta, accounts.size, txns.size, f.date(cb.openingDate), cb.currency), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(stringResource(R.string.created_on, f.dateTime(cb.createdAt)), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (cb.isSample) AssistChip(onClick = {}, label = { Text(stringResource(R.string.sample)) })
                    if (cb.archived) AssistChip(onClick = {}, label = { Text(stringResource(R.string.archived)) })
                }
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(f.amount(total), style = MaterialTheme.typography.titleSmall)
                Box {
                    IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, stringResource(R.string.more_options)) }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem(text = { Text(stringResource(R.string.edit)) }, onClick = { menu = false; nav.navigate(Routes.cashbook(cb.id)) })
                        DropdownMenuItem(text = { Text(stringResource(R.string.accounts)) }, onClick = { menu = false; nav.navigate(Routes.accounts(cb.id)) })
                        if (!cb.archived) DropdownMenuItem(text = { Text(stringResource(R.string.set_default)) }, onClick = { menu = false; vm.updateSettings { it.copy(defaultCashbookId = cb.id) } })
                        DropdownMenuItem(text = { Text(stringResource(R.string.export_transactions)) }, onClick = {
                            menu = false; vm.updateSettings { it.copy(currentCashbookId = cb.id) }; vm.pendingReportAllTime = true; nav.navigate(Routes.report("CUSTOM"))
                        })
                        DropdownMenuItem(text = { Text(stringResource(if (cb.archived) R.string.restore else R.string.archive)) }, onClick = {
                            menu = false; vm.run { ledger.setCashbookArchived(cb.id, !cb.archived) }
                            if (!cb.archived && s.currentCashbookId == cb.id) vm.updateSettings { it.copy(currentCashbookId = it.defaultCashbookId.takeIf { d -> d != cb.id } ?: 0) }
                        })
                        DropdownMenuItem(text = { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }, onClick = { menu = false; onDelete() })
                    }
                }
            }
        }
    }
}

@Composable
fun CashbookEditScreen(vm: AppViewModel, nav: NavHostController, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val existing = snap.cashbookById[id]
    var name by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var currency by rememberSaveable { mutableStateOf("INR") }
    var openingDate by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var loaded by rememberSaveable { mutableStateOf(id == 0L) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    val initialDrafts = defaultDrafts()
    var drafts by rememberSaveable(stateSaver = AccountDraft.ListSaver) { mutableStateOf(initialDrafts) }
    LaunchedEffect(existing) {
        if (!loaded && existing != null) {
            name = existing.name; description = existing.description; currency = existing.currency; openingDate = existing.openingDate.toEpochDay(); loaded = true
        }
    }
    val isNew = id == 0L
    AppScaffold(title = stringResource(if (isNew) R.string.new_cashbook else R.string.edit_cashbook), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.cashbook_name)) }, singleLine = true, isError = showErrors && name.isBlank(),
                supportingText = { Text(stringResource(R.string.cashbook_name_hint)) }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.description_optional)) }, modifier = Modifier.fillMaxWidth())
            DateField(stringResource(R.string.opening_date), LocalDate.ofEpochDay(openingDate), { openingDate = it.toEpochDay() })
            OutlinedTextField(currency, { currency = it.uppercase().filter { c -> c.isLetter() }.take(3) }, label = { Text(stringResource(R.string.currency)) }, singleLine = true,
                supportingText = { Text(stringResource(R.string.currency_hint)) }, modifier = Modifier.fillMaxWidth())
            if (isNew) {
                Text(stringResource(R.string.accounts), style = MaterialTheme.typography.titleMedium)
                AccountDraftEditor(drafts, { drafts = it }, showErrors)
            }
            Button(onClick = {
                showErrors = true
                if (name.isBlank() || currency.length != 3 || (isNew && !validDrafts(drafts))) return@Button
                val date = LocalDate.ofEpochDay(openingDate)
                vm.run {
                    if (isNew) {
                        val newId = ledger.createCashbook(name, description, date, drafts.filter { it.enabled }.map { it.toNew(date) })
                        this.settings.update { st -> st.copy(currentCashbookId = newId, defaultCashbookId = if (st.defaultCashbookId == 0L) newId else st.defaultCashbookId) }
                    } else ledger.updateCashbook(id, name, description, date, currency)
                }
                nav.popBackStack()
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
        }
    }
}
