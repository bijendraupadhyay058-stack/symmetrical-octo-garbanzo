package com.cashbook.app.ui.invoices

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.recurring.frequencyLabel
import com.cashbook.app.ui.theme.LocalFinanceColors

/** Recurring sales invoices: what each creates, how often, the next date and how many invoices it has made. */
@Composable
fun RecurringInvoicesScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val scope = currentScope(snap, s)
    val rows = snap.schedules.mapNotNull { sc -> snap.templates.firstOrNull { it.id == sc.templateId && it.cashbookId in scope }?.let { sc to it } }
        .sortedWith(compareBy({ !it.first.active || it.first.finished }, { it.first.nextDate }))
    AppScaffold(title = stringResource(R.string.recurring_invoices), onBack = { nav.popBackStack() }, floating = {
        ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.templateEdit(0)) }, icon = { Icon(Icons.Filled.Add, null) },
            text = { Text(stringResource(R.string.new_recurring_invoice)) })
    }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad)) {
            item { InfoBanner(stringResource(R.string.recurring_invoices_intro), Modifier.padding(16.dp), icon = Icons.Filled.Info) }
            if (rows.isEmpty()) item { EmptyState(Icons.Filled.Repeat, stringResource(R.string.no_recurring_invoices)) }
            items(rows, key = { it.first.id }) { (sc, t) ->
                val made = snap.invoices.count { it.scheduleId == sc.id }
                val state = when {
                    !sc.active -> stringResource(R.string.paused)
                    sc.finished -> stringResource(R.string.ended)
                    else -> stringResource(R.string.next_x, f.date(sc.nextDate!!))
                }
                Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.templateEdit(t.id)) }.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(snap.names.party(t.partyId), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (t.description.isNotBlank()) Text(t.description, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${frequencyLabel(sc.frequency, sc.interval)} · $state", style = MaterialTheme.typography.bodySmall,
                            color = if (sc.active && !sc.finished) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(stringResource(R.string.invoices_made_x, made), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(f.amount(t.amount), style = MaterialTheme.typography.titleSmall, color = if (sc.active) fc.income else MaterialTheme.colorScheme.outline)
                }
                HorizontalDivider()
            }
            item { Box(Modifier.padding(40.dp)) }
        }
    }
}
