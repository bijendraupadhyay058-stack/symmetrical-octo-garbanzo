package com.cashbook.app.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.cashbook.app.R
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.Snapshot
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.scopeName

/** Title-bar control to switch the active cashbook or choose the combined view. */
@Composable
fun CashbookSwitcher(snap: Snapshot, settings: AppSettings, subtitle: String, onSelect: (Long) -> Unit, onManage: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    val allLabel = stringResource(R.string.all_cashbooks)
    val scope = currentScope(snap, settings)
    val desc = stringResource(R.string.switch_cashbook)
    Column(Modifier.clickable(onClickLabel = desc) { open = true }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(scopeName(snap, settings, allLabel).ifEmpty { stringResource(R.string.app_name) }, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f, fill = false))
            Icon(Icons.Filled.ArrowDropDown, desc)
        }
        Text(subtitle, style = MaterialTheme.typography.labelSmall, maxLines = 1)
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            snap.cashbooks.filter { !it.archived }.forEach { cb ->
                val selected = settings.currentCashbookId != AppSettings.ALL_CASHBOOKS && cb.id in scope
                DropdownMenuItem(
                    text = { Text(cb.name + if (cb.isSample) " · " + stringResource(R.string.sample) else "") },
                    leadingIcon = { if (selected) Icon(Icons.Filled.Check, null) },
                    onClick = { onSelect(cb.id); open = false },
                )
            }
            if (snap.cashbooks.count { !it.archived } > 1) {
                DropdownMenuItem(
                    text = { Text(allLabel) },
                    leadingIcon = { if (settings.currentCashbookId == AppSettings.ALL_CASHBOOKS) Icon(Icons.Filled.Check, null) },
                    onClick = { onSelect(AppSettings.ALL_CASHBOOKS); open = false },
                )
            }
            HorizontalDivider()
            DropdownMenuItem(text = { Text(stringResource(R.string.manage_cashbooks)) }, leadingIcon = { Icon(Icons.Filled.Settings, null) },
                onClick = { open = false; onManage() })
        }
    }
}
