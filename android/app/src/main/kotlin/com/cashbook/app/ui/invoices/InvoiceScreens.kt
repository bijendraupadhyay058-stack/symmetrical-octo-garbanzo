package com.cashbook.app.ui.invoices

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.data.Snapshot
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.AppViewModel
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
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.paymentModeLabel
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.CategoryKind
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.Invoices
import com.cashbook.core.Money
import com.cashbook.core.PartyType
import com.cashbook.core.PaymentMode
import kotlinx.coroutines.launch
import java.time.LocalDate

@Composable
fun statusColor(s: InvoiceStatus): Color = LocalFinanceColors.current.let {
    when (s) { InvoiceStatus.PAID -> it.income; InvoiceStatus.OVERDUE -> it.expense; InvoiceStatus.PARTIAL -> it.warning
        InvoiceStatus.OPEN -> MaterialTheme.colorScheme.primary; InvoiceStatus.CANCELLED -> MaterialTheme.colorScheme.outline }
}

@Composable
fun statusLabel(b: InvoiceBalance): String = when (b.status) {
    InvoiceStatus.OPEN -> stringResource(R.string.inv_open)
    InvoiceStatus.PARTIAL -> stringResource(R.string.inv_partial)
    InvoiceStatus.OVERDUE -> stringResource(R.string.inv_overdue_days, b.daysOverdue)
    InvoiceStatus.PAID -> stringResource(R.string.inv_paid)
    InvoiceStatus.CANCELLED -> stringResource(R.string.inv_cancelled)
}

/** Text status chip (never colour alone). */
@Composable
fun StatusChip(b: InvoiceBalance) {
    val c = statusColor(b.status)
    Text(statusLabel(b), style = MaterialTheme.typography.labelSmall, color = c,
        modifier = Modifier.background(c.copy(alpha = 0.12f), RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp))
}

@Composable
fun kindLabel(k: InvoiceKind) = stringResource(if (k == InvoiceKind.SALE) R.string.inv_kind_sale else R.string.inv_kind_purchase)

private enum class Filter { OPEN, OVERDUE, PAID, ALL }

@Composable
fun InvoicesScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    var tab by rememberSaveable { mutableStateOf(0) }
    var filter by rememberSaveable { mutableStateOf(Filter.OPEN) }
    val kind = if (tab == 0) InvoiceKind.SALE else InvoiceKind.PURCHASE
    val scope = currentScope(snap, s)
    val all = snap.invoiceBalances().filter { it.invoice.cashbookId in scope && it.invoice.kind == kind }
    val shown = all.filter {
        when (filter) {
            Filter.OPEN -> it.outstanding > 0
            Filter.OVERDUE -> it.status == InvoiceStatus.OVERDUE
            Filter.PAID -> it.status == InvoiceStatus.PAID
            Filter.ALL -> true
        }
    }.sortedWith(compareBy({ it.outstanding == 0L }, { it.invoice.dueDate }))
    AppScaffold(title = stringResource(R.string.invoices_bills), onBack = { nav.popBackStack() }, floating = {
        ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.invoiceEdit(0, kind.name)) }, icon = { Icon(Icons.Filled.Add, null) },
            text = { Text(stringResource(if (kind == InvoiceKind.SALE) R.string.new_invoice else R.string.new_bill)) })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            TabRow(tab) {
                Tab(tab == 0, { tab = 0 }, text = { Text(stringResource(R.string.receivables)) })
                Tab(tab == 1, { tab = 1 }, text = { Text(stringResource(R.string.payables)) })
            }
            LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        SectionCard {
                            Row {
                                Column(Modifier.weight(1f)) {
                                    Text(stringResource(if (kind == InvoiceKind.SALE) R.string.to_receive else R.string.to_pay), style = MaterialTheme.typography.labelLarge)
                                    Text(f.amount(all.sumOf { it.outstanding }), style = MaterialTheme.typography.titleLarge)
                                }
                                Column(horizontalAlignment = Alignment.End) {
                                    Text(stringResource(R.string.overdue), style = MaterialTheme.typography.labelLarge)
                                    Text(f.amount(all.filter { it.status == InvoiceStatus.OVERDUE }.sumOf { it.outstanding }), style = MaterialTheme.typography.titleLarge,
                                        color = fc.expense)
                                }
                            }
                        }
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Filter.entries.forEach { fl ->
                                FilterChip(filter == fl, { filter = fl }, { Text(stringResource(when (fl) {
                                    Filter.OPEN -> R.string.inv_filter_unpaid; Filter.OVERDUE -> R.string.overdue; Filter.PAID -> R.string.inv_paid; Filter.ALL -> R.string.inv_filter_all })) })
                            }
                        }
                        InfoBanner(stringResource(R.string.invoices_intro), icon = Icons.Filled.Info)
                    }
                }
                if (shown.isEmpty()) item { EmptyState(Icons.Filled.Description, stringResource(R.string.no_invoices)) }
                items(shown, key = { it.invoice.id }) { b ->
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(b.invoice.id)) }.padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(snap.names.party(b.invoice.partyId), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("${b.invoice.number} · ${stringResource(R.string.due_x, f.date(b.invoice.dueDate))}", style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(Modifier.height(2.dp)); StatusChip(b)
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(f.amount(b.outstanding), style = MaterialTheme.typography.titleSmall)
                            Text(stringResource(R.string.of_x, f.amount(b.invoice.amount)), style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    HorizontalDivider()
                }
                item { Box(Modifier.padding(40.dp)) }
            }
        }
    }
}

