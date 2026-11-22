package com.cashbook.app.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.EventRepeat
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.cashbook.app.R
import com.cashbook.app.data.Snapshot
import com.cashbook.core.Txn
import com.cashbook.core.TxnType

/** One entry in a list: type icon, description, category/party, account, mode, date, signed amount. */
@Composable
fun TxnRow(t: Txn, snap: Snapshot, onClick: () -> Unit, runningBalance: Long? = null, showCashbook: Boolean = false) {
    val f = LocalUiFormat.current
    val title = when {
        t.description.isNotBlank() -> t.description
        t.type == TxnType.TRANSFER -> stringResource(R.string.type_transfer)
        else -> snap.categoryName(t.categoryId)
    }
    val account = if (t.type == TxnType.TRANSFER) "${snap.names.account(t.accountId)} → ${snap.names.account(t.toAccountId)}" else snap.names.account(t.accountId)
    val detail = listOfNotNull(
        snap.categoryName(t.categoryId).takeIf { it.isNotBlank() && it != title },
        snap.names.party(t.partyId).takeIf { it.isNotBlank() },
    ).joinToString(" · ")
    val icon = snap.categoryById[t.categoryId]?.let { categoryIcon(it.icon) }
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        TypeAvatar(t.type, icon)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                if (t.recurringId != null) {
                    Spacer(Modifier.width(4.dp))
                    Icon(Icons.Filled.EventRepeat, stringResource(R.string.recurring_entry), Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if ((snap.attachmentCounts[t.id] ?: 0) > 0) {
                    Spacer(Modifier.width(4.dp))
                    Icon(Icons.Filled.AttachFile, stringResource(R.string.has_attachment), Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (detail.isNotBlank()) Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(buildString {
                append(f.date(t.date)); append(" · "); append(account)
                if (showCashbook) snap.cashbookById[t.cashbookId]?.let { append(" · ").append(it.name) }
            }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(verticalAlignment = Alignment.CenterVertically) {
                TypeBadge(t.type)
                Spacer(Modifier.width(6.dp))
                Text(paymentModeLabel(t.paymentMode), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Spacer(Modifier.width(8.dp))
        Column(horizontalAlignment = Alignment.End) {
            AmountText(t.amount, t.type)
            if (runningBalance != null) Text(stringResource(R.string.bal_short, f.amount(runningBalance)), style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
