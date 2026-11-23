package com.cashbook.app.ui.invoices

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.data.Snapshot
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.ConfirmDialog
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.GstCalc
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.Qr
import com.cashbook.core.QuoteStatus
import com.cashbook.core.Quotations
import java.time.LocalDate

@Composable
fun quoteStatusColor(s: QuoteStatus): Color = LocalFinanceColors.current.let {
    when (s) { QuoteStatus.OPEN -> MaterialTheme.colorScheme.primary; QuoteStatus.EXPIRED -> it.warning; QuoteStatus.CONVERTED -> it.income
        QuoteStatus.DECLINED -> MaterialTheme.colorScheme.outline }
}

/** Purchase orders read Open / Overdue (expected date passed) / Billed / Cancelled. */
@Composable
fun quoteStatusLabel(s: QuoteStatus, kind: InvoiceKind = InvoiceKind.SALE) = stringResource(if (kind == InvoiceKind.SALE) when (s) {
    QuoteStatus.OPEN -> R.string.quote_open; QuoteStatus.EXPIRED -> R.string.quote_expired
    QuoteStatus.CONVERTED -> R.string.quote_converted; QuoteStatus.DECLINED -> R.string.quote_declined } else when (s) {
    QuoteStatus.OPEN -> R.string.quote_open; QuoteStatus.EXPIRED -> R.string.overdue
    QuoteStatus.CONVERTED -> R.string.po_billed; QuoteStatus.DECLINED -> R.string.inv_cancelled })

@Composable
fun QuoteStatusChip(s: QuoteStatus, kind: InvoiceKind = InvoiceKind.SALE) {
    val c = quoteStatusColor(s)
    Text(quoteStatusLabel(s, kind), style = MaterialTheme.typography.labelSmall, color = c,
        modifier = Modifier.background(c.copy(alpha = 0.12f), RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp))
}

/** Quotations & orders tab: sales quotations or purchase orders; open ones first (by date), then the rest, newest first. */
@Composable
fun QuotationList(snap: Snapshot, nav: NavHostController, cashbookIds: Set<Long>, kind: InvoiceKind, onKind: (InvoiceKind) -> Unit) {
    val f = LocalUiFormat.current
    val today = LocalDate.now()
    val sale = kind == InvoiceKind.SALE
    val quotes = snap.quotations.filter { it.cashbookId in cashbookIds && it.kind == kind }.map { it to Quotations.status(it, today) }
        .sortedWith(compareBy({ it.second != QuoteStatus.OPEN }, { if (it.second == QuoteStatus.OPEN) it.first.dueDate.toEpochDay() else -it.first.issueDate.toEpochDay() }))
    val open = quotes.filter { it.second == QuoteStatus.OPEN }
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    FilterChip(sale, { onKind(InvoiceKind.SALE) }, { Text(stringResource(R.string.quotations)) })
                    FilterChip(!sale, { onKind(InvoiceKind.PURCHASE) }, { Text(stringResource(R.string.purchase_orders)) })
                }
                SectionCard {
                    Row {
                        Column(Modifier.weight(1f)) {
                            Text(stringResource(if (sale) R.string.open_quotations else R.string.open_purchase_orders), style = MaterialTheme.typography.labelLarge)
                            Text(f.amount(open.sumOf { it.first.amount }), style = MaterialTheme.typography.titleLarge)
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(quoteStatusLabel(QuoteStatus.CONVERTED, kind), style = MaterialTheme.typography.labelLarge)
                            Text(quotes.count { it.second == QuoteStatus.CONVERTED }.toString() + " / " + quotes.size, style = MaterialTheme.typography.titleLarge)
                        }
                    }
                }
                InfoBanner(stringResource(if (sale) R.string.quotes_intro else R.string.po_intro), icon = Icons.Filled.Info)
            }
        }
        if (quotes.isEmpty()) item { EmptyState(Icons.Filled.Description, stringResource(if (sale) R.string.no_quotations else R.string.no_purchase_orders)) }
        items(quotes, key = { it.first.id }) { (q, st) ->
            Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(q.id)) }.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(snap.names.party(q.partyId), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("${q.number} · ${stringResource(if (sale) R.string.valid_until_x else R.string.expected_by_x, f.date(q.dueDate))}", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(2.dp)); QuoteStatusChip(st, kind)
                }
                Text(f.amount(q.amount), style = MaterialTheme.typography.titleSmall)
            }
            HorizontalDivider()
        }
        item { Box(Modifier.padding(40.dp)) }
    }
}