@Composable
fun InvoiceEditScreen(vm: AppViewModel, nav: NavHostController, id: Long, kindName: String, presetParty: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    var kind by rememberSaveable { mutableStateOf(runCatching { InvoiceKind.valueOf(kindName) }.getOrDefault(InvoiceKind.SALE)) }
    var cashbookId by rememberSaveable { mutableStateOf(0L) }
    var number by rememberSaveable { mutableStateOf("") }
    var partyId by rememberSaveable { mutableStateOf(presetParty) }
    var issue by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var due by rememberSaveable { mutableStateOf(LocalDate.now().plusDays(15).toEpochDay()) }
    var amount by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var notes by rememberSaveable { mutableStateOf("") }
    var itemised by rememberSaveable { mutableStateOf(true) }
    var items by rememberSaveable(stateSaver = ItemDraft.ListSaver) { mutableStateOf(listOf(ItemDraft())) }
    var placeOfSupply by rememberSaveable { mutableStateOf("") }
    var roundOff by rememberSaveable { mutableStateOf(true) }
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    var loaded by rememberSaveable { mutableStateOf(false) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    var partyPicker by rememberSaveable { mutableStateOf(false) }
    var newParty by rememberSaveable { mutableStateOf<String?>(null) }

    // New invoice: once the business profile has loaded, default the place of supply to the seller's state.
    LaunchedEffect(seller.stateCode) { if (id == 0L && placeOfSupply.isBlank() && snap.partyById[partyId]?.stateCode.isNullOrBlank()) placeOfSupply = seller.stateCode }
    LaunchedEffect(snap.loaded) {
        if (loaded || !snap.loaded) return@LaunchedEffect
        val existing = snap.invoices.firstOrNull { it.id == id }
        if (existing != null) {
            kind = existing.kind; cashbookId = existing.cashbookId; number = existing.number; partyId = existing.partyId
            issue = existing.issueDate.toEpochDay(); due = existing.dueDate.toEpochDay(); amount = Money.toPlain(existing.amount)
            description = existing.description; notes = existing.notes
            placeOfSupply = existing.placeOfSupply; roundOff = existing.roundOff
            val existingItems = snap.invoiceItems[id].orEmpty()
            itemised = existingItems.isNotEmpty()
            items = if (existingItems.isEmpty()) listOf(ItemDraft()) else existingItems.map { ItemDraft.from(it) }
        } else {
            placeOfSupply = snap.partyById[presetParty]?.stateCode?.ifBlank { null } ?: seller.stateCode
            val sc = currentScope(snap, s)
            cashbookId = if (s.defaultCashbookId in sc) s.defaultCashbookId else sc.firstOrNull() ?: 0
            number = vm.deps?.ledger?.nextInvoiceNumber(cashbookId, kind, LocalDate.now()) ?: ""
        }
        loaded = true
    }
    val parsed = Money.parse(amount)
    val paid = snap.invoiceBalances().firstOrNull { it.invoice.id == id }?.paid ?: 0L
    val itemsValid = items.isNotEmpty() && items.all { it.valid }
    val totals = if (itemised && itemsValid) com.cashbook.core.GstCalc.totals(items.map { it.toItem() },
        com.cashbook.core.GstCalc.isInterState(seller.stateCode, placeOfSupply), roundOff) else null
    val errAmount = if (itemised) !itemsValid || (totals?.grandTotal ?: 0) <= 0 || (totals?.grandTotal ?: 0) < paid
        else parsed !is Money.ParseResult.Ok || (parsed as Money.ParseResult.Ok).paise < paid
    val errParty = snap.partyById[partyId] == null
    val errDates = due < issue
    val msgDuplicate = stringResource(R.string.inv_err_duplicate)
    val msgBelowPaid = stringResource(R.string.inv_err_below_paid)

    AppScaffold(title = stringResource(if (id == 0L) (if (kind == InvoiceKind.SALE) R.string.new_invoice else R.string.new_bill) else R.string.edit_invoice),
        onBack = { nav.popBackStack() }, snackbar = snackbar) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (id == 0L) SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                InvoiceKind.entries.forEachIndexed { i, k ->
                    SegmentedButton(kind == k, onClick = {
                        if (kind != k) { kind = k; scope.launch { number = vm.deps?.ledger?.nextInvoiceNumber(cashbookId, k, LocalDate.ofEpochDay(issue)) ?: number } }
                    }, shape = SegmentedButtonDefaults.itemShape(i, 2)) { Text(kindLabel(k), maxLines = 1) }
                }
            }
            Text(stringResource(if (kind == InvoiceKind.SALE) R.string.inv_sale_explain else R.string.inv_purchase_explain), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            val cbs = snap.cashbooks.filter { !it.archived || it.id == cashbookId }
            if (cbs.size > 1 && id == 0L) DropdownField(stringResource(R.string.cashbook), cbs.map { it.id }, cashbookId.takeIf { it != 0L },
                labelOf = { snap.cashbookById[it]?.name ?: "" }, onSelect = { cashbookId = it })
            PickerField(stringResource(if (kind == InvoiceKind.SALE) R.string.inv_customer else R.string.inv_supplier), snap.names.party(partyId.takeIf { it > 0 }),
                { partyPicker = true }, isError = showErrors && errParty, supporting = if (showErrors && errParty) stringResource(R.string.inv_err_party) else null)
            OutlinedTextField(number, { number = it }, label = { Text(stringResource(R.string.inv_number)) }, singleLine = true, isError = showErrors && number.isBlank(),
                modifier = Modifier.fillMaxWidth())
            com.cashbook.app.ui.components.SwitchRow(stringResource(R.string.itemised_gst), itemised, { itemised = it }, stringResource(R.string.itemised_gst_desc))
            if (!itemised) MoneyField(amount, { amount = it }, stringResource(R.string.inv_amount),
                error = if (showErrors && errAmount) (if (paid > 0) stringResource(R.string.inv_err_below_paid) else stringResource(R.string.err_amount_invalid)) else null)
            DateField(stringResource(R.string.inv_issue_date), LocalDate.ofEpochDay(issue), { issue = it.toEpochDay() })
            DateField(stringResource(R.string.inv_due_date), LocalDate.ofEpochDay(due), { due = it.toEpochDay() }, isError = errDates,
                supporting = if (errDates) stringResource(R.string.inv_err_due_before) else null)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(0, 7, 15, 30, 45, 60).forEach { d ->
                    FilterChip(due - issue == d.toLong(), { due = issue + d }, { Text(if (d == 0) stringResource(R.string.inv_on_receipt) else stringResource(R.string.inv_net_days, d)) })
                }
            }
            if (itemised) {
                DropdownField(stringResource(R.string.place_of_supply), listOf("") + com.cashbook.core.Gst.STATES.keys, placeOfSupply,
                    labelOf = { if (it.isEmpty()) stringResource(R.string.not_set) else com.cashbook.core.Gst.stateLabel(it) }, onSelect = { placeOfSupply = it },
                    supporting = if (seller.stateCode.isBlank()) stringResource(R.string.set_business_state) else null, modifier = Modifier.fillMaxWidth())
                InvoiceItemsEditor(items, { items = it }, showErrors, totals)
                com.cashbook.app.ui.components.SwitchRow(stringResource(R.string.round_off_total), roundOff, { roundOff = it })
                totals?.let { TotalsCard(it) }
                if (showErrors && errAmount && paid > 0 && itemsValid) Text(stringResource(R.string.inv_err_below_paid), color = MaterialTheme.colorScheme.error)
            }
            OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.description)) }, modifier = Modifier.fillMaxWidth(), maxLines = 3)
            OutlinedTextField(notes, { notes = it }, label = { Text(stringResource(R.string.notes)) }, modifier = Modifier.fillMaxWidth(), maxLines = 4)
            InfoBanner(stringResource(R.string.inv_not_cash_note), icon = Icons.Filled.Info)
            Button(onClick = {
                showErrors = true
                if (errAmount || errParty || errDates || number.isBlank() || cashbookId == 0L) return@Button
                val inv = InvoiceInfo(id, cashbookId, kind, number, partyId, LocalDate.ofEpochDay(issue), LocalDate.ofEpochDay(due),
                    if (itemised) totals!!.grandTotal else (parsed as Money.ParseResult.Ok).paise, description, notes,
                    placeOfSupply = placeOfSupply, roundOff = roundOff)
                val lineItems = if (itemised) items.map { it.toItem() } else emptyList()
                vm.run(onError = { e ->
                    val m = when ((e as? LedgerRepository.InvoiceException)?.reason) {
                        LedgerRepository.InvoiceException.Reason.DUPLICATE_NUMBER -> msgDuplicate
                        LedgerRepository.InvoiceException.Reason.BELOW_PAID -> msgBelowPaid
                        else -> e.localizedMessage ?: ""
                    }
                    scope.launch { snackbar.showSnackbar(m) }
                }) {
                    val newId = ledger.saveInvoice(inv, lineItems, seller.stateCode)
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) {
                        nav.popBackStack()
                        if (id == 0L) nav.navigate(Routes.invoice(newId))
                    }
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
        }
    }
    if (partyPicker) SearchPickerSheet(stringResource(R.string.select_party), snap.parties.filter { !it.archived || it.id == partyId }.map { PickItem(it.id, it.name, it.mobile) },
        onPick = { p -> partyId = p?.id ?: 0; partyPicker = false
            snap.partyById[partyId]?.stateCode?.takeIf { it.isNotBlank() }?.let { placeOfSupply = it } },
        onDismiss = { partyPicker = false },
        createLabel = stringResource(R.string.new_party), onCreate = { q -> newParty = q; partyPicker = false })
    newParty?.let { initial ->
        var name by remember { mutableStateOf(initial) }
        AlertDialog(onDismissRequest = { newParty = null }, title = { Text(stringResource(R.string.new_party)) },
            text = { OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.name)) }, singleLine = true) },
            confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = {
                val type = if (kind == InvoiceKind.SALE) PartyType.CUSTOMER else PartyType.SUPPLIER
                vm.run { partyId = ledger.saveParty(PartyEntity(name = name, type = type.name, createdAt = 0, updatedAt = 0)) }
                newParty = null
            }) { Text(stringResource(R.string.create)) } },
            dismissButton = { TextButton(onClick = { newParty = null }) { Text(stringResource(R.string.cancel)) } })
    }
}

