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
import androidx.compose.material.icons.filled.Repeat
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
        InvoiceStatus.OPEN -> MaterialTheme.colorScheme.primary; InvoiceStatus.CANCELLED -> MaterialTheme.colorScheme.outline
        InvoiceStatus.REFUND_DUE -> it.transfer }
}

@Composable
fun statusLabel(b: InvoiceBalance): String = when (b.status) {
    InvoiceStatus.OPEN -> stringResource(R.string.inv_open)
    InvoiceStatus.PARTIAL -> stringResource(R.string.inv_partial)
    InvoiceStatus.OVERDUE -> stringResource(R.string.inv_overdue_days, b.daysOverdue)
    InvoiceStatus.PAID -> stringResource(R.string.inv_paid)
    InvoiceStatus.CANCELLED -> stringResource(R.string.inv_cancelled)
    InvoiceStatus.REFUND_DUE -> stringResource(R.string.inv_refund_due_x, LocalUiFormat.current.amount(b.refundDue))
}

@Composable
fun docTypeLabel(t: com.cashbook.core.DocType, kind: InvoiceKind) = when (t) {
    com.cashbook.core.DocType.CREDIT_NOTE -> stringResource(R.string.credit_note)
    com.cashbook.core.DocType.DEBIT_NOTE -> stringResource(R.string.debit_note)
    com.cashbook.core.DocType.INVOICE -> kindLabel(kind)
    com.cashbook.core.DocType.QUOTATION -> stringResource(if (kind == InvoiceKind.SALE) R.string.quotation else R.string.purchase_order)
    com.cashbook.core.DocType.CHALLAN -> stringResource(R.string.delivery_challan)
    com.cashbook.core.DocType.TEMPLATE -> stringResource(R.string.recurring_invoice)
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
    var docView by rememberSaveable { mutableStateOf(PreDocView.QUOTATIONS) }
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
    AppScaffold(title = stringResource(R.string.invoices_bills), onBack = { nav.popBackStack() }, actions = {
        IconButton(onClick = { nav.navigate(Routes.RECURRING_INVOICES) }) { Icon(Icons.Filled.Repeat, stringResource(R.string.recurring_invoices)) }
    }, floating = {
        if (tab == 2) ExtendedFloatingActionButton(onClick = {
            nav.navigate(when (docView) { PreDocView.QUOTATIONS -> Routes.quoteEdit(0, "SALE"); PreDocView.PURCHASE_ORDERS -> Routes.quoteEdit(0, "PURCHASE")
                PreDocView.CHALLANS -> Routes.challanEdit(0) })
        }, icon = { Icon(Icons.Filled.Add, null) }, text = { Text(stringResource(when (docView) {
            PreDocView.QUOTATIONS -> R.string.new_quotation; PreDocView.PURCHASE_ORDERS -> R.string.new_purchase_order; PreDocView.CHALLANS -> R.string.new_challan })) })
        else ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.invoiceEdit(0, kind.name)) }, icon = { Icon(Icons.Filled.Add, null) },
            text = { Text(stringResource(if (kind == InvoiceKind.SALE) R.string.new_invoice else R.string.new_bill)) })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            TabRow(tab) {
                Tab(tab == 0, { tab = 0 }, text = { Text(stringResource(R.string.receivables), maxLines = 1) })
                Tab(tab == 1, { tab = 1 }, text = { Text(stringResource(R.string.payables), maxLines = 1) })
                Tab(tab == 2, { tab = 2 }, text = { Text(stringResource(R.string.quotes_and_orders), maxLines = 1) })
            }
            if (tab == 2) { QuotationList(snap, nav, scope, docView) { docView = it }; return@Column }
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
                        val overdueCustomers = all.filter { it.status == InvoiceStatus.OVERDUE && it.invoice.kind == InvoiceKind.SALE }.map { it.invoice.partyId }.distinct().size
                        if (kind == InvoiceKind.SALE && overdueCustomers > 0) OutlinedButton(onClick = { nav.navigate(Routes.COLLECTIONS) }, modifier = Modifier.fillMaxWidth()) {
                            Icon(Icons.Filled.Share, null); Text(" " + stringResource(R.string.remind_overdue_x, overdueCustomers), maxLines = 1) }
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
fun InvoiceEditScreen(vm: AppViewModel, nav: NavHostController, id: Long, kindName: String, presetParty: Long,
                      docType: com.cashbook.core.DocType = com.cashbook.core.DocType.INVOICE, refInvoiceId: Long = 0) {
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
    // transport (sales invoices and challans)
    var vehicle by rememberSaveable { mutableStateOf("") }
    var transporter by rememberSaveable { mutableStateOf("") }
    var lrNo by rememberSaveable { mutableStateOf("") }
    var eway by rememberSaveable { mutableStateOf("") }
    var showTransport by rememberSaveable { mutableStateOf(false) }
    // schedule (recurring invoice templates)
    var frequency by rememberSaveable { mutableStateOf(com.cashbook.core.Frequency.MONTHLY) }
    var every by rememberSaveable { mutableStateOf("1") }
    var start by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var hasEnd by rememberSaveable { mutableStateOf(false) }
    var end by rememberSaveable { mutableStateOf(LocalDate.now().plusYears(1).toEpochDay()) }
    var dueDays by rememberSaveable { mutableStateOf(15) }
    var confirmDeleteSchedule by remember { mutableStateOf(false) }
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    var loaded by rememberSaveable { mutableStateOf(false) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    var partyPicker by rememberSaveable { mutableStateOf(false) }
    var newParty by rememberSaveable { mutableStateOf<String?>(null) }

    // New invoice: once the business profile has loaded, default the place of supply to the seller's state.
    LaunchedEffect(seller.stateCode) { if (id == 0L && placeOfSupply.isBlank() && snap.partyById[partyId]?.stateCode.isNullOrBlank()) placeOfSupply = seller.stateCode }
    val existingDoc = snap.doc(id)
    val isQuote = docType == com.cashbook.core.DocType.QUOTATION || existingDoc?.docType == com.cashbook.core.DocType.QUOTATION
    val isChallan = docType == com.cashbook.core.DocType.CHALLAN || existingDoc?.docType == com.cashbook.core.DocType.CHALLAN
    val isTemplate = docType == com.cashbook.core.DocType.TEMPLATE || existingDoc?.docType == com.cashbook.core.DocType.TEMPLATE
    val schedule = snap.schedules.firstOrNull { it.templateId == id }
    val isNote = docType.isNote || existingDoc?.docType?.isNote == true
    val original = (existingDoc?.refInvoiceId ?: refInvoiceId.takeIf { it > 0 })?.let { r -> snap.invoices.firstOrNull { it.id == r } }
    val noteType = existingDoc?.docType ?: docType
    LaunchedEffect(snap.loaded) {
        if (loaded || !snap.loaded) return@LaunchedEffect
        val existing = snap.doc(id)
        if (existing == null && isNote && original != null) {
            // new credit/debit note: same party, kind and place of supply as the invoice; a credit note starts from its items
            kind = original.kind; cashbookId = original.cashbookId; partyId = original.partyId; placeOfSupply = original.placeOfSupply
            roundOff = original.roundOff; due = issue
            val orig = snap.invoiceItems[original.id].orEmpty()
            itemised = orig.isNotEmpty()
            items = if (orig.isNotEmpty() && docType == com.cashbook.core.DocType.CREDIT_NOTE) orig.map { ItemDraft.from(it) } else listOf(ItemDraft(gstBp = orig.firstOrNull()?.gstBp ?: 1800))
            number = vm.deps?.ledger?.nextInvoiceNumber(original.cashbookId, original.kind, LocalDate.now(), docType) ?: ""
            loaded = true
            return@LaunchedEffect
        }
        if (existing != null) {
            kind = existing.kind; cashbookId = existing.cashbookId; number = existing.number; partyId = existing.partyId
            issue = existing.issueDate.toEpochDay(); due = existing.dueDate.toEpochDay(); amount = Money.toPlain(existing.amount)
            description = existing.description; notes = existing.notes
            placeOfSupply = existing.placeOfSupply; roundOff = existing.roundOff
            existing.transport.let { vehicle = it.vehicleNo; transporter = it.transporter; lrNo = it.lrNo; eway = it.ewayBillNo; showTransport = !it.isEmpty }
            snap.schedules.firstOrNull { it.templateId == id }?.let { sc ->
                frequency = sc.frequency; every = sc.interval.toString(); start = sc.startDate.toEpochDay(); dueDays = sc.dueDays
                hasEnd = sc.endDate != null; sc.endDate?.let { end = it.toEpochDay() }
            }
            val existingItems = snap.invoiceItems[id].orEmpty()
            itemised = existingItems.isNotEmpty()
            items = if (existingItems.isEmpty()) listOf(ItemDraft()) else existingItems.map { ItemDraft.from(it) }
        } else {
            placeOfSupply = snap.partyById[presetParty]?.stateCode?.ifBlank { null } ?: seller.stateCode
            val sc = currentScope(snap, s)
            cashbookId = if (s.defaultCashbookId in sc) s.defaultCashbookId else sc.firstOrNull() ?: 0
            number = vm.deps?.ledger?.nextInvoiceNumber(cashbookId, kind, LocalDate.now(),
                if (isQuote) com.cashbook.core.DocType.QUOTATION else if (isChallan) com.cashbook.core.DocType.CHALLAN
                else if (isTemplate) com.cashbook.core.DocType.TEMPLATE else com.cashbook.core.DocType.INVOICE) ?: ""
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
    val errDates = !isNote && !isTemplate && due < issue
    val errEway = !com.cashbook.core.Transport.isValidEwayBill(eway)
    val everyN = every.toIntOrNull()
    val errSchedule = isTemplate && (everyN == null || everyN !in 1..99 || (hasEnd && end < start))
    val msgSaved = stringResource(R.string.recurring_saved)
    val msgDuplicate = stringResource(R.string.inv_err_duplicate)
    val msgBelowPaid = stringResource(R.string.inv_err_below_paid)
    val msgNoteTooLarge = stringResource(R.string.note_err_too_large)

    val screenTitle = when {
        isChallan -> stringResource(if (id == 0L) R.string.new_challan else R.string.edit_challan)
        isTemplate -> stringResource(if (id == 0L) R.string.new_recurring_invoice else R.string.edit_recurring_invoice)
        isQuote && kind == InvoiceKind.PURCHASE -> stringResource(if (id == 0L) R.string.new_purchase_order else R.string.edit_purchase_order)
        isQuote -> stringResource(if (id == 0L) R.string.new_quotation else R.string.edit_quotation)
        isNote -> stringResource(if (id == 0L) (if (noteType == com.cashbook.core.DocType.CREDIT_NOTE) R.string.new_credit_note else R.string.new_debit_note) else R.string.edit_note)
        id == 0L -> stringResource(if (kind == InvoiceKind.SALE) R.string.new_invoice else R.string.new_bill)
        else -> stringResource(R.string.edit_invoice)
    }
    AppScaffold(title = screenTitle,
        onBack = { nav.popBackStack() }, snackbar = snackbar) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (isNote && original != null) InfoBanner(stringResource(if (noteType == com.cashbook.core.DocType.CREDIT_NOTE) R.string.credit_note_explain else R.string.debit_note_explain,
                original.number, snap.names.party(original.partyId)), icon = Icons.Filled.Info)
            if (id == 0L && !isNote && !isQuote && !isChallan && !isTemplate) SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                InvoiceKind.entries.forEachIndexed { i, k ->
                    SegmentedButton(kind == k, onClick = {
                        if (kind != k) { kind = k; scope.launch { number = vm.deps?.ledger?.nextInvoiceNumber(cashbookId, k, LocalDate.ofEpochDay(issue)) ?: number } }
                    }, shape = SegmentedButtonDefaults.itemShape(i, 2)) { Text(kindLabel(k), maxLines = 1) }
                }
            }
            if (!isNote) Text(stringResource(if (isTemplate) R.string.recurring_explain else if (isChallan) R.string.challan_explain else if (isQuote) (if (kind == InvoiceKind.SALE) R.string.quote_explain else R.string.po_explain) else if (kind == InvoiceKind.SALE) R.string.inv_sale_explain else R.string.inv_purchase_explain), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            val cbs = snap.cashbooks.filter { !it.archived || it.id == cashbookId }
            if (cbs.size > 1 && id == 0L && !isNote) DropdownField(stringResource(R.string.cashbook), cbs.map { it.id }, cashbookId.takeIf { it != 0L },
                labelOf = { snap.cashbookById[it]?.name ?: "" }, onSelect = { cashbookId = it })
            PickerField(stringResource(if (kind == InvoiceKind.SALE) R.string.inv_customer else R.string.inv_supplier), snap.names.party(partyId.takeIf { it > 0 }),
                { if (!isNote) partyPicker = true }, isError = showErrors && errParty, supporting = if (showErrors && errParty) stringResource(R.string.inv_err_party) else null)
            if (!isTemplate) OutlinedTextField(number, { number = it }, label = { Text(stringResource(if (isChallan) R.string.challan_number else if (isQuote) (if (kind == InvoiceKind.SALE) R.string.quote_number else R.string.po_number) else R.string.inv_number)) }, singleLine = true, isError = showErrors && number.isBlank(),
                modifier = Modifier.fillMaxWidth())
            // a challan always lists the goods sent
            if (!isChallan) com.cashbook.app.ui.components.SwitchRow(stringResource(R.string.itemised_gst), itemised, { itemised = it }, stringResource(R.string.itemised_gst_desc))
            if (!itemised) MoneyField(amount, { amount = it }, stringResource(R.string.inv_amount),
                error = if (showErrors && errAmount) (if (paid > 0) stringResource(R.string.inv_err_below_paid) else stringResource(R.string.err_amount_invalid)) else null)
            if (isTemplate) {
                // ----- schedule -----
                Text(stringResource(R.string.repeats), style = MaterialTheme.typography.labelLarge)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(com.cashbook.core.Frequency.WEEKLY, com.cashbook.core.Frequency.MONTHLY, com.cashbook.core.Frequency.QUARTERLY, com.cashbook.core.Frequency.YEARLY).forEach { fr ->
                        FilterChip(frequency == fr, { frequency = fr }, { Text(com.cashbook.app.ui.recurring.frequencyLabel(fr)) })
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(every, { every = it.filter { c -> c.isDigit() }.take(2) }, label = { Text(stringResource(R.string.every_n)) }, singleLine = true,
                        isError = everyN == null || everyN < 1, modifier = Modifier.weight(0.6f),
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number))
                    DateField(stringResource(R.string.first_invoice_on), LocalDate.ofEpochDay(start), { start = it.toEpochDay() }, Modifier.weight(1.4f))
                }
                everyN?.takeIf { it >= 1 }?.let { n -> Text(com.cashbook.app.ui.recurring.frequencyLabel(frequency, n), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant) }
                com.cashbook.app.ui.components.SwitchRow(stringResource(R.string.ends_on), hasEnd, { hasEnd = it })
                if (hasEnd) DateField(stringResource(R.string.end_date), LocalDate.ofEpochDay(end), { end = it.toEpochDay() }, isError = end < start,
                    supporting = if (end < start) stringResource(R.string.inv_err_due_before) else null)
                Text(stringResource(R.string.payment_terms), style = MaterialTheme.typography.labelLarge)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(0, 7, 15, 30).forEach { d -> FilterChip(dueDays == d, { dueDays = d }, { Text(if (d == 0) stringResource(R.string.inv_on_receipt) else stringResource(R.string.inv_net_days, d)) }) }
                }
                if (start < LocalDate.now().toEpochDay() && schedule == null) Text(stringResource(R.string.recurring_backfill_note), style = MaterialTheme.typography.bodySmall,
                    color = LocalFinanceColors.current.warning)
            }
            if (!isTemplate) DateField(stringResource(if (isNote) R.string.note_date else if (isChallan) R.string.challan_date else if (isQuote) (if (kind == InvoiceKind.SALE) R.string.quote_date else R.string.po_date) else R.string.inv_issue_date), LocalDate.ofEpochDay(issue), { issue = it.toEpochDay(); if (isNote) due = issue })
            if (!isNote && !isChallan && !isTemplate) DateField(stringResource(if (isQuote) (if (kind == InvoiceKind.SALE) R.string.valid_until else R.string.po_expected_by) else R.string.inv_due_date), LocalDate.ofEpochDay(due), { due = it.toEpochDay() }, isError = errDates,
                supporting = if (errDates) stringResource(R.string.inv_err_due_before) else null)
            if (!isNote && !isChallan && !isTemplate) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                (if (isQuote) listOf(7, 15, 30, 60) else listOf(0, 7, 15, 30, 45, 60)).forEach { d ->
                    FilterChip(due - issue == d.toLong(), { due = issue + d }, { Text(if (d == 0) stringResource(R.string.inv_on_receipt) else stringResource(R.string.inv_net_days, d)) })
                }
            }
            if (itemised) {
                DropdownField(stringResource(R.string.place_of_supply), listOf("") + com.cashbook.core.Gst.STATES.keys, placeOfSupply,
                    labelOf = { if (it.isEmpty()) stringResource(R.string.not_set) else com.cashbook.core.Gst.stateLabel(it) }, onSelect = { placeOfSupply = it },
                    supporting = if (seller.stateCode.isBlank()) stringResource(R.string.set_business_state) else null, modifier = Modifier.fillMaxWidth())
                InvoiceItemsEditor(items, { items = it }, showErrors, totals, snap.catalog, purchase = kind == InvoiceKind.PURCHASE, onHand = { snap.onHand(it) },
                    stockOut = (kind == InvoiceKind.SALE && (!isNote)) || (kind == InvoiceKind.PURCHASE && isNote && noteType == com.cashbook.core.DocType.CREDIT_NOTE))
                com.cashbook.app.ui.components.SwitchRow(stringResource(R.string.round_off_total), roundOff, { roundOff = it })
                totals?.let { TotalsCard(it) }
                if (showErrors && errAmount && paid > 0 && itemsValid) Text(stringResource(R.string.inv_err_below_paid), color = MaterialTheme.colorScheme.error)
            }
            if (kind == InvoiceKind.SALE && !isNote && !isQuote && !isTemplate) {
                // ----- transport (optional) -----
                com.cashbook.app.ui.components.SwitchRow(stringResource(R.string.transport_details), showTransport, { showTransport = it }, stringResource(R.string.transport_details_desc))
                if (showTransport) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(vehicle, { vehicle = it.uppercase().take(15) }, label = { Text(stringResource(R.string.vehicle_no)) }, singleLine = true, modifier = Modifier.weight(1f))
                        OutlinedTextField(lrNo, { lrNo = it.take(30) }, label = { Text(stringResource(R.string.lr_no)) }, singleLine = true, modifier = Modifier.weight(1f))
                    }
                    OutlinedTextField(transporter, { transporter = it.take(60) }, label = { Text(stringResource(R.string.transporter)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(eway, { eway = it.filter { c -> c.isDigit() || c == ' ' }.take(14) }, label = { Text(stringResource(R.string.eway_bill_no)) }, singleLine = true,
                        isError = errEway, supportingText = if (errEway) ({ Text(stringResource(R.string.eway_invalid)) }) else null, modifier = Modifier.fillMaxWidth(),
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number))
                }
            }
            OutlinedTextField(description, { description = it }, label = { Text(stringResource(if (isNote) R.string.note_reason else R.string.description)) },
                modifier = Modifier.fillMaxWidth(), maxLines = 3, supportingText = if (isTemplate) ({ Text(stringResource(R.string.recurring_placeholders)) }) else null)
            OutlinedTextField(notes, { notes = it }, label = { Text(stringResource(R.string.notes)) }, modifier = Modifier.fillMaxWidth(), maxLines = 4)
            InfoBanner(stringResource(if (isTemplate) R.string.recurring_not_cash_note else if (isChallan) R.string.challan_not_cash_note else if (isQuote) (if (kind == InvoiceKind.SALE) R.string.quote_not_cash_note else R.string.po_not_cash_note) else R.string.inv_not_cash_note), icon = Icons.Filled.Info)
            Button(onClick = {
                showErrors = true
                if (errAmount || errParty || errDates || errEway || errSchedule || (number.isBlank() && !isTemplate) || cashbookId == 0L) return@Button
                val inv = InvoiceInfo(id, cashbookId, kind, number, partyId, LocalDate.ofEpochDay(issue), LocalDate.ofEpochDay(due),
                    if (itemised) totals!!.grandTotal else (parsed as Money.ParseResult.Ok).paise, description, notes,
                    placeOfSupply = placeOfSupply, roundOff = roundOff,
                    docType = if (isNote) noteType else if (isQuote) com.cashbook.core.DocType.QUOTATION else if (isChallan) com.cashbook.core.DocType.CHALLAN
                        else if (isTemplate) com.cashbook.core.DocType.TEMPLATE else com.cashbook.core.DocType.INVOICE, refInvoiceId = if (isNote) original?.id else null,
                    transport = if (showTransport) com.cashbook.core.Transport(vehicle, transporter, lrNo, eway) else com.cashbook.core.Transport())
                val lineItems = if (itemised) items.map { it.toItem() } else emptyList()
                vm.run(onError = { e ->
                    val m = when ((e as? LedgerRepository.InvoiceException)?.reason) {
                        LedgerRepository.InvoiceException.Reason.DUPLICATE_NUMBER -> msgDuplicate
                        LedgerRepository.InvoiceException.Reason.BELOW_PAID -> msgBelowPaid
                        LedgerRepository.InvoiceException.Reason.NOTE_TOO_LARGE -> msgNoteTooLarge
                        else -> e.localizedMessage ?: ""
                    }
                    scope.launch { snackbar.showSnackbar(m) }
                }) {
                    if (isTemplate) {
                        ledger.saveSchedule(inv, lineItems, seller.stateCode, com.cashbook.core.InvoiceSchedule(0, id, frequency, everyN!!, LocalDate.ofEpochDay(start),
                            if (hasEnd) LocalDate.ofEpochDay(end) else null, dueDays = dueDays))
                        val made = ledger.postDueInvoiceSchedules(dates = s.dateFormat)
                        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { nav.popBackStack(); if (made > 0) vm.toast(msgSaved.format(made)) }
                        return@run
                    }
                    val newId = ledger.saveInvoice(inv, lineItems, seller.stateCode)
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) {
                        nav.popBackStack()
                        if (id == 0L) nav.navigate(Routes.invoice(newId))
                    }
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
            if (isTemplate && schedule != null) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { vm.run { ledger.setScheduleActive(schedule.id, !schedule.active) } }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(if (schedule.active) R.string.pause else R.string.resume), maxLines = 1) }
                OutlinedButton(onClick = { confirmDeleteSchedule = true }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            }
        }
    }
    if (confirmDeleteSchedule && schedule != null) ConfirmDialog(stringResource(R.string.delete_recurring_title), stringResource(R.string.delete_recurring_inv_text),
        stringResource(R.string.delete), onConfirm = { vm.run { ledger.deleteSchedule(schedule.id) }; nav.popBackStack() },
        onDismiss = { confirmDeleteSchedule = false }, destructive = true)
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
    snap.quotations.firstOrNull { it.id == id }?.let { QuotationDetailScreen(vm, nav, it); return }
    snap.challans.firstOrNull { it.id == id }?.let { ChallanDetailScreen(vm, nav, it); return }
    snap.templates.firstOrNull { it.id == id }?.let { InvoiceEditScreen(vm, nav, id, "SALE", 0, docType = com.cashbook.core.DocType.TEMPLATE); return }
    snap.invoices.firstOrNull { it.id == id }?.takeIf { it.docType != com.cashbook.core.DocType.INVOICE }?.let { NoteDetailScreen(vm, nav, it); return }
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val ctx = LocalContext.current
    val b = snap.invoiceBalances().firstOrNull { it.invoice.id == id }
    var applyExisting by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val hasPaymentsMsg = stringResource(R.string.inv_err_has_payments_or_notes)
    AppScaffold(title = b?.invoice?.number ?: "", onBack = { nav.popBackStack() }, actions = {
        if (b != null) {
            IconButton(onClick = { vm.allowExternalActivity(); Exporter.shareText(ctx, shareText(ctx, b, snap, f, vm.businessProfile.value.upiId), ctx.getString(R.string.share)) }) {
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
                if (b.credited > 0) AmountLine(stringResource(R.string.less_credit_notes), "−" + f.amount(b.credited))
                if (b.debited > 0) AmountLine(stringResource(R.string.add_debit_notes), "+" + f.amount(b.debited))
                if (b.credited > 0 || b.debited > 0) AmountLine(stringResource(R.string.net_amount), f.amount(b.net))
                AmountLine(stringResource(if (inv.kind == InvoiceKind.SALE) R.string.inv_received else R.string.inv_paid_amount), f.amount(b.paid), fc.income)
                if (b.refundDue > 0) AmountLine(stringResource(R.string.refund_due), f.amount(b.refundDue), fc.transfer, bold = true)
                else AmountLine(stringResource(R.string.inv_outstanding), f.amount(b.outstanding), if (b.status == InvoiceStatus.OVERDUE) fc.expense else null, bold = true)
                if (inv.description.isNotBlank()) Text(inv.description, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
                if (inv.placeOfSupply.isNotBlank()) Text("${stringResource(R.string.place_of_supply)}: ${com.cashbook.core.Gst.stateLabel(inv.placeOfSupply)}",
                    style = MaterialTheme.typography.bodySmall)
                if (inv.notes.isNotBlank()) Text(inv.notes, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                inv.scheduleId?.let { sid -> snap.schedules.firstOrNull { it.id == sid } }?.let { sc ->
                    Text(stringResource(R.string.from_recurring), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.clickable { nav.navigate(Routes.invoice(sc.templateId)) }.padding(vertical = 4.dp))
                }
                if (!inv.transport.isEmpty) Text(transportLine(inv.transport), style = MaterialTheme.typography.bodySmall)
                snap.sourcesOf(id).forEach { q ->
                    Text(stringResource(when { q.docType == com.cashbook.core.DocType.CHALLAN -> R.string.from_challan_x
                        q.kind == InvoiceKind.SALE -> R.string.from_quotation_x; else -> R.string.from_po_x }, q.number), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.clickable { nav.navigate(Routes.invoice(q.id)) }.padding(vertical = 4.dp))
                }
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
            if (inv.kind == InvoiceKind.SALE && !inv.cancelled && b.outstanding > 0 && com.cashbook.core.Upi.isValidVpa(seller.upiId))
                UpiQrCard(com.cashbook.core.Upi.payUri(seller.upiId, seller.name, b.outstanding, inv.number), seller.upiId, b.outstanding)
            if (inv.kind == InvoiceKind.SALE && !inv.cancelled && b.outstanding > 0) {
                val party = snap.partyById[inv.partyId]
                val wa = party?.mobile?.let { com.cashbook.core.Reminders.whatsappNumber(it) }
                OutlinedButton(onClick = { sendReminder(ctx, vm, party?.mobile ?: "", reminderText(ctx, b, snap, f, seller)) }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Share, null); Text(" " + stringResource(if (wa != null) R.string.whatsapp_reminder else R.string.send_reminder), maxLines = 1) }
            }
            if (b.outstanding > 0) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { nav.navigate(Routes.recordPayment(id)) }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(if (inv.kind == InvoiceKind.SALE) R.string.inv_record_receipt else R.string.inv_record_payment)) }
                OutlinedButton(onClick = { applyExisting = true }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.inv_apply_existing)) }
            }
            if (b.refundDue > 0) Button(onClick = { nav.navigate(Routes.recordRefund(id)) }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(if (inv.kind == InvoiceKind.SALE) R.string.record_refund_customer else R.string.record_refund_supplier)) }
            val noteDocs = snap.notesOf(id)
            SectionCard(stringResource(R.string.credit_debit_notes)) {
                if (noteDocs.isEmpty()) Text(stringResource(R.string.no_notes), style = MaterialTheme.typography.bodySmall)
                noteDocs.forEach { n ->
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(n.id)) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("${docTypeLabel(n.docType, n.kind)} ${n.number}", style = MaterialTheme.typography.bodyMedium)
                            Text(f.date(n.issueDate) + (if (n.description.isNotBlank()) " · ${n.description}" else ""), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Text((if (n.docType == com.cashbook.core.DocType.CREDIT_NOTE) "−" else "+") + f.amount(n.amount), style = MaterialTheme.typography.titleSmall)
                    }
                    HorizontalDivider()
                }
                if (!inv.cancelled) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 6.dp)) {
                    OutlinedButton(onClick = { nav.navigate(Routes.noteEdit(0, "CREDIT_NOTE", id)) }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.credit_note), maxLines = 1) }
                    OutlinedButton(onClick = { nav.navigate(Routes.noteEdit(0, "DEBIT_NOTE", id)) }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.debit_note), maxLines = 1) }
                }
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
                OutlinedButton(onClick = { if (payments.isEmpty() && snap.notesOf(id).isEmpty()) confirmDelete = true else vm.toast(hasPaymentsMsg) }, modifier = Modifier.weight(1f)) {
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
fun RecordPaymentScreen(vm: AppViewModel, nav: NavHostController, invoiceId: Long, refund: Boolean = false) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val b = snap.invoiceBalances().firstOrNull { it.invoice.id == invoiceId } ?: return
    val inv = b.invoice
    // a payment is income for a sale / expense for a bill; a refund is the opposite
    val catKind = if ((inv.kind == InvoiceKind.SALE) != refund) CategoryKind.INCOME else CategoryKind.EXPENSE
    val entryType = if (catKind == CategoryKind.INCOME) com.cashbook.core.TxnType.INCOME else com.cashbook.core.TxnType.EXPENSE
    val limit = if (refund) b.refundDue else b.outstanding
    val accounts = snap.accounts.filter { it.cashbookId == inv.cashbookId && !it.archived }
    // default category: the one last used with this party for this type…
    val lastCat = snap.txns.filter { it.partyId == inv.partyId && it.type == entryType }.maxByOrNull { it.date }?.categoryId
    val cats = snap.categoriesOf(catKind).filter { !it.archived }
    // refunds: prefer a category named like "Refund…", else the last ("Other …") one
    val refundCat = if (refund) (cats.firstOrNull { it.name.contains("refund", true) || it.name.contains("रिफंड") } ?: cats.lastOrNull { it.parentId == null })?.id else null
    var amount by rememberSaveable { mutableStateOf(Money.toPlain(limit)) }
    var accountId by rememberSaveable { mutableStateOf(accounts.firstOrNull { it.type != com.cashbook.core.AccountType.CASH }?.id ?: accounts.firstOrNull()?.id ?: 0L) }
    // otherwise the category most used for this kind of entry in the cashbook
    val mostUsed = snap.txns.filter { it.cashbookId == inv.cashbookId && it.type == entryType && it.categoryId != null }
        .groupingBy { it.categoryId!! }.eachCount().maxByOrNull { it.value }?.key
    var categoryId by rememberSaveable { mutableStateOf(refundCat ?: lastCat ?: mostUsed ?: cats.firstOrNull()?.id ?: 0L) }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var mode by rememberSaveable { mutableStateOf(PaymentMode.UPI) }
    var reference by rememberSaveable { mutableStateOf("") }
    val parsed = Money.parse(amount)
    val tooMuch = parsed is Money.ParseResult.Ok && parsed.paise > limit
    val ok = parsed is Money.ParseResult.Ok && !tooMuch && accountId != 0L && categoryId != 0L
    val label = stringResource(when {
        refund && inv.kind == InvoiceKind.SALE -> R.string.refund_to_customer_for
        refund -> R.string.refund_from_supplier_for
        inv.kind == InvoiceKind.SALE -> R.string.inv_payment_for
        else -> R.string.inv_payment_of }, inv.number)
    val f = LocalUiFormat.current
    AppScaffold(title = stringResource(when {
        refund -> if (inv.kind == InvoiceKind.SALE) R.string.record_refund_customer else R.string.record_refund_supplier
        inv.kind == InvoiceKind.SALE -> R.string.inv_record_receipt
        else -> R.string.inv_record_payment }), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            InfoBanner("${inv.number} · ${snap.names.party(inv.partyId)} · " +
                (if (refund) "${stringResource(R.string.refund_due)} ${f.amount(b.refundDue)}" else "${stringResource(R.string.inv_outstanding)} ${f.amount(b.outstanding)}"))
            MoneyField(amount, { amount = it }, stringResource(R.string.amount_required),
                error = when { tooMuch -> stringResource(if (refund) R.string.err_more_than_refund_due else R.string.inv_err_more_than_outstanding); parsed is Money.ParseResult.Error && amount.isNotEmpty() -> stringResource(R.string.err_amount_invalid); else -> null })
            DropdownField(stringResource(R.string.account), accounts.map { it.id }, accountId.takeIf { it != 0L }, labelOf = { snap.names.account(it) }, onSelect = { accountId = it })
            DropdownField(stringResource(R.string.category), cats.map { it.id }, categoryId.takeIf { it != 0L }, labelOf = { snap.categoryName(it) }, onSelect = { categoryId = it })
            DropdownField(stringResource(R.string.payment_mode), PaymentMode.entries, mode, labelOf = { paymentModeLabel(it) }, onSelect = { mode = it })
            DateField(stringResource(R.string.date), LocalDate.ofEpochDay(date), { date = it.toEpochDay() })
            OutlinedTextField(reference, { reference = it }, label = { Text(stringResource(R.string.reference_number)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button(enabled = ok, onClick = {
                val paise = (parsed as Money.ParseResult.Ok).paise
                vm.run {
                    if (refund) ledger.recordRefund(inv.id, accountId, categoryId, paise, LocalDate.ofEpochDay(date), mode, reference, label)
                    else ledger.recordPayment(inv.id, accountId, categoryId, paise, LocalDate.ofEpochDay(date), mode, reference, label)
                }
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

/** "Vehicle MH12AB1234 · VRL Logistics · LR 5521 · E-way bill 3810 0123 4567" (only the parts filled in). */
@Composable
fun transportLine(t: com.cashbook.core.Transport): String = listOfNotNull(
    t.vehicleNo.takeIf { it.isNotBlank() }?.let { stringResource(R.string.vehicle_no) + " " + it },
    t.transporter.takeIf { it.isNotBlank() },
    t.lrNo.takeIf { it.isNotBlank() }?.let { stringResource(R.string.lr_no) + " " + it },
    t.ewayBillNo.takeIf { it.isNotBlank() }?.let { stringResource(R.string.eway_bill_no) + " " + it.chunked(4).joinToString(" ") },
).joinToString(" · ")

/** Polite payment reminder for a sales invoice: amount, dates, balance, UPI ID and the business name. */
fun reminderText(ctx: android.content.Context, b: InvoiceBalance, snap: Snapshot, f: com.cashbook.app.ui.components.UiFormat,
                 seller: com.cashbook.core.backup.BusinessProfileDto, today: LocalDate = LocalDate.now()): String {
    val inv = b.invoice
    val overdue = java.time.temporal.ChronoUnit.DAYS.between(inv.dueDate, today)
    return buildString {
        appendLine(ctx.getString(R.string.reminder_greeting, snap.names.party(inv.partyId)))
        appendLine()
        appendLine(if (overdue > 0) ctx.getString(R.string.reminder_overdue, inv.number, f.date(inv.issueDate), f.amount(inv.amount), f.date(inv.dueDate), overdue.toInt())
            else ctx.getString(R.string.reminder_due, inv.number, f.date(inv.issueDate), f.amount(inv.amount), f.date(inv.dueDate)))
        appendLine(ctx.getString(R.string.reminder_balance, f.amount(b.outstanding)))
        if (com.cashbook.core.Upi.isValidVpa(seller.upiId)) appendLine(ctx.getString(R.string.pay_by_upi_x, seller.upiId.trim()))
        appendLine()
        appendLine(ctx.getString(R.string.reminder_ignore))
        append(ctx.getString(R.string.reminder_thanks))
        if (seller.name.isNotBlank()) append("\n" + seller.name)
    }.trim()
}

private fun shareText(ctx: android.content.Context, b: InvoiceBalance, snap: Snapshot, f: com.cashbook.app.ui.components.UiFormat, upiId: String = ""): String {
    val inv = b.invoice
    return buildString {
        appendLine(ctx.getString(if (inv.kind == InvoiceKind.SALE) R.string.inv_kind_sale else R.string.inv_kind_purchase) + " " + inv.number)
        appendLine(snap.names.party(inv.partyId))
        appendLine("${ctx.getString(R.string.inv_issue_date)}: ${f.date(inv.issueDate)}")
        appendLine("${ctx.getString(R.string.inv_due_date)}: ${f.date(inv.dueDate)}")
        appendLine("${ctx.getString(R.string.inv_amount)}: ${f.amount(inv.amount)}")
        if (b.paid > 0) appendLine("${ctx.getString(R.string.inv_paid_amount)}: ${f.amount(b.paid)}")
        appendLine("${ctx.getString(R.string.inv_outstanding)}: ${f.amount(b.outstanding)}")
        if (inv.kind == InvoiceKind.SALE && b.outstanding > 0 && com.cashbook.core.Upi.isValidVpa(upiId)) appendLine(ctx.getString(R.string.pay_by_upi_x, upiId.trim()))
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
    c.getString(R.string.pdf_credit_note), c.getString(R.string.pdf_debit_note), c.getString(R.string.pdf_against_invoice),
    c.getString(R.string.pdf_note_no), c.getString(R.string.note_date),
    c.getString(R.string.pdf_quotation), c.getString(R.string.pdf_quotation_no), c.getString(R.string.quote_date), c.getString(R.string.valid_until),
    c.getString(R.string.pdf_scan_to_pay),
    c.getString(R.string.pdf_purchase_order), c.getString(R.string.pdf_po_no), c.getString(R.string.po_date), c.getString(R.string.po_expected_by),
    c.getString(R.string.pdf_supplier),
    c.getString(R.string.pdf_delivery_challan), c.getString(R.string.pdf_challan_no), c.getString(R.string.challan_date), c.getString(R.string.pdf_deliver_to),
    c.getString(R.string.vehicle_no), c.getString(R.string.transporter), c.getString(R.string.lr_no), c.getString(R.string.eway_bill_no),
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
    val store = vm.deps?.attachments
    val ref = b.invoice.refInvoiceId?.let { r -> snap.invoices.firstOrNull { it.id == r } }?.let { com.cashbook.app.export.InvoicePdfWriter.Reference(it.number, it.issueDate) }
    fun write(out: java.io.OutputStream) = com.cashbook.app.export.InvoicePdfWriter(f.money, settings?.dateFormat ?: com.cashbook.core.DateFormatOption.DD_MM_YYYY,
        invoicePdfStrings(ctx)).write(b, snap.invoiceItems[b.invoice.id].orEmpty(), seller, snap.partyById[b.invoice.partyId], out,
        com.cashbook.app.export.InvoicePdfWriter.Branding(store?.brandBitmap(com.cashbook.app.data.AttachmentStore.Brand.LOGO),
            store?.brandBitmap(com.cashbook.app.data.AttachmentStore.Brand.SIGNATURE)), ref)
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


/** Detail of a credit or debit note: what it adjusts, its items and totals, and its PDF. */
@Composable
fun NoteDetailScreen(vm: AppViewModel, nav: NavHostController, note: InvoiceInfo) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    var confirmDelete by remember { mutableStateOf(false) }
    val original = note.refInvoiceId?.let { r -> snap.invoices.firstOrNull { it.id == r } }
    AppScaffold(title = note.number, onBack = { nav.popBackStack() }, actions = {
        IconButton(onClick = { nav.navigate(Routes.noteEdit(note.id, note.docType.name, note.refInvoiceId ?: 0)) }) { Icon(Icons.Filled.Edit, stringResource(R.string.edit)) }
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard {
                Text(docTypeLabel(note.docType, note.kind), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                Text(snap.names.party(note.partyId), style = MaterialTheme.typography.titleLarge)
                Text("${stringResource(R.string.note_date)}: ${f.date(note.issueDate)}", style = MaterialTheme.typography.bodySmall)
                original?.let { o ->
                    Text(stringResource(R.string.against_x, o.number, f.date(o.issueDate)), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.primary, modifier = Modifier.clickable { nav.navigate(Routes.invoice(o.id)) }.padding(vertical = 4.dp))
                }
                AmountLine(stringResource(R.string.amount), (if (note.docType == com.cashbook.core.DocType.CREDIT_NOTE) "−" else "+") + f.amount(note.amount), bold = true)
                if (note.description.isNotBlank()) Text(note.description, style = MaterialTheme.typography.bodyMedium)
            }
            val lineItems = snap.invoiceItems[note.id].orEmpty()
            if (lineItems.isNotEmpty()) TotalsCard(com.cashbook.core.GstCalc.totals(lineItems, com.cashbook.core.GstCalc.isInterState(seller.stateCode, note.placeOfSupply), note.roundOff))
            InfoBanner(stringResource(if (note.docType == com.cashbook.core.DocType.CREDIT_NOTE) R.string.credit_note_effect else R.string.debit_note_effect), icon = Icons.Filled.Info)
            if (note.kind == InvoiceKind.SALE) InvoicePdfButtons(vm, snap, InvoiceBalance(note, 0, InvoiceStatus.OPEN, 0))
            OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
        }
    }
    if (confirmDelete) ConfirmDialog(stringResource(R.string.delete_note_title), stringResource(R.string.delete_note_text), stringResource(R.string.delete),
        onConfirm = { vm.run { ledger.deleteInvoice(note.id) }; nav.popBackStack() }, onDismiss = { confirmDelete = false }, destructive = true)
}
