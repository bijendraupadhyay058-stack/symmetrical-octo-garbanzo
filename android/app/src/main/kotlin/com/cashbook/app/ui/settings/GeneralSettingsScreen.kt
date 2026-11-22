package com.cashbook.app.ui.settings

import androidx.appcompat.app.AppCompatDelegate
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.os.LocaleListCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.ThemeMode
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.core.CurrencyDisplay
import com.cashbook.core.DateFormatOption
import java.time.DayOfWeek
import java.time.LocalDate

fun applyLanguage(code: String) = AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(code))

@Composable
fun themeLabel(t: ThemeMode) = stringResource(when (t) { ThemeMode.SYSTEM -> R.string.theme_system; ThemeMode.LIGHT -> R.string.theme_light; ThemeMode.DARK -> R.string.theme_dark })

@Composable
fun GeneralSettingsScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    AppScaffold(title = stringResource(R.string.general_financial), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard(stringResource(R.string.general)) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    DropdownField(stringResource(R.string.language), listOf("en", "hi"), s.language, labelOf = { if (it == "hi") "हिन्दी (Hindi)" else "English" },
                        onSelect = { code -> vm.updateSettings { it.copy(language = code) }; applyLanguage(code) })
                    DropdownField(stringResource(R.string.theme), ThemeMode.entries, s.theme, labelOf = { themeLabel(it) }, onSelect = { t -> vm.updateSettings { it.copy(theme = t) } })
                    DropdownField(stringResource(R.string.date_format), DateFormatOption.entries, s.dateFormat, labelOf = { "${it.pattern.uppercase()}  (${it.format(LocalDate.now())})" },
                        onSelect = { d -> vm.updateSettings { it.copy(dateFormat = d) } })
                    DropdownField(stringResource(R.string.start_of_week), listOf(DayOfWeek.MONDAY, DayOfWeek.SUNDAY), s.weekStart,
                        labelOf = { stringResource(if (it == DayOfWeek.SUNDAY) R.string.sunday else R.string.monday) }, onSelect = { d -> vm.updateSettings { it.copy(weekStart = d) } })
                    val cbs = snap.cashbooks.filter { !it.archived }
                    DropdownField(stringResource(R.string.default_cashbook), cbs.map { it.id }, s.defaultCashbookId.takeIf { id -> cbs.any { it.id == id } },
                        labelOf = { snap.cashbookById[it]?.name ?: "" }, onSelect = { id -> vm.updateSettings { it.copy(defaultCashbookId = id) } })
                    val accs = snap.accounts.filter { !it.archived && it.cashbookId == s.defaultCashbookId }
                    DropdownField(stringResource(R.string.default_account), listOf(0L) + accs.map { it.id }, s.defaultAccountId.takeIf { id -> accs.any { it.id == id } } ?: 0L,
                        labelOf = { if (it == 0L) stringResource(R.string.first_account) else snap.accountById[it]?.name ?: "" },
                        onSelect = { id -> vm.updateSettings { it.copy(defaultAccountId = id) } })
                }
            }
            SectionCard(stringResource(R.string.financial)) {
                DropdownField(stringResource(R.string.currency_display), CurrencyDisplay.entries, s.currencyDisplay,
                    labelOf = { when (it) { CurrencyDisplay.SYMBOL -> "₹1,25,000.00"; CurrencyDisplay.CODE -> "INR 1,25,000.00"; CurrencyDisplay.NONE -> "1,25,000.00" } },
                    onSelect = { c -> vm.updateSettings { it.copy(currencyDisplay = c) } })
                SwitchRow(stringResource(R.string.allow_negative), s.allowNegative, { v -> vm.updateSettings { it.copy(allowNegative = v) } },
                    stringResource(if (s.allowNegative) R.string.allow_negative_on else R.string.allow_negative_off))
                InfoBanner(stringResource(R.string.fy_info))
            }
        }
    }
}
