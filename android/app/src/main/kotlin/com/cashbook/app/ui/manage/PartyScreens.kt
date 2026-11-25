package com.cashbook.app.ui.manage

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.components.TxnRow
import com.cashbook.app.ui.components.partyTypeLabel
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.PartyType
import com.cashbook.core.TxnChronological
import com.cashbook.core.TxnFilter
import com.cashbook.core.TxnType

@Composable
fun PartiesScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    var query by rememberSaveable { mutableStateOf("") }
    val list = snap.parties.filter { query.isBlank() || it.name.contains(query, true) || it.mobile.replace(" ", "").contains(query.replace(" ", "")) }
    val counts = snap.txns.groupingBy { it.partyId }.eachCount()
    AppScaffold(title = stringResource(R.string.parties), onBack = { nav.popBackStack() }, floating = {
        com.cashbook.app.ui.components.AppFab(stringResource(R.string.new_party), onClick = { nav.navigate(Routes.party(0)) })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            OutlinedTextField(query, { query = it }, leadingIcon = { Icon(Icons.Filled.Search, null) }, placeholder = { Text(stringResource(R.string.search_party)) },
                singleLine = true, modifier = Modifier.fillMaxWidth().padding(16.dp))
            if (list.isEmpty()) EmptyState(Icons.Filled.Person, stringResource(R.string.no_parties))
            LazyColumn {
                items(list, key = { it.id }) { p ->
                    ListItem(
                        headlineContent = { Text(p.name) },
                        supportingContent = { Text(listOfNotNull(partyTypeLabel(p.type), p.mobile.takeIf { it.isNotBlank() }, stringResource(R.string.n_entries, counts[p.id] ?: 0)).joinToString(" · ")) },
                        leadingContent = { Icon(Icons.Filled.Person, null, tint = MaterialTheme.colorScheme.primary) },
                        modifier = Modifier.clickable { nav.navigate(Routes.partyDetail(p.id)) }.alpha(if (p.archived) 0.55f else 1f),
                    )
                    HorizontalDivider()
                }
                item { Box(Modifier.padding(40.dp)) }
            }
        }
    }
}

@Composable
fun PartyDetailScreen(vm: AppViewModel, nav: NavHostController, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val p = snap.partyById[id]
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val txns = snap.txns.filter { it.partyId == id }.sortedWith(TxnChronological.reversed())
    AppScaffold(title = p?.name ?: "", onBack = { nav.popBackStack() }, actions = {
        IconButton(onClick = { nav.navigate(Routes.party(id)) }) { Icon(Icons.Filled.Edit, stringResource(R.string.edit)) }
    }) { pad ->
        if (p == null) return@AppScaffold
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SectionCard {
                        Text(partyTypeLabel(p.type), style = MaterialTheme.typography.labelLarge)
                        listOf(p.mobile, p.email, p.address, p.gstin.takeIf { it.isNotBlank() }?.let { "GSTIN: $it" } ?: "", p.notes).filter { it.isNotBlank() }
                            .forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
                    }
                    SectionCard {
                        Row(Modifier.fillMaxWidth()) {
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.total_received), style = MaterialTheme.typography.labelMedium)
                                Text(f.amount(txns.filter { it.type == TxnType.INCOME }.sumOf { it.amount }), color = fc.income, style = MaterialTheme.typography.titleMedium)
                            }
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.total_paid), style = MaterialTheme.typography.labelMedium)
                                Text(f.amount(txns.filter { it.type == TxnType.EXPENSE }.sumOf { it.amount }), color = fc.expense, style = MaterialTheme.typography.titleMedium)
                            }
                        }
                        Text(stringResource(R.string.n_entries, txns.size), style = MaterialTheme.typography.bodySmall)
                    }
                    val balances = snap.invoiceBalances().filter { it.invoice.partyId == id && it.outstanding > 0 }
                    SectionCard(stringResource(R.string.receivables_payables)) {
                        Row(Modifier.fillMaxWidth()) {
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.to_receive), style = MaterialTheme.typography.labelMedium)
                                Text(f.amount(balances.filter { it.invoice.kind == com.cashbook.core.InvoiceKind.SALE }.sumOf { it.outstanding }), style = MaterialTheme.typography.titleMedium)
                            }
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.to_pay), style = MaterialTheme.typography.labelMedium)
                                Text(f.amount(balances.filter { it.invoice.kind == com.cashbook.core.InvoiceKind.PURCHASE }.sumOf { it.outstanding }), style = MaterialTheme.typography.titleMedium)
                            }
                        }
                        balances.forEach { b ->
                            Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(b.invoice.id)) }.padding(vertical = 4.dp)) {
                                Text("${b.invoice.number} · ${stringResource(R.string.due_x, f.date(b.invoice.dueDate))}", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                                Text(f.amount(b.outstanding), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { nav.navigate(Routes.invoiceEdit(0, "SALE", id)) }, Modifier.weight(1f)) { Text(stringResource(R.string.new_invoice), maxLines = 1) }
                            OutlinedButton(onClick = { nav.navigate(Routes.invoiceEdit(0, "PURCHASE", id)) }, Modifier.weight(1f)) { Text(stringResource(R.string.new_bill), maxLines = 1) }
                        }
                        OutlinedButton(onClick = {
                            vm.pendingReportFilter = TxnFilter(partyIds = setOf(id))
                            vm.updateSettings { it.copy(currentCashbookId = com.cashbook.app.data.AppSettings.ALL_CASHBOOKS.takeIf { snap.cashbooks.count { c -> !c.archived } > 1 } ?: it.currentCashbookId) }
                            nav.navigate(Routes.report("PARTY_STATEMENT"))
                        }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.report_party_statement), maxLines = 1) }
                    }
                    InfoBanner(stringResource(R.string.party_ledger_note), icon = Icons.Filled.Info)
                    OutlinedButton(onClick = {
                        vm.pendingReportFilter = TxnFilter(partyIds = setOf(id)); vm.pendingReportAllTime = true
                        vm.updateSettings { it.copy(currentCashbookId = com.cashbook.app.data.AppSettings.ALL_CASHBOOKS.takeIf { snap.cashbooks.count { c -> !c.archived } > 1 } ?: it.currentCashbookId) }
                        nav.navigate(Routes.report("PARTY_WISE"))
                    }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.export_party_report)) }
                }
            }
            items(txns, key = { it.id }) { t -> TxnRow(t, snap, onClick = { nav.navigate(Routes.txn(t.id)) }, showCashbook = true); HorizontalDivider() }
        }
    }
}

