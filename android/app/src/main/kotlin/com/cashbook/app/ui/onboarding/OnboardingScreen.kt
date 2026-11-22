package com.cashbook.app.ui.onboarding

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cashbook.app.R
import com.cashbook.app.data.ThemeMode
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.lock.PinSetup
import com.cashbook.app.ui.manage.AccountDraft
import com.cashbook.app.ui.manage.AccountDraftEditor
import com.cashbook.app.ui.manage.defaultDrafts
import com.cashbook.app.ui.manage.validDrafts
import com.cashbook.app.ui.settings.applyLanguage
import com.cashbook.app.ui.settings.sampleNames
import com.cashbook.app.ui.settings.themeLabel
import com.cashbook.app.ui.theme.LocalFinanceColors
import java.time.LocalDate

private const val STEPS = 7

/** First-run setup: welcome → language → theme → cashbook → accounts → app lock → finish. */
@Composable
fun OnboardingScreen(vm: AppViewModel) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    val fc = LocalFinanceColors.current
    var step by rememberSaveable { mutableStateOf(0) }
    var cashbookName by rememberSaveable { mutableStateOf("") }
    var openingDate by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    val initial = defaultDrafts()
    var drafts by rememberSaveable(stateSaver = AccountDraft.ListSaver) { mutableStateOf(initial) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    var pinSet by rememberSaveable { mutableStateOf(vm.container.secure.hasPin) }
    var settingPin by rememberSaveable { mutableStateOf(false) }
    var withSample by rememberSaveable { mutableStateOf(false) }
    var finishing by rememberSaveable { mutableStateOf(false) }
    val defaultName = stringResource(R.string.default_cashbook_name)

    fun finish() {
        finishing = true
        vm.run(onError = { finishing = false; vm.toast(it.localizedMessage ?: "Error") }) {
            ledger.ensureDefaultCategories(s.language)
            val date = LocalDate.ofEpochDay(openingDate)
            val id = ledger.createCashbook(cashbookName.ifBlank { defaultName }, "", date, drafts.filter { it.enabled }.map { it.toNew(date) })
            val sampleId = if (withSample) ledger.addSampleData(s.language, sampleNames(ctx)) else null
            this.settings.update { it.copy(onboarded = true, defaultCashbookId = id, currentCashbookId = id, lockEnabled = pinSet) }
            if (sampleId != null) vm.toast(ctx.getString(R.string.sample_added))
            vm.unlocked()
        }
    }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            Box(Modifier.fillMaxWidth().background(fc.header).padding(20.dp)) {
                Column {
                    Text(stringResource(R.string.setup_step, step + 1, STEPS), color = fc.onHeader.copy(alpha = 0.8f), style = MaterialTheme.typography.labelMedium)
                    Text(stringResource(stepTitle(step)), color = fc.onHeader, style = MaterialTheme.typography.headlineSmall)
                    Spacer(Modifier.height(8.dp))
                    LinearProgressIndicator({ (step + 1f) / STEPS }, Modifier.fillMaxWidth())
                }
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                when (step) {
                    0 -> {
                        Icon(Icons.AutoMirrored.Filled.MenuBook, null, Modifier.size(64.dp), tint = MaterialTheme.colorScheme.primary)
                        Text(stringResource(R.string.welcome_title), style = MaterialTheme.typography.titleLarge)
                        Text(stringResource(R.string.welcome_body))
                        listOf(R.string.welcome_p1, R.string.welcome_p2, R.string.welcome_p3, R.string.welcome_p4).forEach {
                            Row(verticalAlignment = Alignment.Top) {
                                Icon(Icons.Filled.CheckCircle, null, tint = fc.income, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.size(8.dp)); Text(stringResource(it))
                            }
                        }
                        InfoBanner(stringResource(R.string.welcome_offline))
                    }
                    1 -> listOf("en" to "English", "hi" to "हिन्दी (Hindi)").forEach { (code, label) ->
                        Choice(label, s.language == code) { vm.updateSettings { it.copy(language = code) }; applyLanguage(code) }
                    }
                    2 -> ThemeMode.entries.forEach { t -> Choice(themeLabel(t), s.theme == t) { vm.updateSettings { it.copy(theme = t) } } }
                    3 -> {
                        OutlinedTextField(cashbookName, { cashbookName = it }, label = { Text(stringResource(R.string.cashbook_name)) }, placeholder = { Text(defaultName) },
                            singleLine = true, supportingText = { Text(stringResource(R.string.cashbook_name_hint)) }, modifier = Modifier.fillMaxWidth())
                        DateField(stringResource(R.string.opening_date), LocalDate.ofEpochDay(openingDate), { openingDate = it.toEpochDay() },
                            supporting = stringResource(R.string.opening_date_hint))
                    }
                    4 -> {
                        Text(stringResource(R.string.accounts_setup_hint))
                        AccountDraftEditor(drafts, { drafts = it }, showErrors)
                    }
                    5 -> {
                        Icon(Icons.Filled.Lock, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.primary)
                        Text(stringResource(R.string.lock_setup_body))
                        if (pinSet) {
                            InfoBanner(stringResource(R.string.pin_enabled), icon = Icons.Filled.CheckCircle)
                            TextButton(onClick = { vm.container.secure.clearPin(); pinSet = false }) { Text(stringResource(R.string.remove_pin)) }
                        } else Button(onClick = { settingPin = true }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.set_pin)) }
                        Text(stringResource(R.string.lock_later_hint), style = MaterialTheme.typography.bodySmall)
                    }
                    6 -> {
                        Icon(Icons.Filled.CheckCircle, null, Modifier.size(64.dp), tint = fc.income)
                        Text(stringResource(R.string.ready_body, cashbookName.ifBlank { defaultName }))
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.selectable(withSample, role = Role.Checkbox) { withSample = !withSample }) {
                            Checkbox(withSample, null)
                            Column {
                                Text(stringResource(R.string.add_sample))
                                Text(stringResource(R.string.sample_desc), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (step > 0) OutlinedButton(onClick = { step-- }, enabled = !finishing) { Text(stringResource(R.string.back)) }
                Spacer(Modifier.weight(1f))
                if (step in setOf(1, 2, 5)) TextButton(onClick = { step++ }) { Text(stringResource(R.string.skip)) }
                Button(enabled = !finishing, onClick = {
                    when (step) {
                        4 -> { showErrors = true; if (validDrafts(drafts)) step++ }
                        STEPS - 1 -> finish()
                        else -> step++
                    }
                }) { Text(stringResource(if (step == STEPS - 1) R.string.start_using else R.string.next)) }
            }
        }
        if (settingPin) PinSetup(stringResource(R.string.set_pin), onDone = { pin -> vm.container.secure.setPin(pin); pinSet = true; settingPin = false },
            onCancel = { settingPin = false })
    }
}

private fun stepTitle(step: Int) = when (step) {
    0 -> R.string.step_welcome; 1 -> R.string.step_language; 2 -> R.string.step_theme; 3 -> R.string.step_cashbook
    4 -> R.string.step_accounts; 5 -> R.string.step_lock; else -> R.string.step_done
}

@Composable
private fun Choice(label: String, selected: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().selectable(selected, role = Role.RadioButton, onClick = onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected, null)
        Spacer(Modifier.size(12.dp))
        Text(label, style = MaterialTheme.typography.titleMedium)
    }
}
