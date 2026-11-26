package com.cashbook.app.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.BuildConfig
import com.cashbook.app.R
import com.cashbook.app.data.Diagnostics
import com.cashbook.app.data.Diagnostics.DeviceCheck
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.HealthCheck.Check
import com.cashbook.core.Severity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private fun deviceTitle(c: DeviceCheck) = when (c) {
    DeviceCheck.NOTIFICATIONS -> R.string.hc_notifications; DeviceCheck.DAILY_JOB -> R.string.hc_daily_job; DeviceCheck.BATTERY -> R.string.hc_battery
    DeviceCheck.BACKUP_FOLDER -> R.string.hc_backup_folder; DeviceCheck.LAST_BACKUP -> R.string.hc_last_backup; DeviceCheck.WHATSAPP -> R.string.hc_whatsapp
    DeviceCheck.PDF_VIEWER -> R.string.hc_pdf; DeviceCheck.STORAGE -> R.string.hc_storage; DeviceCheck.DATABASE -> R.string.hc_database
}

/** What a finding means for the user, and what to do about it (only for findings that aren't OK). */
private fun deviceAdvice(c: DeviceCheck) = when (c) {
    DeviceCheck.NOTIFICATIONS -> R.string.hc_notifications_fix; DeviceCheck.DAILY_JOB -> R.string.hc_daily_job_fix; DeviceCheck.BATTERY -> R.string.hc_battery_fix
    DeviceCheck.BACKUP_FOLDER -> R.string.hc_backup_folder_fix; DeviceCheck.LAST_BACKUP -> R.string.hc_last_backup_fix; DeviceCheck.WHATSAPP -> R.string.hc_whatsapp_fix
    DeviceCheck.PDF_VIEWER -> R.string.hc_pdf_fix; DeviceCheck.STORAGE -> R.string.hc_storage_fix; DeviceCheck.DATABASE -> R.string.hc_database_fix
}

private fun ledgerTitle(c: Check) = when (c) {
    Check.ALLOCATIONS_ORPHANED -> R.string.hc_orphaned; Check.OVER_ALLOCATED -> R.string.hc_over_allocated; Check.TRANSFER_BROKEN -> R.string.hc_transfers
    Check.CASHBOOK_MISMATCH -> R.string.hc_cashbook_mismatch; Check.CATEGORY_KIND -> R.string.hc_category_kind; Check.CONVERSION_LINK -> R.string.hc_links
    Check.NEGATIVE_BALANCE -> R.string.hc_negative
}

/**
 * Settings › App health check: is this phone set up so reminders, automatic backups, WhatsApp and PDFs work, and is
 * the data consistent. The report can be shared as text (no amounts or names of parties).
 */
@Composable
fun HealthCheckScreen(vm: AppViewModel, nav: NavHostController) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    val fc = LocalFinanceColors.current
    var run by remember { mutableIntStateOf(0) }
    var report by remember { mutableStateOf<Diagnostics.Report?>(null) }
    LaunchedEffect(run) {
        report = null
        val deps = vm.deps ?: return@LaunchedEffect
        report = withContext(Dispatchers.IO) { Diagnostics.run(ctx, deps, s, vm.snapshot.value) }
    }
    @Composable fun icon(sev: Severity) = when (sev) {
        Severity.OK -> Icons.Filled.CheckCircle to fc.income; Severity.INFO -> Icons.Filled.Info to MaterialTheme.colorScheme.primary
        Severity.WARNING -> Icons.Filled.Warning to fc.warning; Severity.ERROR -> Icons.Filled.Error to fc.expense
    }
    val sevLabels = mapOf(Severity.OK to stringResource(R.string.hc_ok), Severity.INFO to stringResource(R.string.hc_info),
        Severity.WARNING to stringResource(R.string.hc_warning), Severity.ERROR to stringResource(R.string.hc_error))
    @Composable fun line(title: String, sev: Severity, detail: String?) {
        val (ic, color) = icon(sev)
        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp).semantics(mergeDescendants = true) { stateDescription = sevLabels[sev]!! },
            horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
            Icon(ic, null, tint = color)
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyMedium)
                if (!detail.isNullOrBlank()) Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
    AppScaffold(title = stringResource(R.string.health_check), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            InfoBanner(stringResource(R.string.hc_intro), icon = Icons.Filled.Info)
            val r = report
            if (r == null) { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator() }; return@Column }
            val summary = when (r.worst) { Severity.ERROR -> R.string.hc_summary_error; Severity.WARNING -> R.string.hc_summary_warning; else -> R.string.hc_summary_ok }
            Text(stringResource(summary), style = MaterialTheme.typography.titleMedium, color = icon(r.worst).second.takeIf { r.worst != Severity.INFO } ?: Color.Unspecified)
            val deviceLines = r.device.map { d ->
                val detail = when {
                    d.check == DeviceCheck.LAST_BACKUP && d.detail != "-1" -> stringResource(R.string.hc_days_ago_x, d.detail.toIntOrNull() ?: 0) +
                        (if (d.severity != Severity.OK) " " + stringResource(deviceAdvice(d.check)) else "")
                    d.check == DeviceCheck.STORAGE -> stringResource(R.string.hc_free_mb_x, d.detail.toLongOrNull() ?: 0) +
                        (if (d.severity != Severity.OK) " " + stringResource(deviceAdvice(d.check)) else "")
                    d.severity != Severity.OK -> stringResource(deviceAdvice(d.check)) + (if (d.check == DeviceCheck.DATABASE) " (${d.detail})" else "")
                    else -> null
                }
                Triple(stringResource(deviceTitle(d.check)), d.severity, detail)
            }
            SectionCard(stringResource(R.string.hc_this_phone)) { deviceLines.forEach { (t, sev, detail) -> line(t, sev, detail) } }
            val ledgerLines = r.ledger.map { l ->
                Triple(stringResource(ledgerTitle(l.check)), l.severity,
                    if (l.count == 0) null else stringResource(R.string.hc_affected_x, l.count) + ": " + l.examples.joinToString("; "))
            }
            SectionCard(stringResource(R.string.hc_your_data)) { ledgerLines.forEach { (t, sev, detail) -> line(t, sev, detail) } }
            val header = stringResource(R.string.hc_report_header, BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE, android.os.Build.VERSION.RELEASE)
            Button(onClick = {
                val text = buildString {
                    appendLine(header)
                    (deviceLines + ledgerLines).forEach { (t, sev, d) -> appendLine("[${sevLabels[sev]}] $t" + (if (!d.isNullOrBlank()) " — $d" else "")) }
                }
                vm.allowExternalActivity(); Exporter.shareText(ctx, text.trim(), ctx.getString(R.string.health_check))
            }, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Filled.Share, null); Text(" " + stringResource(R.string.hc_share)) }
            OutlinedButton(onClick = { run++ }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.hc_run_again)) }
        }
    }
}
