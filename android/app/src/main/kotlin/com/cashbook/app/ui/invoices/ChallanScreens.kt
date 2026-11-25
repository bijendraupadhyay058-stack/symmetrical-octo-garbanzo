package com.cashbook.app.ui.invoices

import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
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
import com.cashbook.core.GstCalc
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.QuoteStatus
import com.cashbook.core.Quotations
import java.time.LocalDate

/** Challan status reads Not billed / Billed / Cancelled (challans don't expire). */
@Composable
fun challanStatusLabel(s: QuoteStatus) = stringResource(when (s) {
    QuoteStatus.CONVERTED -> R.string.po_billed; QuoteStatus.DECLINED -> R.string.inv_cancelled; else -> R.string.challan_not_billed })

/** Delivery challans: not-billed ones first (oldest first, the next to bill), then the rest, newest first. */
@Composable
fun ChallanList(snap: Snapshot, nav: NavHostController, cashbookIds: Set<Long>, onView: (PreDocView) -> Unit) {
    val f = LocalUiFormat.current
    val today = LocalDate.now()
    val list = snap.challans.filter { it.cashbookId in cashbookIds }.map { it to Quotations.status(it, today) }
        .sortedWith(compareBy({ it.second != QuoteStatus.OPEN }, { if (it.second == QuoteStatus.OPEN) it.first.issueDate.toEpochDay() else -it.first.issueDate.toEpochDay() }))
    val open = list.filter { it.second == QuoteStatus.OPEN }
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PreDocChips(PreDocView.CHALLANS, onView)
                SectionCard {
                    Row {
                        Column(Modifier.weight(1f)) {
                            Text(stringResource(R.string.challans_not_billed), style = MaterialTheme.typography.labelLarge)
                            Text(f.amount(open.sumOf { it.first.amount }), style = MaterialTheme.typography.titleLarge)
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(stringResource(R.string.customers), style = MaterialTheme.typography.labelLarge)
                            Text(open.map { it.first.partyId }.distinct().size.toString(), style = MaterialTheme.typography.titleLarge)
                        }
                    }
                }
                InfoBanner(stringResource(R.string.challans_intro), icon = Icons.Filled.Info)
            }
        }
        if (list.isEmpty()) item { EmptyState(Icons.Filled.Description, stringResource(R.string.no_challans)) }
        items(list, key = { it.first.id }) { (c, st) ->
            Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(c.id)) }.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(snap.names.party(c.partyId), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("${c.number} · ${f.date(c.issueDate)}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(2.dp)); QuoteStatusChipText(challanStatusLabel(st), st)
                }
                Text(f.amount(c.amount), style = MaterialTheme.typography.titleSmall)
            }
            HorizontalDivider()
        }
        item { Box(Modifier.padding(40.dp)) }
    }
}

/**
 * A delivery challan: goods sent, its PDF, and billing. Open challans of the same customer can be ticked to go into
 * one invoice (all are ticked by default — the usual monthly bill).
 */