@Composable
fun PartyEditScreen(vm: AppViewModel, nav: NavHostController, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val existing = snap.partyById[id]
    val ctx = LocalContext.current
    var name by rememberSaveable { mutableStateOf("") }
    var type by rememberSaveable { mutableStateOf(PartyType.CUSTOMER) }
    var mobile by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var address by rememberSaveable { mutableStateOf("") }
    var gstin by rememberSaveable { mutableStateOf("") }
    var notes by rememberSaveable { mutableStateOf("") }
    var archived by rememberSaveable { mutableStateOf(false) }
    var stateCode by rememberSaveable { mutableStateOf("") }
    var loaded by rememberSaveable { mutableStateOf(id == 0L) }
    var usage by remember { mutableIntStateOf(0) }
    LaunchedEffect(existing) {
        if (!loaded && existing != null) {
            name = existing.name; type = existing.type; mobile = existing.mobile; email = existing.email; address = existing.address
            gstin = existing.gstin; notes = existing.notes; archived = existing.archived; stateCode = existing.stateCode; loaded = true
        }
        if (id > 0) usage = vm.deps?.ledger?.partyUsage(id) ?: 0
    }
    val gstinOk = gstin.isBlank() || com.cashbook.core.Gst.isValidGstin(gstin)
    val emailOk = email.isBlank() || android.util.Patterns.EMAIL_ADDRESS.matcher(email.trim()).matches()
    AppScaffold(title = stringResource(if (id == 0L) R.string.new_party else R.string.edit_party), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.name)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            DropdownField(stringResource(R.string.party_type), PartyType.entries, type, labelOf = { partyTypeLabel(it) }, onSelect = { type = it })
            OutlinedTextField(mobile, { mobile = it.filter { c -> c.isDigit() || c == '+' || c == ' ' }.take(16) }, label = { Text(stringResource(R.string.mobile)) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(email, { email = it }, label = { Text(stringResource(R.string.email)) }, singleLine = true, isError = !emailOk,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(address, { address = it }, label = { Text(stringResource(R.string.address)) }, modifier = Modifier.fillMaxWidth(), maxLines = 3)
            OutlinedTextField(gstin, { v -> gstin = v.uppercase().filter { c -> c.isLetterOrDigit() }.take(15)
                    if (gstin.length == 15) com.cashbook.core.Gst.stateFromGstin(gstin)?.let { stateCode = it } },
                label = { Text(stringResource(R.string.gstin_optional)) }, singleLine = true,
                isError = !gstinOk, supportingText = if (!gstinOk) ({ Text(stringResource(R.string.gstin_invalid_check)) }) else null, modifier = Modifier.fillMaxWidth())
            DropdownField(stringResource(R.string.state_ut), listOf("") + com.cashbook.core.Gst.STATES.keys, stateCode,
                labelOf = { if (it.isEmpty()) stringResource(R.string.not_set) else com.cashbook.core.Gst.stateLabel(it) }, onSelect = { stateCode = it },
                supporting = stringResource(R.string.party_state_hint), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(notes, { notes = it }, label = { Text(stringResource(R.string.notes)) }, modifier = Modifier.fillMaxWidth(), maxLines = 4)
            if (id > 0) SwitchRow(stringResource(R.string.archived), archived, { archived = it }, stringResource(R.string.archive_party_desc))
            Button(onClick = {
                if (name.isBlank() || !gstinOk || !emailOk) return@Button
                vm.run { ledger.saveParty(PartyEntity(id = id, name = name, type = type.name, mobile = mobile.trim(), email = email.trim(), address = address.trim(),
                    gstin = gstin.trim(), notes = notes.trim(), archived = archived, createdAt = 0, updatedAt = 0, stateCode = stateCode)) }
                nav.popBackStack()
            }, enabled = name.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
            if (id > 0) OutlinedButton(onClick = {
                vm.run {
                    if (ledger.deleteParty(id)) { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { nav.popBackStack(Routes.PARTIES, false) } }
                    else vm.toast(ctx.getString(R.string.party_in_use, usage))
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
        }
    }
}
