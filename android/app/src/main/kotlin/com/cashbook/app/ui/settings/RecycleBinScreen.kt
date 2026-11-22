package com.cashbook.app.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.RestoreFromTrash
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.ConfirmDialog
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.TxnRow
import com.cashbook.app.ui.nav.Routes
import com.cashbook.core.Txn
import com.cashbook.core.TxnType

@Composable
fun RecycleBinScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    var confirmEmpty by remember { mutableStateOf(false) }
    var confirmPurge by remember { mutableStateOf<Txn?>(null) }
    // Deleted entries whose accounts still exist (a deleted cashbook removes everything permanently).
    val items = snap.deleted
    AppScaffold(title = stringResource(R.string.recycle_bin), onBack = { nav.popBackStack() }, actions = {
        if (items.isNotEmpty()) IconButton(onClick = { confirmEmpty = true }) { Icon(Icons.Filled.DeleteSweep, stringResource(R.string.empty_recycle_bin)) }
    }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item {
                Column(Modifier.padding(16.dp)) {
                    DropdownField(stringResource(R.string.auto_delete), listOf(0, 30, 90), s.recycleRetentionDays,
                        labelOf = { if (it == 0) stringResource(R.string.keep_forever) else stringResource(R.string.after_days, it) },
                        onSelect = { d -> vm.updateSettings { it.copy(recycleRetentionDays = d) } })
                    InfoBanner(if (s.recycleRetentionDays > 0) stringResource(R.string.retention_info, s.recycleRetentionDays) else stringResource(R.string.retention_off),
                        Modifier.padding(top = 8.dp))
                }
            }
            if (items.isEmpty()) item { EmptyState(Icons.Filled.DeleteSweep, stringResource(R.string.recycle_empty)) }
            items(items, key = { it.id }) { t ->
                Column {
                    TxnRow(t, snap, onClick = { nav.navigate(Routes.txn(t.id)) })
                    Row(Modifier.padding(start = 70.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(R.string.deleted_on, f.dateTime(t.deletedAt ?: 0)), style = MaterialTheme.typography.labelSmall, modifier = Modifier.weight(1f))
                        TextButton(onClick = { vm.run { ledger.restoreTxn(t.id) } }) {
                            Icon(Icons.Filled.RestoreFromTrash, null); Text(" " + stringResource(R.string.restore))
                        }
                        IconButton(onClick = { confirmPurge = t }) { Icon(Icons.Filled.DeleteForever, stringResource(R.string.delete_permanently), tint = MaterialTheme.colorScheme.error) }
                    }
                    if (t.type == TxnType.TRANSFER) Text(stringResource(R.string.restore_transfer_note), style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(start = 70.dp, bottom = 4.dp))
                    HorizontalDivider()
                }
            }
        }
    }
    if (confirmEmpty) ConfirmDialog(stringResource(R.string.empty_recycle_bin), stringResource(R.string.empty_recycle_bin_text, items.size),
        stringResource(R.string.delete_permanently), onConfirm = { vm.run { ledger.emptyRecycleBin() } }, onDismiss = { confirmEmpty = false }, destructive = true)
    confirmPurge?.let { t ->
        ConfirmDialog(stringResource(R.string.delete_permanently), stringResource(R.string.delete_permanently_text), stringResource(R.string.delete_permanently),
            onConfirm = { vm.run { ledger.purge(listOf(t.id)) } }, onDismiss = { confirmPurge = null }, destructive = true)
    }
}
