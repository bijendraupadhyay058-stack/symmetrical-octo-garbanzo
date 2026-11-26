package com.cashbook.app.ui.dashboard

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.Snapshot
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.nav.openTab
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.TxnType

/** First-week steps, each done when the data says so (nothing to tick by hand). */
enum class StartStep { FIRST_ENTRY, BUSINESS_PROFILE, APP_LOCK, BACKUP, INVOICE, REPORT }

/** Which getting-started steps are done. Entries and invoices in the sample cashbook don't count. */
fun gettingStarted(snap: Snapshot, s: AppSettings, businessName: String): Map<StartStep, Boolean> {
    val real = snap.cashbooks.filter { !it.isSample }.map { it.id }.toSet()
    return linkedMapOf(
        StartStep.FIRST_ENTRY to snap.txns.any { it.cashbookId in real },
        StartStep.BUSINESS_PROFILE to businessName.isNotBlank(),
        StartStep.APP_LOCK to s.lockEnabled,
        StartStep.BACKUP to (s.lastBackupAt > 0 || s.autoBackupEnabled),
        StartStep.INVOICE to (snap.invoices.any { it.cashbookId in real } || snap.quotations.any { it.cashbookId in real }),
        StartStep.REPORT to s.seenReports,
    )
}

@Composable
private fun stepTitle(step: StartStep) = stringResource(when (step) {
    StartStep.FIRST_ENTRY -> R.string.gs_first_entry; StartStep.BUSINESS_PROFILE -> R.string.gs_profile; StartStep.APP_LOCK -> R.string.gs_lock
    StartStep.BACKUP -> R.string.gs_backup; StartStep.INVOICE -> R.string.gs_invoice; StartStep.REPORT -> R.string.gs_report
})

/** "Getting started" card on the dashboard until every step is done or the user hides it. */
@Composable
fun GettingStartedCard(vm: AppViewModel, nav: NavHostController, snap: Snapshot, s: AppSettings, businessName: String) {
    if (s.checklistHidden) return
    val steps = gettingStarted(snap, s, businessName)
    val done = steps.count { it.value }
    if (done == steps.size) return
    val fc = LocalFinanceColors.current
    SectionCard(stringResource(R.string.gs_title), action = {
        TextButton(onClick = { vm.updateSettings { it.copy(checklistHidden = true) } }) { Text(stringResource(R.string.gs_hide)) }
    }) {
        Text(stringResource(R.string.gs_progress_x, done, steps.size), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        LinearProgressIndicator(progress = { done.toFloat() / steps.size }, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp))
        val doneLabel = stringResource(R.string.gs_done); val todoLabel = stringResource(R.string.gs_todo)
        steps.forEach { (step, ok) ->
            Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = !ok, role = Role.Button) {
                when (step) {
                    StartStep.FIRST_ENTRY -> nav.navigate(Routes.newTxn(TxnType.EXPENSE))
                    StartStep.BUSINESS_PROFILE -> nav.navigate(Routes.BUSINESS)
                    StartStep.APP_LOCK -> nav.navigate(Routes.SECURITY)
                    StartStep.BACKUP -> nav.navigate(Routes.BACKUP)
                    StartStep.INVOICE -> nav.navigate(Routes.invoiceEdit(0, "SALE"))
                    StartStep.REPORT -> nav.openTab(Routes.REPORTS)
                }
            }.semantics { stateDescription = if (ok) doneLabel else todoLabel }, verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Icon(if (ok) Icons.Filled.CheckCircle else Icons.Filled.RadioButtonUnchecked, null,
                    tint = if (ok) fc.income else MaterialTheme.colorScheme.onSurfaceVariant)
                Text(stepTitle(step), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium,
                    color = if (ok) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
                if (!ok) Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
            }
        }
    }
}

/** A version's highlights for "What's new". */
data class Release(val code: Int, val name: String, val highlights: List<Int>)

val RELEASES = listOf(
    Release(17, "1.16", listOf(R.string.wn_16_1)),
    Release(18, "1.17", listOf(R.string.wn_17_1, R.string.wn_17_2)),
    Release(19, "1.18", listOf(R.string.wn_18_1)),
)

/** Releases newer than the one last seen (installs that updated from before 1.17 count as 1.16 = code 17). */
fun releasesSince(lastSeen: Int, onboarded: Boolean, current: Int): List<Release> {
    if (!onboarded) return emptyList()
    val since = if (lastSeen == 0) 17 else lastSeen
    return RELEASES.filter { it.code in (since + 1)..current }
}

/** Shown once after an update; closing it records the version. */
@Composable
fun WhatsNewDialog(vm: AppViewModel, s: AppSettings) {
    val current = com.cashbook.app.BuildConfig.VERSION_CODE
    val news = releasesSince(s.lastSeenVersion, s.onboarded, current)
    if (news.isEmpty()) return
    val close = { vm.updateSettings { it.copy(lastSeenVersion = current) } }
    AlertDialog(onDismissRequest = close, title = { Text(stringResource(R.string.wn_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                news.reversed().forEach { r ->
                    Text(stringResource(R.string.wn_version_x, r.name), style = MaterialTheme.typography.titleSmall)
                    r.highlights.forEach { Text("• " + stringResource(it), style = MaterialTheme.typography.bodyMedium) }
                }
            }
        },
        confirmButton = { TextButton(onClick = close) { Text(stringResource(R.string.wn_ok)) } })
}
