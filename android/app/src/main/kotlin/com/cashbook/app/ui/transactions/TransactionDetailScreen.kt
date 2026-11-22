package com.cashbook.app.ui.transactions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AmountText
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.AttachmentItem
import com.cashbook.app.ui.components.AttachmentUi
import com.cashbook.app.ui.components.ConfirmDialog
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.TypeAvatar
import com.cashbook.app.ui.components.TypeBadge
import com.cashbook.app.ui.components.paymentModeLabel
import com.cashbook.app.ui.components.txnTypeLabel
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.TxnType
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch

@Composable
fun TransactionDetailScreen(vm: AppViewModel, nav: NavHostController, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val deps = vm.deps ?: return
    val t = snap.txns.firstOrNull { it.id == id } ?: snap.deleted.firstOrNull { it.id == id }
    val attachments by remember(id) { deps.ledger.attachmentsFor(id) }.collectAsState(initial = emptyList())
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val ctx = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    var confirmDelete by remember { mutableStateOf(false) }
    val noViewer = stringResource(R.string.no_viewer)

    AppScaffold(
        title = stringResource(R.string.entry_details), onBack = { nav.popBackStack() }, snackbar = snackbar,
        actions = {
            if (t != null && t.deletedAt == null) {
                IconButton(onClick = {
                    vm.allowExternalActivity()
                    Exporter.shareText(ctx, buildShareText(ctx, t, snap, f), ctx.getString(R.string.share))
                }) { Icon(Icons.Filled.Share, stringResource(R.string.share)) }
                IconButton(onClick = { nav.navigate(Routes.editTxn(id)) }) { Icon(Icons.Filled.Edit, stringResource(R.string.edit)) }
            }
        },
    ) { pad ->
        if (t == null) { EmptyState(Icons.Filled.Delete, stringResource(R.string.entry_not_found), Modifier.padding(pad)); return@AppScaffold }
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TypeAvatar(t.type)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        TypeBadge(t.type)
                        Text(t.description.ifBlank { snap.categoryName(t.categoryId).ifBlank { txnTypeLabel(t.type) } }, style = MaterialTheme.typography.titleMedium)
                        Text(f.date(t.date), style = MaterialTheme.typography.bodySmall)
                    }
                    AmountText(t.amount, t.type, style = MaterialTheme.typography.headlineSmall)
                }
                if (t.deletedAt != null) Text(stringResource(R.string.in_recycle_bin_since, f.dateTime(t.deletedAt!!)), color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
            if (t.type == TxnType.TRANSFER) {
                SectionCard(stringResource(R.string.both_sides)) {
                    Row(Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.from_account) + ": " + snap.names.account(t.accountId), Modifier.weight(1f))
                        Text("−" + f.amount(t.amount), color = fc.expense)
                    }
                    Spacer(Modifier.height(6.dp))
                    Row(Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.to_account) + ": " + snap.names.account(t.toAccountId), Modifier.weight(1f))
                        Text("+" + f.amount(t.amount), color = fc.income)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(stringResource(R.string.transfer_note_short), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            SectionCard(stringResource(R.string.details)) {
                Detail(stringResource(R.string.cashbook), snap.cashbookById[t.cashbookId]?.name ?: "")
                if (t.type != TxnType.TRANSFER) {
                    Detail(stringResource(R.string.category), snap.categoryName(t.categoryId))
                    Detail(stringResource(R.string.account), snap.names.account(t.accountId))
                    Detail(stringResource(if (t.type == TxnType.INCOME) R.string.received_from else R.string.paid_to), snap.names.party(t.partyId))
                }
                Detail(stringResource(R.string.payment_mode), paymentModeLabel(t.paymentMode))
                Detail(stringResource(R.string.reference_number), t.reference)
                Detail(stringResource(R.string.tags), t.tagList.joinToString(", "))
                Detail(stringResource(R.string.notes), t.notes)
                Detail(stringResource(R.string.created), f.dateTime(t.createdAt))
                if (t.updatedAt > t.createdAt + 1000) Detail(stringResource(R.string.modified), f.dateTime(t.updatedAt))
            }
            if (attachments.isNotEmpty()) SectionCard(stringResource(R.string.attachments)) {
                attachments.forEach { a ->
                    AttachmentItem(AttachmentUi("e:${a.id}", deps.attachments.file(a.storedName), a.fileName, a.mimeType, a.sizeBytes), null, null,
                        onOpenFailed = { scope.launch { snackbar.showSnackbar(noViewer) } }, beforeExternal = vm::allowExternalActivity)
                }
            }
            if (t.deletedAt == null) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { nav.navigate(Routes.duplicateTxn(id)) }, Modifier.weight(1f)) {
                        Icon(Icons.Filled.ContentCopy, null); Text(" " + stringResource(R.string.duplicate)) }
                    OutlinedButton(onClick = { confirmDelete = true }, Modifier.weight(1f)) {
                        Icon(Icons.Filled.Delete, null, tint = MaterialTheme.colorScheme.error); Text(" " + stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
                }
            } else {
                OutlinedButton(onClick = { vm.run { ledger.restoreTxn(id) } }, Modifier.fillMaxWidth()) { Text(stringResource(R.string.restore)) }
            }
        }
    }
    if (confirmDelete && t != null) {
        ConfirmDialog(
            title = stringResource(R.string.delete_entry_title),
            text = stringResource(if (t.type == TxnType.TRANSFER) R.string.delete_transfer_text else R.string.delete_entry_text),
            confirm = stringResource(R.string.move_to_recycle_bin), destructive = true,
            onConfirm = { vm.run { ledger.deleteTxn(id) }; vm.toast(ctx.getString(R.string.moved_to_recycle_bin)); nav.popBackStack() },
            onDismiss = { confirmDelete = false },
        )
    }
}

@Composable
private fun Detail(label: String, value: String) {
    if (value.isBlank()) return
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
    HorizontalDivider()
}

private fun buildShareText(ctx: android.content.Context, t: com.cashbook.core.Txn, snap: com.cashbook.app.data.Snapshot, f: com.cashbook.app.ui.components.UiFormat): String {
    val type = ctx.getString(when (t.type) { TxnType.INCOME -> R.string.type_income; TxnType.EXPENSE -> R.string.type_expense; TxnType.TRANSFER -> R.string.type_transfer })
    return buildString {
        appendLine("${ctx.getString(R.string.app_name)} – $type")
        appendLine("${ctx.getString(R.string.date)}: ${f.date(t.date)}")
        appendLine("${ctx.getString(R.string.amount)}: ${f.amount(t.amount)}")
        if (t.type == TxnType.TRANSFER) appendLine("${snap.names.account(t.accountId)} → ${snap.names.account(t.toAccountId)}")
        else {
            appendLine("${ctx.getString(R.string.category)}: ${snap.categoryName(t.categoryId)}")
            appendLine("${ctx.getString(R.string.account)}: ${snap.names.account(t.accountId)}")
            snap.names.party(t.partyId).takeIf { it.isNotBlank() }?.let { appendLine("${ctx.getString(R.string.party)}: $it") }
        }
        if (t.description.isNotBlank()) appendLine("${ctx.getString(R.string.description)}: ${t.description}")
        if (t.reference.isNotBlank()) appendLine("${ctx.getString(R.string.reference_number)}: ${t.reference}")
    }.trim()
}