@Composable
fun ChallanDetailScreen(vm: AppViewModel, nav: NavHostController, c: InvoiceInfo) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    val ctx = LocalContext.current
    var confirmDelete by remember { mutableStateOf(false) }
    val status = Quotations.status(c, LocalDate.now())
    val billedIn = c.convertedInvoiceId?.let { i -> snap.invoices.firstOrNull { it.id == i } }
    val openForParty = snap.challans.filter { it.partyId == c.partyId && it.cashbookId == c.cashbookId && it.convertedInvoiceId == null && !it.cancelled }
        .sortedBy { it.issueDate }
    var selected by rememberSaveable(c.id) { mutableStateOf(openForParty.map { it.id }) }
    val msgFailed = stringResource(R.string.challan_err_convert)
    AppScaffold(title = c.number, onBack = { nav.popBackStack() }, actions = {
        IconButton(onClick = {
            vm.allowExternalActivity()
            Exporter.shareText(ctx, buildString {
                appendLine(ctx.getString(R.string.delivery_challan) + " " + c.number)
                appendLine(snap.names.party(c.partyId))
                appendLine("${ctx.getString(R.string.challan_date)}: ${f.date(c.issueDate)}")
                snap.invoiceItems[c.id].orEmpty().forEach { appendLine("• ${it.description} — ${com.cashbook.core.Gst.formatQuantity(it.quantityMilli)} ${it.unit}".trimEnd()) }
            }.trim(), ctx.getString(R.string.share))
        }) { Icon(Icons.Filled.Share, stringResource(R.string.share)) }
        if (billedIn == null) IconButton(onClick = { nav.navigate(Routes.challanEdit(c.id)) }) { Icon(Icons.Filled.Edit, stringResource(R.string.edit)) }
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(stringResource(R.string.delivery_challan), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                        Text(snap.names.party(c.partyId), style = MaterialTheme.typography.titleLarge)
                        Text("${stringResource(R.string.challan_date)}: ${f.date(c.issueDate)}", style = MaterialTheme.typography.bodySmall)
                    }
                    QuoteStatusChipText(challanStatusLabel(status), status)
                }
                if (c.description.isNotBlank()) Text(c.description, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp))
                if (c.notes.isNotBlank()) Text(c.notes, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            val lineItems = snap.invoiceItems[c.id].orEmpty()
            if (lineItems.isNotEmpty()) {
                val t = GstCalc.totals(lineItems, GstCalc.isInterState(seller.stateCode, c.placeOfSupply), c.roundOff)
                SectionCard(stringResource(R.string.items)) {
                    t.lines.forEachIndexed { i, l ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text("${i + 1}. ${l.item.description}", style = MaterialTheme.typography.bodyMedium)
                                Text("${com.cashbook.core.Gst.formatQuantity(l.item.quantityMilli)} ${l.item.unit} × ${f.amount(l.item.rate)}",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(f.amount(l.total), style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
                TotalsCard(t)
            }
            InvoicePdfButtons(vm, snap, InvoiceBalance(c, 0, InvoiceStatus.OPEN, 0))
            InfoBanner(stringResource(R.string.challan_not_cash_note), icon = Icons.Filled.Info)
            if (billedIn != null) {
                SectionCard {
                    Text(stringResource(R.string.billed_in_x, billedIn.number), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.fillMaxWidth().clickable { nav.navigate(Routes.invoice(billedIn.id)) }.padding(vertical = 4.dp))
                    Text(stringResource(R.string.billed_challan_explain), style = MaterialTheme.typography.bodySmall)
                }
            } else if (!c.cancelled) {
                SectionCard(stringResource(R.string.bill_challans)) {
                    Text(stringResource(R.string.bill_challans_explain), style = MaterialTheme.typography.bodySmall)
                    openForParty.forEach { o ->
                        Row(Modifier.fillMaxWidth().toggleable(o.id in selected, role = androidx.compose.ui.semantics.Role.Checkbox) {
                            selected = if (it) selected + o.id else selected - o.id }, verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(o.id in selected, null, Modifier.padding(12.dp))
                            Text("${o.number} · ${f.date(o.issueDate)}", Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                            Text(f.amount(o.amount), style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    val chosen = openForParty.filter { it.id in selected }
                    Button(enabled = chosen.isNotEmpty(), onClick = {
                        val desc = ctx.getString(R.string.challans_desc_x, chosen.joinToString(", ") { it.number })
                        vm.run(onError = { vm.toast((it as? LedgerRepository.InvoiceException)?.let { msgFailed } ?: it.localizedMessage ?: "") }) {
                            val inv = ledger.convertChallans(chosen.map { it.id }, LocalDate.now(), 15, seller.stateCode, desc)
                            kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { nav.navigate(Routes.invoice(inv)) }
                        }
                    }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                        Text(stringResource(R.string.create_invoice_x, chosen.size, f.amount(chosen.sumOf { it.amount })), maxLines = 1)
                    }
                }
            }
            if (billedIn == null) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { vm.run { ledger.setInvoiceCancelled(c.id, !c.cancelled) } }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(if (c.cancelled) R.string.inv_reopen else R.string.challan_cancel), maxLines = 1) }
                OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.weight(1f)) {
                    Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            }
        }
    }
    if (confirmDelete) ConfirmDialog(stringResource(R.string.delete_challan_title), stringResource(R.string.delete_challan_text), stringResource(R.string.delete),
        onConfirm = { vm.run { ledger.deleteInvoice(c.id) }; nav.popBackStack() }, onDismiss = { confirmDelete = false }, destructive = true)
}
