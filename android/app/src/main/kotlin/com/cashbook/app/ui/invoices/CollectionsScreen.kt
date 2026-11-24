package com.cashbook.app.ui.invoices

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.UiFormat
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.Reminders
import com.cashbook.core.Upi
import com.cashbook.core.backup.BusinessProfileDto
import java.time.LocalDate

/** One customer's overdue sales invoices, most overdue first. */
data class OverdueCustomer(val partyId: Long, val name: String, val mobile: String, val invoices: List<InvoiceBalance>) {
    val total: Long get() = invoices.sumOf { it.outstanding }
    val oldestDays: Int get() = invoices.maxOf { it.daysOverdue }
}

/** Customers with overdue sales invoices in [cashbookIds], largest amount first. */
fun overdueCustomers(snap: com.cashbook.app.data.Snapshot, cashbookIds: Set<Long>, today: LocalDate = LocalDate.now()): List<OverdueCustomer> =
    snap.invoiceBalances(today).filter { it.invoice.kind == InvoiceKind.SALE && it.invoice.cashbookId in cashbookIds && it.status == InvoiceStatus.OVERDUE }
        .groupBy { it.invoice.partyId }
        .map { (pid, l) -> OverdueCustomer(pid, snap.names.party(pid), snap.partyById[pid]?.mobile ?: "", l.sortedByDescending { it.daysOverdue }) }
        .sortedByDescending { it.total }

/** One message listing every overdue invoice of a customer and the total. */
fun customerReminderText(ctx: android.content.Context, c: OverdueCustomer, f: UiFormat, seller: BusinessProfileDto): String = buildString {
    appendLine(ctx.getString(R.string.reminder_greeting, c.name))
    appendLine()
    appendLine(ctx.getString(R.string.reminder_list_intro))
    c.invoices.forEach { b ->
        appendLine(ctx.getString(R.string.reminder_line, b.invoice.number, f.date(b.invoice.issueDate), f.amount(b.outstanding), f.date(b.invoice.dueDate), b.daysOverdue))
    }
    appendLine(ctx.getString(R.string.reminder_total, f.amount(c.total)))
    if (Upi.isValidVpa(seller.upiId)) appendLine(ctx.getString(R.string.pay_by_upi_x, seller.upiId.trim()))
    appendLine()
    appendLine(ctx.getString(R.string.reminder_ignore))
    append(ctx.getString(R.string.reminder_thanks))
    if (seller.name.isNotBlank()) append("\n" + seller.name)
}.trim()

/** Opens WhatsApp on the customer's mobile with [text] typed in, or the share sheet when there's no usable number or no WhatsApp. */
fun sendReminder(ctx: android.content.Context, vm: AppViewModel, mobile: String, text: String) {
    val wa = Reminders.whatsappNumber(mobile)
    vm.allowExternalActivity()
    val opened = wa != null && runCatching {
        ctx.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(Reminders.whatsappLink(wa, text))))
    }.isSuccess
    if (!opened) Exporter.shareText(ctx, text, ctx.getString(R.string.send_reminder))
}

/** Overdue collections: every customer with overdue invoices, with a one-tap reminder listing all of them. */
@Composable
fun CollectionsScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val seller by vm.businessProfile.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val ctx = LocalContext.current
    val customers = overdueCustomers(snap, currentScope(snap, s))
    AppScaffold(title = stringResource(R.string.collections_title), onBack = { nav.popBackStack() }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SectionCard {
                        Row {
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.overdue), style = MaterialTheme.typography.labelLarge)
                                Text(f.amount(customers.sumOf { it.total }), style = MaterialTheme.typography.titleLarge, color = fc.expense)
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text(stringResource(R.string.customers), style = MaterialTheme.typography.labelLarge)
                                Text(customers.size.toString(), style = MaterialTheme.typography.titleLarge)
                            }
                        }
                    }
                    InfoBanner(stringResource(R.string.collections_intro), icon = Icons.Filled.Info)
                }
            }
            if (customers.isEmpty()) item { EmptyState(Icons.Filled.CheckCircle, stringResource(R.string.no_overdue)) }
            items(customers, key = { it.partyId }) { c ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.partyDetail(c.partyId)) }, verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(c.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(stringResource(R.string.overdue_summary_x, c.invoices.size, c.oldestDays), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text(f.amount(c.total), style = MaterialTheme.typography.titleSmall, color = fc.expense)
                    }
                    c.invoices.forEach { b ->
                        Text("${b.invoice.number} · ${f.amount(b.outstanding)} · ${stringResource(R.string.inv_overdue_days, b.daysOverdue)}",
                            style = MaterialTheme.typography.bodySmall, modifier = Modifier.clickable { nav.navigate(Routes.invoice(b.invoice.id)) }.padding(vertical = 2.dp))
                    }
                    val wa = Reminders.whatsappNumber(c.mobile) != null
                    OutlinedButton(onClick = { sendReminder(ctx, vm, c.mobile, customerReminderText(ctx, c, f, seller)) }, modifier = Modifier.padding(top = 4.dp)) {
                        Icon(Icons.Filled.Share, null); Text(" " + stringResource(if (wa) R.string.whatsapp_reminder else R.string.send_reminder), maxLines = 1)
                    }
                }
                HorizontalDivider()
            }
            item { Box(Modifier.padding(24.dp)) }
        }
    }
}