@Composable
fun InvoiceDetailScreen(vm: AppViewModel, nav: NavHostController, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val ctx = LocalContext.current
    val b = snap.invoiceBalances().firstOrNull { it.invoice.id == id }
    var applyExisting by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val hasPaymentsMsg = stringResource(R.string.inv_err_has_payments)
    AppScaffold(title = b?.invoice?.number ?: "", onBack = { nav.popBackStack() }, actions = {
        if (b != null) {
            IconButton(onClick = { vm.allowExternalActivity(); Exporter.shareText(ctx, shareText(ctx, b, snap, f), ctx.getString(R.string.share)) }) {
                Icon(Icons.Filled.Share, stringResource(R.string.share)) }
            IconButton(onClick = { nav.navigate(Routes.invoiceEdit(id)) }) { Icon(Icons.Filled.Edit, stringResource(R.string.edit)) }
        }
    }) { pad ->
        if (b == null) { EmptyState(Icons.Filled.Description, stringResource(R.string.entry_not_found), Modifier.padding(pad)); return@AppScaffold }
        val inv = b.invoice
        val payments = snap.allocations.filter { it.invoiceId == id }
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(kindLabel(inv.kind), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                        Text(snap.names.party(inv.partyId), style = MaterialTheme.typography.titleLarge)
                        Text("${stringResource(R.string.inv_issue_date)}: ${f.date(inv.issueDate)} · ${stringResource(R.string.due_x, f.date(inv.dueDate))}",
                            style = MaterialTheme.typography.bodySmall)
                    }
                    StatusChip(b)
                }
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
                AmountLine(stringResource(R.string.inv_amount), f.amount(inv.amount))
                AmountLine(stringResource(if (inv.kind == InvoiceKind.SALE) R.string.inv_received else R.string.inv_paid_amount), f.amount(b.paid), fc.income)
                AmountLine(stringResource(R.string.inv_outstanding), f.amount(b.outstanding), if (b.status == InvoiceStatus.OVERDUE) fc.expense else null, bold = true)
                if (inv.description.isNotBlank()) Text(inv.description, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
                if (inv.placeOfSupply.isNotBlank()) Text("${stringResource(R.string.place_of_supply)}: ${com.cashbook.core.Gst.stateLabel(inv.placeOfSupply)}",
                    style = MaterialTheme.typography.bodySmall)
                if (inv.notes.isNotBlank()) Text(inv.notes, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            val lineItems = snap.invoiceItems[id].orEmpty()
            val seller by vm.businessProfile.collectAsStateWithLifecycle()
            if (lineItems.isNotEmpty()) {
                val t = com.cashbook.core.GstCalc.totals(lineItems, com.cashbook.core.GstCalc.isInterState(seller.stateCode, inv.placeOfSupply), inv.roundOff)
                SectionCard(stringResource(R.string.items)) {
                    t.lines.forEachIndexed { i, l ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text("${i + 1}. ${l.item.description}", style = MaterialTheme.typography.bodyMedium)
                                Text("${com.cashbook.core.Gst.formatQuantity(l.item.quantityMilli)} ${l.item.unit} × ${f.amount(l.item.rate)}" +
                                    (if (l.item.discountBp > 0) " − ${com.cashbook.core.Gst.formatPercent(l.item.discountBp)}%" else "") +
                                    " · GST ${com.cashbook.core.Gst.rateLabel(l.item.gstBp)}" + (if (l.item.hsn.isNotBlank()) " · HSN/SAC ${l.item.hsn}" else ""),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(f.amount(l.total), style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
                TotalsCard(t)
            }
            if (inv.kind == InvoiceKind.SALE) InvoicePdfButtons(vm, snap, b)
            if (b.outstanding > 0) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { nav.navigate(Routes.recordPayment(id)) }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(if (inv.kind == InvoiceKind.SALE) R.string.inv_record_receipt else R.string.inv_record_payment)) }
                OutlinedButton(onClick = { applyExisting = true }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.inv_apply_existing)) }
            }
            SectionCard(stringResource(R.string.inv_payments)) {
                if (payments.isEmpty()) Text(stringResource(R.string.inv_no_payments), style = MaterialTheme.typography.bodySmall)
                payments.forEach { a ->
                    val t = snap.txns.firstOrNull { it.id == a.txnId } ?: snap.deleted.firstOrNull { it.id == a.txnId }
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.txn(a.txnId)) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(t?.let { f.date(it.date) + " · " + snap.names.account(it.accountId) + " · " + paymentModeLabel(it.paymentMode) } ?: "", style = MaterialTheme.typography.bodyMedium)
                            if (t?.deletedAt != null) Text(stringResource(R.string.inv_payment_in_bin), style = MaterialTheme.typography.labelSmall, color = fc.expense)
                        }
                        Text(f.amount(a.amount), style = MaterialTheme.typography.titleSmall)
                        IconButton(onClick = { vm.run { ledger.allocate(id, a.txnId, 0) } }) { Icon(Icons.Filled.Close, stringResource(R.string.inv_unlink)) }
                    }
                    HorizontalDivider()
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    vm.run(onError = { vm.toast(hasPaymentsMsg) }) { ledger.setInvoiceCancelled(id, !inv.cancelled) }
                }, modifier = Modifier.weight(1f)) { Text(stringResource(if (inv.cancelled) R.string.inv_reopen else R.string.inv_cancel)) }
                OutlinedButton(onClick = { if (payments.isEmpty()) confirmDelete = true else vm.toast(hasPaymentsMsg) }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            }
        }
    }
    if (b != null && applyExisting) ApplyEntryDialog(vm, snap, b) { applyExisting = false }
    if (confirmDelete) ConfirmDialog(stringResource(R.string.inv_delete_title), stringResource(R.string.inv_delete_text), stringResource(R.string.delete),
        onConfirm = { vm.run { ledger.deleteInvoice(id) }; nav.popBackStack() }, onDismiss = { confirmDelete = false }, destructive = true)
}

