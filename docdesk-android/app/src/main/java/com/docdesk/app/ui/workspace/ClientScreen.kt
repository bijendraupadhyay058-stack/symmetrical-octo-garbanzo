package com.docdesk.app.ui.workspace

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.NoteAdd
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CreateNewFolder
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.db.ChecklistEntity
import com.docdesk.app.data.db.FolderEntity
import com.docdesk.app.data.db.WsDocEntity
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.core.DocStatus
import com.docdesk.core.FolderKind
import com.docdesk.core.Workspace
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.DateFormat
import java.time.LocalDate
import java.util.Date

/** One client: folders and documents, checklists, notes and recent activity. */
@Composable
fun ClientScreen(nav: Nav, clientId: Long, startFolder: Long?) {
    val app = DocDeskApp.instance
    val ws = app.workspace
    val scope = rememberCoroutineScope()
    val loaded by produceState<Pair<Boolean, com.docdesk.app.data.db.ClientEntity?>>(false to null, clientId) { ws.dao.observeClient(clientId).collect { value = true to it } }
    val client = loaded.second
    val folders by ws.dao.observeFolders(clientId).collectAsStateWithLifecycle(emptyList())
    val docs by ws.dao.observeDocs(clientId).collectAsStateWithLifecycle(emptyList())
    var tab by remember { mutableIntStateOf(0) }
    var folder by remember { mutableStateOf(startFolder) }
    var menu by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf(false) }
    var newFolder by remember { mutableStateOf(false) }
    var openDoc by remember { mutableStateOf<WsDocEntity?>(null) }
    var folderMenu by remember { mutableStateOf<FolderEntity?>(null) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) scope.launch { ws.addDocuments(clientId, folder, uris, app.files) }
    }
    val c = client
    ToolScaffold(c?.name ?: "Client", nav::back, actions = {
        Box {
            IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Client actions") }
            DropdownMenu(menu, { menu = false }) {
                DropdownMenuItem(text = { Text("Rename") }, onClick = { menu = false; renaming = true })
                if (c != null) DropdownMenuItem(text = { Text(if (c.archived) "Restore from archive" else "Archive") }, onClick = {
                    menu = false; scope.launch { ws.updateClient(c.copy(archived = !c.archived), if (c.archived) "Restored from archive" else "Archived") }
                })
            }
        }
    }) {
        if (c == null) { Text(if (loaded.first) "This client was not found – it may have been replaced by restoring a backup." else "Loading…"); return@ToolScaffold }
        TabRow(tab) { listOf("Files", "Checklists", "Notes", "Activity").forEachIndexed { i, t -> Tab(tab == i, { tab = i }, text = { Text(t) }) } }
        when (tab) {
            0 -> {
                // Breadcrumb
                val byId = folders.associateBy { it.id }
                val path = generateSequence(folder?.let { byId[it] }) { f -> f.parentId?.let { byId[it] } }.toList().reversed()
                @OptIn(ExperimentalLayoutApi::class)
                FlowRow(verticalArrangement = Arrangement.Center) {
                    TextButton({ folder = null }) { Text(c.name) }
                    path.forEach { f -> Text("›", Modifier.padding(top = 12.dp)); TextButton({ folder = f.id }) { Text(f.name) } }
                }
                if (folder != null && folder !in byId) folder = null
                val sub = folders.filter { it.parentId == folder }
                val here = docs.filter { it.folderId == folder }
                if (sub.isEmpty() && here.isEmpty()) Notice(if (folder == null) "Start with a financial-year folder (e.g. ${Workspace.financialYear(LocalDate.now())}), then add category folders such as GST or Bank Statements inside it." else "This folder is empty.")
                sub.forEach { f ->
                    val count = docs.count { it.folderId == f.id }
                    ListItem(headlineContent = { Text(f.name) }, supportingContent = { Text("${FolderKind.entries.firstOrNull { it.name == f.kind }?.label ?: "Folder"} · $count file(s)") },
                        leadingContent = { Icon(Icons.Default.Folder, null) },
                        trailingContent = { IconButton({ folderMenu = f }) { Icon(Icons.Default.MoreVert, "Folder actions for ${f.name}") } },
                        modifier = Modifier.clickable { folder = f.id })
                }
                here.forEach { d ->
                    ListItem(headlineContent = { Text(d.name) },
                        supportingContent = { Text(listOfNotNull(DocStatus.entries.firstOrNull { it.name == d.status }?.label, d.tags.ifBlank { null }, formatSize(d.size)).joinToString(" · ")) },
                        leadingContent = { Icon(Icons.Default.Description, null) }, modifier = Modifier.clickable { openDoc = d })
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SecondaryAction("New folder", icon = Icons.Default.CreateNewFolder, modifier = Modifier.weight(1f)) { newFolder = true }
                    SecondaryAction("Add documents", icon = Icons.AutoMirrored.Filled.NoteAdd, modifier = Modifier.weight(1f)) { picker.launch(arrayOf("*/*")) }
                }
                Text("Files stay where they are; DocDesk keeps a link. If a file is moved or deleted elsewhere, its entry shows as unavailable.", style = MaterialTheme.typography.bodySmall)
            }
            1 -> Checklists(clientId)
            2 -> {
                var notes by remember(c.id) { mutableStateOf(c.notes) }
                OutlinedTextField(notes, { notes = it }, Modifier.fillMaxWidth(), minLines = 8, label = { Text("Private notes") })
                Text("Stored only on this phone (and in backups you make).", style = MaterialTheme.typography.bodySmall)
                SecondaryAction("Save notes", enabled = notes != c.notes) { scope.launch { ws.updateClient(c.copy(notes = notes), "Notes updated") } }
            }
            else -> {
                val activity by ws.dao.observeActivity(clientId).collectAsStateWithLifecycle(emptyList())
                val fmt = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
                if (activity.isEmpty()) Text("No activity yet.")
                activity.forEach { a -> ListItem(headlineContent = { Text(a.text) }, supportingContent = { Text(fmt.format(Date(a.time))) }) }
            }
        }
    }
    if (renaming && c != null) {
        var name by remember { mutableStateOf(c.name) }; var ref by remember { mutableStateOf(c.reference) }
        AlertDialog(onDismissRequest = { renaming = false }, title = { Text("Client details") },
            text = { Column {
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Client name") })
                OutlinedTextField(ref, { ref = it }, Modifier.fillMaxWidth().padding(top = 8.dp), singleLine = true, label = { Text("Reference (optional)") })
            } },
            confirmButton = { TextButton({ renaming = false; scope.launch { ws.updateClient(c.copy(name = name.trim(), reference = ref.trim()), "Details changed") } }, enabled = name.isNotBlank()) { Text("Save") } },
            dismissButton = { TextButton({ renaming = false }) { Text("Cancel") } })
    }
    if (newFolder) NewFolderDialog(onDismiss = { newFolder = false }) { name, kind -> newFolder = false; scope.launch { ws.createFolder(clientId, folder, name, kind) } }
    folderMenu?.let { f ->
        var name by remember(f.id) { mutableStateOf(f.name) }
        AlertDialog(onDismissRequest = { folderMenu = null }, title = { Text("Folder") },
            text = { Column {
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Name") })
                Text("Removing a folder moves its files and subfolders up one level; nothing is deleted.", style = MaterialTheme.typography.bodySmall)
                TextButton({ folderMenu = null; scope.launch { ws.deleteFolder(f) } }) { Text("Remove folder", color = MaterialTheme.colorScheme.error) }
            } },
            confirmButton = { TextButton({ folderMenu = null; scope.launch { ws.renameFolder(f, name) } }, enabled = name.isNotBlank() && name != f.name) { Text("Rename") } },
            dismissButton = { TextButton({ folderMenu = null }) { Text("Close") } })
    }
    openDoc?.let { d -> DocDialog(nav, d, folders) { openDoc = null } }
}

