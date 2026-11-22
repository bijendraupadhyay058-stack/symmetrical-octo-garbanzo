package com.cashbook.app.ui.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.HelpOutline
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Backup
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.EventRepeat
import androidx.compose.material.icons.filled.Savings
import androidx.compose.material.icons.filled.Feedback
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material.icons.filled.Science
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.BuildConfig
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.ConfirmDialog
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.NavRow
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.nav.openTab

@Composable
fun SettingsScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    val f = LocalUiFormat.current
    var confirmRemoveSample by remember { mutableStateOf(false) }
    val hasSample = snap.cashbooks.any { it.isSample }
    AppScaffold(title = stringResource(R.string.nav_settings)) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState())) {
            Header(stringResource(R.string.settings_books))
            NavRow(stringResource(R.string.cashbooks), Icons.AutoMirrored.Filled.MenuBook, stringResource(R.string.cashbooks_desc)) { nav.navigate(Routes.CASHBOOKS) }
            NavRow(stringResource(R.string.accounts), Icons.Filled.AccountBalanceWallet, stringResource(R.string.accounts_desc)) {
                currentScope(snap, s).singleOrNull()?.let { nav.navigate(Routes.accounts(it)) } ?: nav.navigate(Routes.CASHBOOKS)
            }
            NavRow(stringResource(R.string.categories), Icons.Filled.Category, stringResource(R.string.categories_desc)) { nav.navigate(Routes.CATEGORIES) }
            NavRow(stringResource(R.string.parties), Icons.Filled.People, stringResource(R.string.parties_desc)) { nav.navigate(Routes.PARTIES) }
            NavRow(stringResource(R.string.recurring_entries), Icons.Filled.EventRepeat, stringResource(R.string.recurring_desc, snap.recurring.count { it.active && !it.finished })) { nav.navigate(Routes.RECURRING) }
            NavRow(stringResource(R.string.budgets), Icons.Filled.Savings, stringResource(R.string.budgets_desc)) { nav.navigate(Routes.BUDGETS) }
            HorizontalDivider()
            Header(stringResource(R.string.settings_preferences))
            NavRow(stringResource(R.string.general_financial), Icons.Filled.Tune, stringResource(R.string.general_desc)) { nav.navigate(Routes.GENERAL) }
            NavRow(stringResource(R.string.security), Icons.Filled.Security,
                stringResource(if (s.lockEnabled) R.string.app_lock_on else R.string.app_lock_off)) { nav.navigate(Routes.SECURITY) }
            HorizontalDivider()
            Header(stringResource(R.string.settings_data))
            NavRow(stringResource(R.string.backup_restore), Icons.Filled.Backup,
                if (s.lastBackupAt > 0) stringResource(R.string.last_backup, f.dateTime(s.lastBackupAt)) else stringResource(R.string.never_backed_up)) { nav.navigate(Routes.BACKUP) }
            NavRow(stringResource(R.string.export_data), Icons.Filled.Download, stringResource(R.string.export_data_desc)) { vm.pendingReportAllTime = true; nav.navigate(Routes.report("CUSTOM")) }
            NavRow(stringResource(R.string.recycle_bin), Icons.Filled.DeleteSweep, stringResource(R.string.recycle_bin_count, snap.deleted.size)) { nav.navigate(Routes.RECYCLE) }
            NavRow(stringResource(if (hasSample) R.string.remove_sample else R.string.add_sample), Icons.Filled.Science, stringResource(R.string.sample_desc)) {
                if (hasSample) confirmRemoveSample = true
                else vm.run {
                    val id = ledger.addSampleData(s.language, sampleNames(ctx))
                    this.settings.update { it.copy(currentCashbookId = id) }
                    vm.toast(ctx.getString(R.string.sample_added))
                }
            }
            HorizontalDivider()
            Header(stringResource(R.string.settings_other))
            NavRow(stringResource(R.string.user_guide), Icons.AutoMirrored.Filled.HelpOutline) { nav.navigate(Routes.GUIDE) }
            NavRow(stringResource(R.string.privacy_policy), Icons.Filled.PrivacyTip) { nav.navigate(Routes.PRIVACY) }
            NavRow(stringResource(R.string.about), Icons.Filled.Info, stringResource(R.string.version_x, BuildConfig.VERSION_NAME)) { nav.navigate(Routes.ABOUT) }
            NavRow(stringResource(R.string.feedback), Icons.Filled.Feedback, stringResource(R.string.feedback_desc)) {
                vm.allowExternalActivity()
                val i = Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:"))
                    .putExtra(Intent.EXTRA_SUBJECT, "Cashbook ${BuildConfig.VERSION_NAME} feedback")
                runCatching { ctx.startActivity(Intent.createChooser(i, ctx.getString(R.string.feedback))) }
            }
        }
    }
    if (confirmRemoveSample) ConfirmDialog(stringResource(R.string.remove_sample), stringResource(R.string.remove_sample_text), stringResource(R.string.remove),
        onConfirm = {
            vm.run {
                ledger.removeSampleData()
                val remaining = ledger.snapshot.value.cashbooks.filter { !it.isSample }
                this.settings.update { st -> st.copy(currentCashbookId = remaining.firstOrNull()?.id ?: 0, defaultCashbookId = if (remaining.any { it.id == st.defaultCashbookId }) st.defaultCashbookId else remaining.firstOrNull()?.id ?: 0) }
            }
            nav.openTab(Routes.DASHBOARD)
        }, onDismiss = { confirmRemoveSample = false }, destructive = true)
}

@Composable
fun Header(text: String) = Text(text, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary,
    modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp))

fun sampleNames(ctx: android.content.Context) = LedgerRepository.SampleNames(
    ctx.getString(R.string.sample_cashbook), ctx.getString(R.string.sample_cashbook_desc), ctx.getString(R.string.sample_cash), ctx.getString(R.string.sample_bank),
    ctx.getString(R.string.sample_t1), ctx.getString(R.string.sample_t2), ctx.getString(R.string.sample_t3), ctx.getString(R.string.sample_t4),
)