@Composable
private fun AmountLine(label: String, value: String, color: Color? = null, bold: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, Modifier.weight(1f), style = if (bold) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium)
        Text(value, style = if (bold) MaterialTheme.typography.titleMedium else MaterialTheme.typography.bodyMedium, color = color ?: MaterialTheme.colorScheme.onSurface)
    }
}

/** Records money received for an invoice (or paid for a bill): creates the entry and applies it in one step. */
@Composable
fun RecordPaymentScreen(vm: AppViewModel, nav: NavHostController, invoiceId: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val b = snap.invoiceBalances().firstOrNull { it.invoice.id == invoiceId } ?: return
    val inv = b.invoice
    val catKind = if (inv.kind == InvoiceKind.SALE) CategoryKind.INCOME else CategoryKind.EXPENSE
    val accounts = snap.accounts.filter { it.cashbookId == inv.cashbookId && !it.archived }
    // default category: the one last used with this party for this type…
    val lastCat = snap.txns.filter { it.partyId == inv.partyId && it.type == inv.kind.paymentType }.maxByOrNull { it.date }?.categoryId
    val cats = snap.categoriesOf(catKind).filter { !it.archived }
    var amount by rememberSaveable { mutableStateOf(Money.toPlain(b.outstanding)) }
    var accountId by rememberSaveable { mutableStateOf(accounts.firstOrNull { it.type != com.cashbook.core.AccountType.CASH }?.id ?: accounts.firstOrNull()?.id ?: 0L) }
    // otherwise the category most used for this kind of entry in the cashbook
    val mostUsed = snap.txns.filter { it.cashbookId == inv.cashbookId && it.type == inv.kind.paymentType && it.categoryId != null }
        .groupingBy { it.categoryId!! }.eachCount().maxByOrNull { it.value }?.key
    var categoryId by rememberSaveable { mutableStateOf(lastCat ?: mostUsed ?: cats.firstOrNull()?.id ?: 0L) }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var mode by rememberSaveable { mutableStateOf(PaymentMode.UPI) }
    var reference by rememberSaveable { mutableStateOf("") }
    val parsed = Money.parse(amount)
    val tooMuch = parsed is Money.ParseResult.Ok && parsed.paise > b.outstanding
    val ok = parsed is Money.ParseResult.Ok && !tooMuch && accountId != 0L && categoryId != 0L
    val label = stringResource(if (inv.kind == InvoiceKind.SALE) R.string.inv_payment_for else R.string.inv_payment_of, inv.number)
    val f = LocalUiFormat.current
    AppScaffold(title = stringResource(if (inv.kind == InvoiceKind.SALE) R.string.inv_record_receipt else R.string.inv_record_payment), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            InfoBanner("${inv.number} · ${snap.names.party(inv.partyId)} · ${stringResource(R.string.inv_outstanding)} ${f.amount(b.outstanding)}")
            MoneyField(amount, { amount = it }, stringResource(R.string.amount_required),
                error = when { tooMuch -> stringResource(R.string.inv_err_more_than_outstanding); parsed is Money.ParseResult.Error && amount.isNotEmpty() -> stringResource(R.string.err_amount_invalid); else -> null })
            DropdownField(stringResource(R.string.account), accounts.map { it.id }, accountId.takeIf { it != 0L }, labelOf = { snap.names.account(it) }, onSelect = { accountId = it })
            DropdownField(stringResource(R.string.category), cats.map { it.id }, categoryId.takeIf { it != 0L }, labelOf = { snap.categoryName(it) }, onSelect = { categoryId = it })
            DropdownField(stringResource(R.string.payment_mode), PaymentMode.entries, mode, labelOf = { paymentModeLabel(it) }, onSelect = { mode = it })
            DateField(stringResource(R.string.date), LocalDate.ofEpochDay(date), { date = it.toEpochDay() })
            OutlinedTextField(reference, { reference = it }, label = { Text(stringResource(R.string.reference_number)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button(enabled = ok, onClick = {
                val paise = (parsed as Money.ParseResult.Ok).paise
                vm.run { ledger.recordPayment(inv.id, accountId, categoryId, paise, LocalDate.ofEpochDay(date), mode, reference, label) }
                nav.popBackStack()
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
        }
    }
}

/** Applies part of an already-recorded income/expense entry to this invoice. */
@Composable
private fun ApplyEntryDialog(vm: AppViewModel, snap: Snapshot, b: InvoiceBalance, onDismiss: () -> Unit) {
    val f = LocalUiFormat.current
    val inv = b.invoice
    val candidates = snap.txns.filter { it.type == inv.kind.paymentType && it.cashbookId == inv.cashbookId && Invoices.unallocated(it, snap.allocations) > 0 }
        .sortedWith(compareBy({ it.partyId != inv.partyId }, { -it.date.toEpochDay() })).take(50)
    var selected by remember { mutableStateOf<Long?>(null) }
    var amount by remember { mutableStateOf("") }
    val txn = candidates.firstOrNull { it.id == selected }
    val parsed = Money.parse(amount)
    val err = if (txn != null && parsed is Money.ParseResult.Ok) Invoices.validateAllocation(b, txn, parsed.paise, snap.allocations) else null
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.inv_apply_existing)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (candidates.isEmpty()) Text(stringResource(R.string.inv_no_candidates))
                candidates.forEach { t ->
                    val free = Invoices.unallocated(t, snap.allocations)
                    Row(Modifier.fillMaxWidth().clickable { selected = t.id; amount = Money.toPlain(minOf(free, b.outstanding)) }
                        .background(if (selected == t.id) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent).padding(8.dp)) {
                        Column(Modifier.weight(1f)) {
                            Text(t.description.ifBlank { snap.categoryName(t.categoryId) }, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("${f.date(t.date)} · ${snap.names.party(t.partyId).ifBlank { "—" }}", style = MaterialTheme.typography.bodySmall)
                        }
                        Text(stringResource(R.string.inv_free_x, f.amount(free)), style = MaterialTheme.typography.labelMedium)
                    }
                }
                if (txn != null) MoneyField(amount, { amount = it }, stringResource(R.string.amount_required), Modifier.padding(top = 8.dp),
                    error = if (err != null) stringResource(R.string.inv_err_allocation) else null)
            }
        },
        confirmButton = { TextButton(enabled = txn != null && parsed is Money.ParseResult.Ok && err == null, onClick = {
            val paise = (parsed as Money.ParseResult.Ok).paise
            vm.run { ledger.allocate(inv.id, txn!!.id, paise) }
            onDismiss()
        }) { Text(stringResource(R.string.apply)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

private fun shareText(ctx: android.content.Context, b: InvoiceBalance, snap: Snapshot, f: com.cashbook.app.ui.components.UiFormat): String {
    val inv = b.invoice
    return buildString {
        appendLine(ctx.getString(if (inv.kind == InvoiceKind.SALE) R.string.inv_kind_sale else R.string.inv_kind_purchase) + " " + inv.number)
        appendLine(snap.names.party(inv.partyId))
        appendLine("${ctx.getString(R.string.inv_issue_date)}: ${f.date(inv.issueDate)}")
        appendLine("${ctx.getString(R.string.inv_due_date)}: ${f.date(inv.dueDate)}")
        appendLine("${ctx.getString(R.string.inv_amount)}: ${f.amount(inv.amount)}")
        if (b.paid > 0) appendLine("${ctx.getString(R.string.inv_paid_amount)}: ${f.amount(b.paid)}")
        appendLine("${ctx.getString(R.string.inv_outstanding)}: ${f.amount(b.outstanding)}")
        if (inv.description.isNotBlank()) appendLine(inv.description)
    }.trim()
}


fun invoicePdfStrings(c: android.content.Context) = com.cashbook.app.export.InvoicePdfWriter.Strings(
    c.getString(R.string.pdf_tax_invoice), c.getString(R.string.pdf_invoice), c.getString(R.string.pdf_invoice_no), c.getString(R.string.inv_issue_date),
    c.getString(R.string.inv_due_date), c.getString(R.string.place_of_supply), c.getString(R.string.pdf_bill_to), "GSTIN", c.getString(R.string.state_ut),
    c.getString(R.string.mobile), c.getString(R.string.pdf_sr), c.getString(R.string.item_description), c.getString(R.string.item_hsn),
    c.getString(R.string.item_qty), c.getString(R.string.item_rate), c.getString(R.string.pdf_disc), c.getString(R.string.taxable_value),
    c.getString(R.string.pdf_gst), c.getString(R.string.amount), c.getString(R.string.pdf_tax_summary), "CGST", "SGST", "IGST",
    c.getString(R.string.rl_total_tax), c.getString(R.string.round_off), c.getString(R.string.grand_total), c.getString(R.string.inv_paid_amount),
    c.getString(R.string.pdf_balance_due), c.getString(R.string.pdf_amount_in_words), c.getString(R.string.bp_payment_details),
    c.getString(R.string.pdf_bank), c.getString(R.string.pdf_account_name), c.getString(R.string.pdf_account_no), "IFSC", "UPI",
    c.getString(R.string.pdf_terms), c.getString(R.string.pdf_for), c.getString(R.string.pdf_authorised_signatory), c.getString(R.string.page_x_of_y),
    c.getString(R.string.pdf_generated_by), "",
)

/** Save or share the invoice as a printable PDF. */
@Composable
fun InvoicePdfButtons(vm: AppViewModel, snap: Snapshot, b: InvoiceBalance) {
    val ctx = LocalContext.current
    val f = LocalUiFormat.current
    val settings by vm.settings.collectAsStateWithLifecycle()
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val failed = stringResource(R.string.export_failed)
    val saved = stringResource(R.string.export_saved)
    val name = Exporter.safeFileName("${b.invoice.number}_${snap.names.party(b.invoice.partyId)}") + ".pdf"
    fun write(out: java.io.OutputStream) = com.cashbook.app.export.InvoicePdfWriter(f.money, settings?.dateFormat ?: com.cashbook.core.DateFormatOption.DD_MM_YYYY,
        invoicePdfStrings(ctx)).write(b, snap.invoiceItems[b.invoice.id].orEmpty(), seller, snap.partyById[b.invoice.partyId], out)
    val save = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.CreateDocument(Exporter.MIME_PDF)) { uri ->
        if (uri != null) scope.launch {
            val ok = runCatching { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { Exporter.writeTo(ctx, uri) { write(it) } } }.isSuccess
            vm.toast(if (ok) saved else failed)
        }
    }
    if (seller.name.isBlank()) InfoBanner(stringResource(R.string.pdf_set_profile_hint), icon = Icons.Filled.Info)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { vm.allowExternalActivity(); save.launch(name) }, modifier = Modifier.weight(1f)) {
            Icon(Icons.Filled.Description, null); Text(" " + stringResource(R.string.save_pdf), maxLines = 1) }
        OutlinedButton(onClick = {
            scope.launch {
                val uri = runCatching { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { Exporter.writeShareable(ctx, name) { write(it) } } }.getOrNull()
                if (uri == null) vm.toast(failed) else { vm.allowExternalActivity(); Exporter.share(ctx, uri, Exporter.MIME_PDF, b.invoice.number) }
            }
        }, modifier = Modifier.weight(1f)) { Icon(Icons.Filled.Share, null); Text(" " + stringResource(R.string.share_pdf), maxLines = 1) }
    }
}
