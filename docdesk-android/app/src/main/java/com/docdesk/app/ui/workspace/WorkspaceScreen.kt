package com.docdesk.app.ui.workspace

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Business
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.DocStatus
import com.docdesk.core.Workspace
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

/** Client list with search across clients and filed documents. */
@Composable
fun WorkspaceScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val clients by app.workspace.dao.observeClients().collectAsStateWithLifecycle(emptyList())
    val docs by app.workspace.dao.observeAllDocs().collectAsStateWithLifecycle(emptyList())
    val folders by app.workspace.dao.observeAllFolders().collectAsStateWithLifecycle(emptyList())
    var query by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<DocStatus?>(null) }
    var showArchived by remember { mutableStateOf(false) }
    var creating by remember { mutableStateOf(false) }

    ToolScaffold("Client workspace", nav::back) {
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, leadingIcon = { Icon(Icons.Default.Search, null) },
            label = { Text("Search clients, file names, tags, notes, folders") })
        @OptIn(ExperimentalLayoutApi::class)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(status == null, { status = null }, label = { Text("Any status") })
            DocStatus.entries.forEach { s -> FilterChip(status == s, { status = if (status == s) null else s }, label = { Text(s.label) }) }
        }
        val searching = query.isNotBlank() || status != null
        if (searching) {
            val byId = clients.associateBy { it.id }; val fById = folders.associateBy { it.id }
            val hits = docs.filter { d ->
                (status == null || d.status == status!!.name) &&
                    Workspace.matches(query, d.name, d.tags, d.note, d.mime.substringAfter('/'), byId[d.clientId]?.name, fById[d.folderId]?.name,
                        DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(d.addedAt)))
            }
            val clientHits = if (status == null) clients.filter { Workspace.matches(query, it.name, it.reference, it.notes) } else emptyList()
            SectionCard("Results") {
                if (hits.isEmpty() && clientHits.isEmpty()) Text("Nothing found. Search looks at client names, file names, tags, notes, folder names, file type and the date added.", style = MaterialTheme.typography.bodySmall)
                clientHits.forEach { c -> ListItem(headlineContent = { Text(c.name) }, supportingContent = { Text("Client" + if (c.archived) " · archived" else "") }, leadingContent = { Icon(Icons.Default.Business, null) }, modifier = Modifier.clickable { nav.to("${Routes.CLIENT}/${c.id}") }) }
                hits.take(200).forEach { d ->
                    ListItem(headlineContent = { Text(d.name) },
                        supportingContent = { Text(listOfNotNull(byId[d.clientId]?.name, fById[d.folderId]?.name, DocStatus.entries.firstOrNull { it.name == d.status }?.label, d.tags.ifBlank { null }).joinToString(" · ")) },
                        leadingContent = { Icon(Icons.Default.Description, null) }, modifier = Modifier.clickable { nav.to("${Routes.CLIENT}/${d.clientId}?folder=${d.folderId ?: -1}") })
                }
            }
            Text("Search inside PDF text: use Search in Files on the Home screen.", style = MaterialTheme.typography.bodySmall)
        } else {
            val shown = clients.filter { showArchived || !it.archived }
            if (clients.isEmpty()) Notice("Organise documents by client: Client › Financial year › Category › File. Everything stays on this phone. Files stay where they are – DocDesk keeps a link to them.")
            SectionCard(if (shown.isEmpty()) "No clients yet" else "${shown.size} client(s)") {
                shown.forEach { c ->
                    val n = docs.count { it.clientId == c.id }; val pending = docs.count { it.clientId == c.id && it.status == DocStatus.PENDING_REVIEW.name }
                    ListItem(headlineContent = { Text(c.name) },
                        supportingContent = { Text(listOfNotNull(c.reference.ifBlank { null }, "$n document(s)", if (pending > 0) "$pending pending review" else null, if (c.archived) "archived" else null).joinToString(" · ")) },
                        leadingContent = { Icon(Icons.Default.Business, null) }, modifier = Modifier.clickable { nav.to("${Routes.CLIENT}/${c.id}") })
                }
                if (clients.any { it.archived }) SwitchRow("Show archived clients", showArchived) { showArchived = it }
            }
        }
        PrimaryAction("New client", icon = Icons.Default.PersonAdd) { creating = true }
    }
    if (creating) {
        var name by remember { mutableStateOf("") }; var ref by remember { mutableStateOf("") }
        AlertDialog(onDismissRequest = { creating = false }, title = { Text("New client") },
            text = { Column {
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Client name") })
                OutlinedTextField(ref, { ref = it }, Modifier.fillMaxWidth().padding(top = 8.dp), singleLine = true, label = { Text("Reference (optional, e.g. file no.)") })
                Text("Stored only on this phone.", style = MaterialTheme.typography.bodySmall)
            } },
            confirmButton = { TextButton({ val n = name; creating = false; scope.launch { val id = app.workspace.createClient(n, ref); nav.to("${Routes.CLIENT}/$id") } }, enabled = name.isNotBlank()) { Text("Create") } },
            dismissButton = { TextButton({ creating = false }) { Text("Cancel") } })
    }
}

@Composable
internal fun StatusChips(current: String, onSet: (DocStatus) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { DocStatus.entries.forEach { s -> FilterChip(current == s.name, { onSet(s) }, label = { Text(s.label) }) } }
}
