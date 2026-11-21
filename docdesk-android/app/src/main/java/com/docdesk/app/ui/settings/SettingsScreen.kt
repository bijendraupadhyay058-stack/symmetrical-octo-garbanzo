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
    if (confirmHistory) ConfirmDialog("Clear history?", "All history entries will be removed. Saved files are not deleted.", "Clear",
        onConfirm = { scope.launch { app.history.clear() }; confirmHistory = false; note = "History cleared." }, onDismiss = { confirmHistory = false })
}

private const val PRIVACY = "All conversion, OCR, editing and page tools run on this phone. DocDesk does not upload your documents, has no analytics, and does not log document contents or passwords. Passwords you type are kept in memory only while the file is open. Files are excluded from cloud backup. Temporary files are deleted after use and automatically after one day. The camera scanner is provided by Google Play services, which may download its scanning module the first time you use it; the scanned images stay on your phone."

private const val LIMITS = "Conversions are best-effort and can differ from the original, especially with complex tables, merged cells, unusual fonts, handwriting and low-quality scans. Always check important figures against the source document. Older .doc/.xls files are not supported; existing PDF text cannot be edited in place (use Cover + Text box instead)."

private const val LICENCES = "PdfBox-Android (Apache License 2.0) · Google ML Kit Text Recognition v2 and Document Scanner (ML Kit Terms of Service; free, on-device) · AndroidX / Jetpack Compose / Room / WorkManager / DataStore (Apache 2.0) · Kotlin & kotlinx.coroutines (Apache 2.0) · Reorderable by Calvin Liang (Apache 2.0)."