@Composable
private fun NewFolderDialog(onDismiss: () -> Unit, onCreate: (String, FolderKind) -> Unit) {
    var kind by remember { mutableStateOf(FolderKind.FINANCIAL_YEAR) }
    var name by remember { mutableStateOf(Workspace.financialYear(LocalDate.now())) }
    val today = LocalDate.now()
    val suggestions = when (kind) {
        FolderKind.FINANCIAL_YEAR -> Workspace.recentFinancialYears(today)
        FolderKind.ASSESSMENT_YEAR -> Workspace.recentAssessmentYears(today)
        FolderKind.CATEGORY -> Workspace.categories
        FolderKind.OTHER -> emptyList()
    }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("New folder") },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            RadioOptions(FolderKind.entries, kind, { it.label }) { kind = it; name = when (it) { FolderKind.FINANCIAL_YEAR -> Workspace.financialYear(today); FolderKind.ASSESSMENT_YEAR -> Workspace.assessmentYear(today); FolderKind.CATEGORY -> "GST"; FolderKind.OTHER -> "" } }
            @OptIn(ExperimentalLayoutApi::class)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { suggestions.forEach { s -> AssistChip({ name = s }, label = { Text(s) }) } }
            OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Folder name") })
        } },
        confirmButton = { TextButton({ onCreate(name, kind) }, enabled = name.isNotBlank()) { Text("Create") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } })
}

