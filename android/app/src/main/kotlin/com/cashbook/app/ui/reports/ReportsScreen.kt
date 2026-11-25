package com.cashbook.app.ui.reports

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ListAlt
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CalendarToday
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.HourglassBottom
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.PieChart
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.CashbookSwitcher
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.reportDescRes
import com.cashbook.app.ui.components.reportTitleRes
import com.cashbook.app.ui.nav.Routes
import com.cashbook.core.ReportType

fun reportIcon(t: ReportType) = when (t) {
    ReportType.DAILY_CASHBOOK -> Icons.Filled.CalendarToday
    ReportType.MONTHLY_SUMMARY -> Icons.Filled.CalendarMonth
    ReportType.YEARLY_SUMMARY -> Icons.Filled.BarChart
    ReportType.FINANCIAL_YEAR -> Icons.Filled.DateRange
    ReportType.CATEGORY_WISE -> Icons.Filled.Category
    ReportType.PARTY_WISE -> Icons.Filled.People
    ReportType.ACCOUNT_WISE -> Icons.Filled.AccountBalance
    ReportType.INCOME_EXPENSE -> Icons.Filled.PieChart
    ReportType.TRANSFERS -> Icons.Filled.SwapHoriz
    ReportType.CUSTOM -> Icons.Filled.Tune
    ReportType.OUTSTANDING -> Icons.Filled.HourglassBottom
    ReportType.GST_SUMMARY -> Icons.Filled.AccountBalance
    ReportType.STOCK_SUMMARY -> Icons.Filled.Inventory2
    ReportType.ITEM_SALES -> Icons.Filled.BarChart
    ReportType.PARTY_STATEMENT -> Icons.Filled.People
    ReportType.BANK_RECONCILIATION -> Icons.Filled.AccountBalance
}

@Composable
fun ReportsScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    AppScaffold(
        title = stringResource(R.string.nav_reports),
        titleContent = {
            CashbookSwitcher(snap, s, stringResource(R.string.nav_reports), onSelect = { id -> vm.updateSettings { it.copy(currentCashbookId = id) } },
                onManage = { nav.navigate(Routes.CASHBOOKS) })
        },
    ) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { InfoBanner(stringResource(R.string.reports_intro), icon = Icons.AutoMirrored.Filled.ListAlt) }
            items(ReportType.entries) { t ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), elevation = CardDefaults.cardElevation(1.dp)) {
                    ListItem(
                        headlineContent = { Text(stringResource(reportTitleRes(t))) },
                        supportingContent = { Text(stringResource(reportDescRes(t))) },
                        leadingContent = { Icon(reportIcon(t), null, tint = MaterialTheme.colorScheme.primary) },
                        colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surface),
                        modifier = Modifier.clickable { nav.navigate(Routes.report(t.name)) },
                    )
                }
            }
        }
    }
}