/** A quotation: items and totals, PDF, convert to invoice, decline / reopen, delete. */
@Composable
fun QuotationDetailScreen(vm: AppViewModel, nav: NavHostController, q: InvoiceInfo) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    val ctx = LocalContext.current
    var confirmDelete by remember { mutableStateOf(false) }
    val status = Quotations.status(q, LocalDate.now())
    val converted = q.convertedInvoiceId?.let { c -> snap.invoices.firstOrNull { it.id == c } }
    val msgDeclined = stringResource(R.string.quote_err_declined)
    val sale = q.kind == InvoiceKind.SALE
    val docLabel = stringResource(if (sale) R.string.quotation else R.string.purchase_order)
    val dateLabel = stringResource(if (sale) R.string.quote_date else R.string.po_date)
    val untilLabel = stringResource(if (sale) R.string.valid_until else R.string.po_expected_by)
    AppScaffold(title = q.number, onBack = { nav.popBackStack() }, actions = {
        IconButton(onClick = {
            vm.allowExternalActivity()
            Exporter.shareText(ctx, buildString {
                appendLine("$docLabel ${q.number}")
                appendLine(snap.names.party(q.partyId))
                appendLine("$dateLabel: ${f.date(q.issueDate)}")
                appendLine("$untilLabel: ${f.date(q.dueDate)}")
                appendLine("${ctx.getString(R.string.amount)}: ${f.amount(q.amount)}")
                if (q.description.isNotBlank()) appendLine(q.description)
            }.trim(), ctx.getString(R.string.share))
        }) { Icon(Icons.Filled.Share, stringResource(R.string.share)) }
        if (converted == null) IconButton(onClick = { nav.navigate(Routes.quoteEdit(q.id, q.kind.name)) }) { Icon(Icons.Filled.Edit, stringResource(R.string.edit)) }
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(docLabel, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                        Text(snap.names.party(q.partyId), style = MaterialTheme.typography.titleLarge)
                        Text("$dateLabel: ${f.date(q.issueDate)} · $untilLabel ${f.date(q.dueDate)}", style = MaterialTheme.typography.bodySmall)
                    }
                    QuoteStatusChip(status, q.kind)
                }
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
                Row(Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.amount), Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
                    Text(f.amount(q.amount), style = MaterialTheme.typography.titleMedium)
                }
                if (q.description.isNotBlank()) Text(q.description, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
                if (q.placeOfSupply.isNotBlank()) Text("${stringResource(R.string.place_of_supply)}: ${com.cashbook.core.Gst.stateLabel(q.placeOfSupply)}",
                    style = MaterialTheme.typography.bodySmall)
                if (q.notes.isNotBlank()) Text(q.notes, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            val lineItems = snap.invoiceItems[q.id].orEmpty()
            if (lineItems.isNotEmpty()) {
                val t = GstCalc.totals(lineItems, GstCalc.isInterState(seller.stateCode, q.placeOfSupply), q.roundOff)
                SectionCard(stringResource(R.string.items)) {
                    t.lines.forEachIndexed { i, l ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text("${i + 1}. ${l.item.description}", style = MaterialTheme.typography.bodyMedium)
                                Text("${com.cashbook.core.Gst.formatQuantity(l.item.quantityMilli)} ${l.item.unit} × ${f.amount(l.item.rate)} · GST ${com.cashbook.core.Gst.rateLabel(l.item.gstBp)}",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(f.amount(l.total), style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
                TotalsCard(t)
            }
            InvoicePdfButtons(vm, snap, InvoiceBalance(q, 0, InvoiceStatus.OPEN, 0))
            if (converted != null) {
                SectionCard {
                    Text(stringResource(if (sale) R.string.converted_to_x else R.string.converted_to_bill_x, converted.number), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(converted.id)) }.padding(vertical = 4.dp))
                    Text(stringResource(if (sale) R.string.converted_explain else R.string.converted_bill_explain), style = MaterialTheme.typography.bodySmall)
                }
            } else {
                InfoBanner(stringResource(if (sale) R.string.quote_not_cash_note else R.string.po_not_cash_note), icon = Icons.Filled.Info)
                if (!q.cancelled) Button(onClick = {
                    vm.run(onError = { e ->
                        vm.toast(if ((e as? LedgerRepository.InvoiceException)?.reason == LedgerRepository.InvoiceException.Reason.DECLINED) msgDeclined else e.localizedMessage ?: "")
                    }) {
                        val invId = ledger.convertQuotation(q.id, LocalDate.now(), 15, seller.stateCode)
                        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { nav.navigate(Routes.invoice(invId)) }
                    }
                }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(if (sale) R.string.convert_to_invoice else R.string.convert_to_bill)) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.run { ledger.setInvoiceCancelled(q.id, !q.cancelled) } }, modifier = Modifier.weight(1f)) {
                        Text(stringResource(if (q.cancelled) R.string.inv_reopen else if (sale) R.string.quote_decline else R.string.po_cancel), maxLines = 1) }
                    OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.weight(1f)) {
                        Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
                }
            }
        }
    }
    if (confirmDelete) ConfirmDialog(stringResource(if (sale) R.string.delete_quote_title else R.string.delete_po_title), stringResource(R.string.delete_quote_text), stringResource(R.string.delete),
        onConfirm = { vm.run { ledger.deleteInvoice(q.id) }; nav.popBackStack() }, onDismiss = { confirmDelete = false }, destructive = true)
}

/** QR code the customer scans with any UPI app; it opens with the payee, amount and invoice number filled in. */
@Composable
fun UpiQrCard(link: String, vpa: String, amount: Long) {
    val f = LocalUiFormat.current
    val qr = remember(link) { Qr.encode(link) }
    val desc = stringResource(R.string.upi_qr_for_x, f.amount(amount), vpa)
    SectionCard(stringResource(R.string.collect_by_upi)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            // white box with a quiet zone so phones read it in dark theme too
            Box(Modifier.background(Color.White, RoundedCornerShape(8.dp)).padding(10.dp)) {
                Canvas(Modifier.size(150.dp).semantics { contentDescription = desc }) {
                    val m = size.width / qr.size
                    for (y in 0 until qr.size) for (x in 0 until qr.size) if (qr[x, y])
                        drawRect(Color.Black, Offset(x * m, y * m), Size(m + 0.5f, m + 0.5f))
                }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(f.amount(amount), style = MaterialTheme.typography.titleLarge)
                Text(vpa, style = MaterialTheme.typography.bodyMedium)
                Text(stringResource(R.string.upi_qr_explain), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