@Composable
private fun DocDialog(nav: Nav, d: WsDocEntity, folders: List<FolderEntity>, onClose: () -> Unit) {
    val app = DocDeskApp.instance
    val ws = app.workspace
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val available by produceState<Boolean?>(null, d.uri) { value = withContext(Dispatchers.IO) { ws.isAvailable(d) } }
    var tags by remember(d.id) { mutableStateOf(d.tags) }
    var note by remember(d.id) { mutableStateOf(d.note) }
    var status by remember(d.id) { mutableStateOf(d.status) }
    var folderId by remember(d.id) { mutableStateOf(d.folderId) }
    var moveMenu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = onClose, title = { Text(d.name) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            when (available) {
                null -> Text("Checking file…", style = MaterialTheme.typography.bodySmall)
                false -> Notice("This file can't be opened any more – it may have been moved, renamed or deleted, or access was removed. Remove this entry and add the file again.", NoteKind.WARNING)
                true -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton({
                        onClose()
                        if (d.mime == "application/pdf" || d.name.endsWith(".pdf", true)) nav.to(Routes.VIEWER, Uri.parse(d.uri))
                        else runCatching { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(d.uri), d.mime.ifEmpty { "*/*" }).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Open with")) }
                    }) { Text("Open") }
                    TextButton({ runCatching { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType(d.mime.ifEmpty { "*/*" }).putExtra(Intent.EXTRA_STREAM, Uri.parse(d.uri)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Share")) }.onFailure { error = "Couldn't share this file." } }) { Text("Share") }
                }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Text("Status", style = MaterialTheme.typography.labelLarge)
            StatusChips(status) { status = it.name }
            OutlinedTextField(tags, { tags = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Tags (comma separated)") })
            OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), minLines = 2, label = { Text("Private note") })
            Box {
                TextButton({ moveMenu = true }) { Text("Folder: ${folders.firstOrNull { it.id == folderId }?.name ?: "(client top level)"} – change") }
                DropdownMenu(moveMenu, { moveMenu = false }) {
                    DropdownMenuItem(text = { Text("(client top level)") }, onClick = { folderId = null; moveMenu = false })
                    folders.forEach { f -> DropdownMenuItem(text = { Text(f.name) }, onClick = { folderId = f.id; moveMenu = false }) }
                }
            }
            Text("Added ${DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(d.addedAt))}", style = MaterialTheme.typography.bodySmall)
            TextButton({ onClose(); scope.launch { ws.removeDoc(d) } }) { Text("Remove from workspace (file is not deleted)", color = MaterialTheme.colorScheme.error) }
        } },
        confirmButton = { TextButton({
            onClose()
            val tagStr = Workspace.parseTags(tags).joinToString(", ")
            val changed = listOfNotNull(if (tagStr != d.tags) "tags" else null, if (note != d.note) "note" else null, if (status != d.status) "status ${DocStatus.valueOf(status).label}" else null, if (folderId != d.folderId) "moved" else null)
            if (changed.isNotEmpty()) scope.launch { ws.updateDoc(d.copy(tags = tagStr, note = note, status = status, folderId = folderId), changed.joinToString(", ") + " updated") }
        }) { Text("Save") } },
        dismissButton = { TextButton(onClose) { Text("Close") } })
}

@Composable
private fun Checklists(clientId: Long) {
    val ws = DocDeskApp.instance.workspace
    val scope = rememberCoroutineScope()
    val lists by ws.dao.observeChecklists(clientId).collectAsStateWithLifecycle(emptyList())
    val items by ws.dao.observeItems(clientId).collectAsStateWithLifecycle(emptyList())
    var creating by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<ChecklistEntity?>(null) }
    if (lists.isEmpty()) Notice("Checklists track what you've collected or done for this client, e.g. for ITR filing or a tax audit. Start from a template and edit it.")
    lists.forEach { cl ->
        val its = items.filter { it.checklistId == cl.id }.sortedBy { it.position }
        SectionCard("${cl.title} · ${its.count { it.done }}/${its.size}") {
            if (its.isNotEmpty()) LinearProgressIndicator(progress = { its.count { it.done }.toFloat() / its.size }, modifier = Modifier.fillMaxWidth())
            its.forEach { i ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(i.done, { scope.launch { ws.toggleItem(clientId, i) } })
                    Text(i.text, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                    IconButton({ scope.launch { ws.dao.deleteItem(i) } }) { Icon(Icons.Default.Close, "Remove item ${i.text}") }
                }
            }
            var newItem by remember(cl.id) { mutableStateOf("") }
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(newItem, { newItem = it }, Modifier.weight(1f), singleLine = true, label = { Text("Add item") })
                IconButton({ val t = newItem.trim(); newItem = ""; scope.launch { ws.dao.upsertItem(com.docdesk.app.data.db.ChecklistItemEntity(checklistId = cl.id, text = t, position = (its.maxOfOrNull { it.position } ?: 0) + 1)) } }, enabled = newItem.isNotBlank()) { Icon(Icons.Default.Add, "Add item") }
            }
            TextButton({ deleting = cl }) { Text("Delete checklist", color = MaterialTheme.colorScheme.error) }
        }
    }
    SecondaryAction("New checklist", icon = Icons.Default.Checklist) { creating = true }
    Text("Templates are starting points – check them against current rules and the client's situation.", style = MaterialTheme.typography.bodySmall)
    if (creating) {
        var template by remember { mutableStateOf<String?>(Workspace.checklistTemplates.keys.first()) }
        var title by remember { mutableStateOf(Workspace.checklistTemplates.keys.first()) }
        AlertDialog(onDismissRequest = { creating = false }, title = { Text("New checklist") },
            text = { Column(Modifier.verticalScroll(rememberScrollState())) {
                RadioOptions(Workspace.checklistTemplates.keys.toList<String?>() + listOf<String?>(null), template, { it ?: "Blank checklist" }) { template = it; title = it ?: "" }
                OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Title") })
            } },
            confirmButton = { TextButton({ creating = false; val t = template; scope.launch { ws.createChecklist(clientId, title, t?.let { Workspace.checklistTemplates[it] } ?: emptyList()) } }, enabled = title.isNotBlank()) { Text("Create") } },
            dismissButton = { TextButton({ creating = false }) { Text("Cancel") } })
    }
    deleting?.let { cl ->
        AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Delete “${cl.title}”?") }, text = { Text("Its items and ticks are deleted.") },
            confirmButton = { TextButton({ deleting = null; scope.launch { ws.deleteChecklist(cl) } }) { Text("Delete") } },
            dismissButton = { TextButton({ deleting = null }) { Text("Cancel") } })
    }
}
