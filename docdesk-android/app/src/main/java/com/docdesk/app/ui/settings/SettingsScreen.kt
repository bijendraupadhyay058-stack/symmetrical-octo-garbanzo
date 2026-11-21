package com.docdesk.app.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.BuildConfigInfo
import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.AppSettings
import com.docdesk.app.data.ThemeMode
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.ui.components.ConfirmDialog
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.formatSize
import com.docdesk.core.DateOrder
import com.docdesk.core.NumberStyle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun SettingsScreen() {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val s by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    var tempBytes by remember { mutableLongStateOf(app.files.temporaryBytes()) }
    var confirmHistory by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var restoreUri by remember { mutableStateOf<android.net.Uri?>(null) }
    var backupDialog by remember { mutableStateOf(false) }
    var pendingBackup by remember { mutableStateOf<Triple<String, Boolean, com.docdesk.app.data.BackupFrequency>?>(null) }
    var cloudCfg by remember { mutableStateOf(com.docdesk.app.data.CloudBackup.config(app)) }
    var busy by remember { mutableStateOf<String?>(null) }
    val backupTarget = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.CreateDocument("application/octet-stream")) { u ->
        val req = pendingBackup; pendingBackup = null
        if (u != null && req != null) scope.launch {
            busy = "Encrypting and saving backup…"
            note = runCatching {
                val o = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { com.docdesk.app.data.CloudBackup.backupNow(app, u, req.first.toCharArray(), req.second, req.third) }
                "Encrypted backup saved (${o.documents} document(s), ${formatSize(o.bytes)}). If you chose a cloud app, it uploads the file. Keep your backup password safe – without it the backup can't be opened." +
                    if (req.third != com.docdesk.app.data.BackupFrequency.OFF && !com.docdesk.app.data.CloudBackup.config(app).hasKey) " Automatic backups aren't available on this phone (secure key storage missing)." else ""
            }.getOrElse { "Backup failed: ${it.message}" }
            busy = null; cloudCfg = com.docdesk.app.data.CloudBackup.config(app)
        }
    }
    val backupPicker = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocument()) { u -> restoreUri = u }

    Scaffold(topBar = { TopAppBar(title = { Text("Settings") }) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            note?.let { Notice(it) { note = null } }
            SectionCard("Appearance") {
                RadioOptions(ThemeMode.entries, s.theme, { it.label }) { scope.launch { app.settings.setTheme(it) } }
                Text("Text size follows your phone's font size setting (Settings › Display).", style = MaterialTheme.typography.bodySmall)
            }
            SectionCard("Default OCR language") {
                RadioOptions(OcrLanguage.entries, s.ocrLanguage, { it.label }) { scope.launch { app.settings.setOcrLanguage(it) } }
                Text("Both recognisers are built into the app and work offline.", style = MaterialTheme.typography.bodySmall)
            }
            SectionCard("Default formats for PDF to Excel") {
                Text("Dates", style = MaterialTheme.typography.labelLarge)
                RadioOptions(DateOrder.entries, s.dateOrder, { it.label }) { scope.launch { app.settings.setDateOrder(it) } }
                Text("Numbers", style = MaterialTheme.typography.labelLarge)
                RadioOptions(NumberStyle.entries, s.numberStyle, { it.label }) { scope.launch { app.settings.setNumberStyle(it) } }
            }
            SectionCard("Security") {
                val context = androidx.compose.ui.platform.LocalContext.current
                val canLock = androidx.biometric.BiometricManager.from(context).canAuthenticate(androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK or androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL) == androidx.biometric.BiometricManager.BIOMETRIC_SUCCESS
                SwitchRow("Lock DocDesk", s.appLock, if (canLock) "Ask for fingerprint, face or screen lock when opening the app and after 1 minute in the background." else "Set up a screen lock or fingerprint in your phone's settings first.") { v ->
                    if (!canLock && v) note = "Your phone has no screen lock or fingerprint set up, so DocDesk can't be locked. Add one in Settings › Security."
                    else scope.launch { app.settings.setAppLock(v) }
                }
                SwitchRow("Hide content & block screenshots", s.secureScreen, "Documents are hidden in the recent-apps view and screenshots/screen recording are blocked.") { scope.launch { app.settings.setSecureScreen(it) } }
            }
            SectionCard("Privacy") {
                SwitchRow("Keep processing history", s.keepHistory, "Only file names, dates and results are stored.") { scope.launch { app.settings.setKeepHistory(it) } }
                SecondaryAction("Clear history") { confirmHistory = true }
                SecondaryAction("Delete temporary files (${formatSize(tempBytes)})") {
                    scope.launch {
                        withContext(Dispatchers.IO) { if (!app.jobs.isBusy) app.files.cleanTemporary() }
                        tempBytes = app.files.temporaryBytes()
                        note = if (app.jobs.isBusy) "An operation is running; temporary files will be cleaned when it finishes." else "Temporary files deleted."
                    }
                }
                Text(PRIVACY, style = MaterialTheme.typography.bodySmall)
            }
            SectionCard("Backup (cloud or phone)") {
                Text("Encrypted backup of your client workspace (clients, folders, document links, tags, notes, statuses, checklists, activity), settings and – if you choose – the documents in My Files. Save it to Google Drive, OneDrive, Dropbox or any cloud app on this phone, or to the phone itself.", style = MaterialTheme.typography.bodySmall)
                Text("The file is encrypted with your password (AES-256) before it leaves DocDesk; DocDesk itself never connects to the internet – the cloud app you choose uploads the file. Forgotten passwords can't be recovered.", style = MaterialTheme.typography.bodySmall)
                busy?.let { Text(it) }
                SecondaryAction("Back up now…", enabled = busy == null) { backupDialog = true }
                SecondaryAction("Restore from a backup…", enabled = busy == null) { backupPicker.launch(arrayOf("application/octet-stream", "application/json", "text/plain", "*/*")) }
                val c = cloudCfg
                if (c.uri != null) {
                    Text("Automatic backup: ${c.frequency.label}" + (c.fileName?.let { " to “$it”" } ?: ""), style = MaterialTheme.typography.bodyMedium)
                    if (c.lastTime > 0) Text("Last: ${java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT).format(java.util.Date(c.lastTime))} – ${c.lastStatus}", style = MaterialTheme.typography.bodySmall)
                    else if (c.lastStatus.isNotEmpty()) Text(c.lastStatus, style = MaterialTheme.typography.bodySmall)
                    RadioOptions(com.docdesk.app.data.BackupFrequency.entries, c.frequency, { it.label }) { f ->
                        if (f != com.docdesk.app.data.BackupFrequency.OFF && !c.hasKey) { note = "To turn automatic backups on again, use “Back up now…” with your password."; return@RadioOptions }
                        com.docdesk.app.data.CloudBackup.setFrequency(app, f); cloudCfg = com.docdesk.app.data.CloudBackup.config(app)
                    }
                    SecondaryAction("Forget backup location") { com.docdesk.app.data.CloudBackup.forget(app); cloudCfg = com.docdesk.app.data.CloudBackup.config(app); note = "Automatic backups stopped. Existing backup files are not deleted." }
                }
            }
            SectionCard("Help us fix problems") {
                val ctx = androidx.compose.ui.platform.LocalContext.current
                Text("If something didn't work, send a problem report. It contains the app and Android version, phone model and technical error details – never your documents, file names or passwords. You choose how to send it (e-mail, WhatsApp…).", style = MaterialTheme.typography.bodySmall)
                SecondaryAction("Send problem report") { runCatching { ctx.startActivity(com.docdesk.app.data.ProblemReports.shareIntent()) } }
                SecondaryAction("Clear problem log") { com.docdesk.app.data.ProblemReports.clear(); note = "Problem log cleared." }
            }
            SectionCard("About") {
                Text("DocDesk ${BuildConfigInfo.versionName(app)}", style = MaterialTheme.typography.bodyLarge)
                Text(LIMITS, style = MaterialTheme.typography.bodySmall)
                Text("Open-source components", style = MaterialTheme.typography.labelLarge)
                Text(LICENCES, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
    restoreUri?.let { u ->
        var pw by remember { mutableStateOf("") }
        var restoring by remember { mutableStateOf(false) }
        androidx.compose.material3.AlertDialog(onDismissRequest = { if (!restoring) restoreUri = null }, title = { Text("Restore backup?") },
            text = { Column {
                Text("Your current client workspace and settings are replaced by the backup's contents. Documents in the backup are added to My Files (nothing there is overwritten). Linked documents open only if they are still on this phone.")
                androidx.compose.material3.OutlinedTextField(pw, { pw = it }, Modifier.fillMaxWidth().padding(top = 8.dp), singleLine = true, label = { Text("Backup password") },
                    visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(), supportingText = { Text("Leave empty for an older unencrypted .json backup.") })
                if (restoring) Text("Restoring…")
            } },
            confirmButton = { TextButton({
                restoring = true
                scope.launch {
                    note = runCatching {
                        val bytes = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { app.contentResolver.openInputStream(u)!!.use { it.readBytes() } }
                        val r = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { com.docdesk.app.data.CloudBackup.restore(app, bytes, pw.toCharArray()) }
                        "Restored ${r.data.clients} client(s), ${r.data.documents} document link(s), ${r.data.checklists} checklist(s), ${r.data.settings} setting(s) and ${r.documentsRestored} document(s) into My Files."
                    }.getOrElse { it.message ?: "Restore failed." }
                    restoring = false; restoreUri = null
                }
            }, enabled = !restoring) { Text("Restore") } },
            dismissButton = { TextButton({ restoreUri = null }, enabled = !restoring) { Text("Cancel") } })
    }
    if (backupDialog) {
        var pw by remember { mutableStateOf("") }; var pw2 by remember { mutableStateOf("") }
        var files by remember { mutableStateOf(true) }
        var freq by remember { mutableStateOf(com.docdesk.app.data.BackupFrequency.OFF) }
        val problem = com.docdesk.core.BackupCrypto.passwordProblem(pw) ?: if (pw != pw2) "The passwords don't match." else null
        androidx.compose.material3.AlertDialog(onDismissRequest = { backupDialog = false }, title = { Text("Encrypted backup") },
            text = { Column(Modifier.verticalScroll(rememberScrollState())) {
                androidx.compose.material3.OutlinedTextField(pw, { pw = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Backup password (min. 8)") }, visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                androidx.compose.material3.OutlinedTextField(pw2, { pw2 = it }, Modifier.fillMaxWidth().padding(top = 6.dp), singleLine = true, label = { Text("Repeat password") }, visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                    isError = pw2.isNotEmpty() && problem != null, supportingText = { if (pw.isNotEmpty()) Text(problem ?: "OK") })
                SwitchRow("Include documents in My Files", files, "${app.files.listMyFiles().size} file(s), ${formatSize(app.files.listMyFiles().sumOf { it.size })}. Linked workspace files outside My Files are not included.") { files = it }
                Text("Repeat automatically to the same file", style = MaterialTheme.typography.labelLarge)
                RadioOptions(com.docdesk.app.data.BackupFrequency.entries, freq, { it.label }) { freq = it }
                Text("Next you choose where to save – pick Drive, OneDrive, Dropbox or another cloud app in the menu of the file picker.", style = MaterialTheme.typography.bodySmall)
            } },
            confirmButton = { TextButton({ backupDialog = false; pendingBackup = Triple(pw, files, freq); backupTarget.launch("DocDesk backup ${java.time.LocalDate.now()}.ddbk") }, enabled = problem == null) { Text("Choose location") } },
            dismissButton = { TextButton({ backupDialog = false }) { Text("Cancel") } })
    }
    if (confirmHistory) ConfirmDialog("Clear history?", "All history entries will be removed. Saved files are not deleted.", "Clear",
        onConfirm = { scope.launch { app.history.clear() }; confirmHistory = false; note = "History cleared." }, onDismiss = { confirmHistory = false })
}

private const val PRIVACY = "All conversion, OCR, editing and page tools run on this phone. DocDesk does not upload your documents, has no analytics, and does not log document contents or passwords. Passwords you type are kept in memory only while the file is open. Files are excluded from cloud backup. Temporary files are deleted after use and automatically after one day. The camera scanner is provided by Google Play services, which may download its scanning module the first time you use it; the scanned images stay on your phone."

private const val LIMITS = "Conversions are best-effort and can differ from the original, especially with complex tables, merged cells, unusual fonts, handwriting and low-quality scans. Always check important figures against the source document. Older .doc/.xls files are not supported; existing PDF text cannot be edited in place (use Cover + Text box instead)."

private const val LICENCES = "PdfBox-Android (Apache License 2.0) · Google ML Kit Text Recognition v2 and Document Scanner (ML Kit Terms of Service; free, on-device) · AndroidX / Jetpack Compose / Room / WorkManager / DataStore (Apache 2.0) · Kotlin & kotlinx.coroutines (Apache 2.0) · Reorderable by Calvin Liang (Apache 2.0)."
