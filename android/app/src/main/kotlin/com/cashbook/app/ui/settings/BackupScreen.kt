package com.cashbook.app.ui.settings

import android.Manifest
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.components.formatSize
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.backup.BackupCrypto
import com.cashbook.core.backup.BackupException
import com.cashbook.core.backup.DecodedBackup
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Composable
fun BackupScreen(vm: AppViewModel, nav: NavHostController) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val deps = vm.deps ?: return
    val ctx = LocalContext.current
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val scope = rememberCoroutineScope()
    val history by remember { deps.ledger.backupHistory }.collectAsState(initial = emptyList())

    var password by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    var show by remember { mutableStateOf(false) }
    var includeAttachments by remember { mutableStateOf(true) }
    var busy by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<Pair<Boolean, String>?>(null) }

    var restoreUri by remember { mutableStateOf<Uri?>(null) }
    var restorePassword by remember { mutableStateOf("") }
    var decoded by remember { mutableStateOf<DecodedBackup?>(null) }
    var understood by remember { mutableStateOf(false) }

    val pwError = when {
        password.isEmpty() -> null
        password.length < BackupCrypto.MIN_PASSWORD_LENGTH -> stringResource(R.string.password_too_short, BackupCrypto.MIN_PASSWORD_LENGTH)
        confirm.isNotEmpty() && confirm != password -> stringResource(R.string.passwords_dont_match)
        else -> null
    }
    val canBackup = password.length >= BackupCrypto.MIN_PASSWORD_LENGTH && password == confirm && !busy

    fun errorText(e: Throwable) = ctx.getString(when ((e as? BackupException)?.reason) {
        BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED -> R.string.restore_wrong_password
        BackupException.Reason.NOT_A_BACKUP -> R.string.restore_not_backup
        BackupException.Reason.UNSUPPORTED_VERSION -> R.string.restore_unsupported
        BackupException.Reason.TRUNCATED -> R.string.restore_truncated
        BackupException.Reason.INVALID_DATA -> R.string.restore_invalid
        else -> R.string.operation_failed
    })

    val createDoc = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        busy = true
        scope.launch {
            val r = deps.backup.createBackup(uri, password.toCharArray(), includeAttachments)
            busy = false
            result = if (r.isSuccess) { password = ""; confirm = ""; true to ctx.getString(R.string.backup_success, formatSize(r.getOrDefault(0))) }
            else false to ctx.getString(R.string.backup_failed)
        }
    }
    val openDoc = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) { restoreUri = uri; restorePassword = "" } }
    val notifPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }

    AppScaffold(title = stringResource(R.string.backup_restore), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            InfoBanner(if (s.lastBackupAt > 0) stringResource(R.string.last_backup, f.dateTime(s.lastBackupAt)) else stringResource(R.string.never_backed_up))
            SectionCard(stringResource(R.string.create_backup)) {
                Text(stringResource(R.string.backup_explain), style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(password, { password = it }, label = { Text(stringResource(R.string.backup_password)) }, singleLine = true,
                    visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = { IconButton(onClick = { show = !show }) { Icon(if (show) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, stringResource(R.string.show_password)) } },
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(confirm, { confirm = it }, label = { Text(stringResource(R.string.confirm_password)) }, singleLine = true,
                    visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    isError = pwError != null, supportingText = pwError?.let { { Text(it) } }, modifier = Modifier.fillMaxWidth())
                SwitchRow(stringResource(R.string.include_attachments), includeAttachments, { includeAttachments = it }, stringResource(R.string.include_attachments_desc))
                InfoBanner(stringResource(R.string.password_loss_warning), icon = Icons.Filled.Warning)
                Button(onClick = {
                    vm.allowExternalActivity()
                    createDoc.launch("Cashbook_backup_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("dd-MM-yyyy_HHmm")) + ".cbk")
                }, enabled = canBackup, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) { Text(stringResource(R.string.choose_location_backup)) }
                Text(stringResource(R.string.cloud_hint), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            SectionCard(stringResource(R.string.restore_backup)) {
                Text(stringResource(R.string.restore_explain), style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = { vm.allowExternalActivity(); openDoc.launch(arrayOf("*/*")) }, enabled = !busy, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                    Text(stringResource(R.string.select_backup_file)) }
            }
            SectionCard(stringResource(R.string.backup_reminders)) {
                DropdownField(stringResource(R.string.remind_me), listOf(0, 7, 30), s.backupReminderDays, labelOf = {
                    when (it) { 0 -> stringResource(R.string.off); 7 -> stringResource(R.string.weekly); else -> stringResource(R.string.monthly) } },
                    onSelect = { d ->
                        if (d > 0 && Build.VERSION.SDK_INT >= 33) notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                        vm.updateSettings { it.copy(backupReminderDays = d) }
                    }, modifier = Modifier.fillMaxWidth())
            }
            if (history.isNotEmpty()) SectionCard(stringResource(R.string.history)) {
                history.forEach { h ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(if (h.success) Icons.Filled.CheckCircle else Icons.Filled.Error, null, tint = if (h.success) fc.income else fc.expense)
                        Column(Modifier.weight(1f).padding(start = 8.dp)) {
                            Text("${stringResource(if (h.kind == "RESTORE") R.string.restore else R.string.backup)} · ${f.dateTime(h.createdAt)}", style = MaterialTheme.typography.bodyMedium)
                            Text(h.fileName + if (h.sizeBytes > 0) " · " + formatSize(h.sizeBytes) else "", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
    }

    // ----- restore: password -> inspect -> confirm -> restore -----
    if (restoreUri != null && decoded == null) {
        AlertDialog(
            onDismissRequest = { if (!busy) restoreUri = null },
            title = { Text(stringResource(R.string.backup_password)) },
            text = {
                Column {
                    Text(stringResource(R.string.enter_backup_password))
                    OutlinedTextField(restorePassword, { restorePassword = it }, singleLine = true, visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 8.dp))
                }
            },
            confirmButton = {
                TextButton(enabled = restorePassword.isNotEmpty() && !busy, onClick = {
                    val uri = restoreUri ?: return@TextButton
                    busy = true
                    scope.launch {
                        val r = deps.backup.inspect(uri, restorePassword.toCharArray())
                        busy = false
                        r.onSuccess { decoded = it; understood = false }
                            .onFailure { e -> restoreUri = null; result = false to errorText(e) }
                    }
                }) { Text(stringResource(R.string.check_backup)) }
            },
            dismissButton = { TextButton(enabled = !busy, onClick = { restoreUri = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    decoded?.let { d ->
        val m = d.manifest
        AlertDialog(
            onDismissRequest = {},
            icon = { Icon(Icons.Filled.Warning, null, tint = fc.warning) },
            title = { Text(stringResource(R.string.confirm_restore)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(stringResource(R.string.backup_created_on, f.dateTime(m.createdAt), m.appVersion))
                    Text(stringResource(R.string.backup_contents, m.cashbooks, m.accounts, m.transactions, m.categories, m.parties))
                    Text(stringResource(if (m.includesAttachments) R.string.backup_has_attachments else R.string.backup_no_attachments, d.attachmentFiles.size))
                    Text(stringResource(R.string.restore_replace_warning), color = MaterialTheme.colorScheme.error)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(understood, { understood = it })
                        Text(stringResource(R.string.restore_understand), style = MaterialTheme.typography.bodySmall)
                    }
                    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                }
            },
            confirmButton = {
                TextButton(enabled = understood && !busy, onClick = {
                    busy = true
                    scope.launch {
                        val r = deps.backup.restore(d, deps.backup.displayName(restoreUri ?: Uri.EMPTY))
                        busy = false; decoded = null; restoreUri = null
                        result = if (r.isSuccess) true to ctx.getString(R.string.restore_success) else false to ctx.getString(R.string.restore_failed_preserved)
                    }
                }) { Text(stringResource(R.string.restore), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(enabled = !busy, onClick = { deps.backup.discardStaging(); decoded = null; restoreUri = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    result?.let { (ok, msg) ->
        AlertDialog(onDismissRequest = { result = null },
            icon = { Icon(if (ok) Icons.Filled.CheckCircle else Icons.Filled.Error, null, tint = if (ok) fc.income else fc.expense) },
            title = { Text(stringResource(if (ok) R.string.success else R.string.failed)) }, text = { Text(msg) },
            confirmButton = { TextButton(onClick = { result = null }) { Text(stringResource(R.string.ok)) } })
    }
}
