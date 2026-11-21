package com.docdesk.app.ui.history

import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.Outcome
import com.docdesk.app.data.DocType
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.ConfirmDialog
import java.io.File
import java.text.DateFormat
import java.util.Date
import kotlinx.coroutines.launch

fun statusLabel(status: String) = runCatching { Outcome.valueOf(status).label }.getOrDefault(status)

@Composable
fun HistoryScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val items by app.history.all.collectAsStateWithLifecycle(emptyList())
    var confirmClear by remember { mutableStateOf(false) }
    Scaffold(topBar = {
        TopAppBar(title = { Text("History") }, actions = {
            if (items.isNotEmpty()) IconButton(onClick = { confirmClear = true }) { Icon(Icons.Default.DeleteSweep, "Clear history") }
        })
    }) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { Text("History stores only file names, dates and results – never document contents or passwords. You can turn it off in Settings.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            if (items.isEmpty()) item { Text("No operations yet.", Modifier.padding(vertical = 24.dp)) }
            items(items, key = { it.id }) { h ->
                val outcome = runCatching { Outcome.valueOf(h.status) }.getOrNull()
                Card(Modifier.padding(vertical = 2.dp)) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                when (outcome) { Outcome.SUCCESS -> Icons.Default.CheckCircle; Outcome.FAILED -> Icons.Default.Error; else -> Icons.Default.Warning },
                                contentDescription = statusLabel(h.status),
                                tint = when (outcome) { Outcome.SUCCESS -> MaterialTheme.colorScheme.primary; Outcome.FAILED -> MaterialTheme.colorScheme.error; else -> MaterialTheme.colorScheme.tertiary },
                            )
                            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                                Text(h.operation, style = MaterialTheme.typography.titleMedium)
                                if (h.inputNames.isNotBlank()) Text(h.inputNames, style = MaterialTheme.typography.bodyMedium)
                            }
                            IconButton(onClick = { scope.launch { app.history.delete(h.id) } }) { Icon(Icons.Default.Delete, "Remove from history") }
                        }
                        Text(h.summary, style = MaterialTheme.typography.bodyMedium)
                        Text(DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(h.timestamp)), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        val outputs = h.outputPaths.lines().filter { it.isNotBlank() }.map { File(it) }.filter { it.exists() }
                        outputs.forEach { f ->
                            AssistChip(onClick = {
                                if (DocType.of(f.name) == DocType.PDF) nav.to(Routes.VIEWER, Uri.fromFile(f))
                                else nav.to(Routes.FILES)
                            }, label = { Text("Open ${f.name}") })
                        }
                    }
                }
            }
        }
    }
    if (confirmClear) ConfirmDialog("Clear history?", "All history entries will be removed. Saved files are not deleted.", "Clear",
        onConfirm = { scope.launch { app.history.clear() }; confirmClear = false }, onDismiss = { confirmClear = false })
}
