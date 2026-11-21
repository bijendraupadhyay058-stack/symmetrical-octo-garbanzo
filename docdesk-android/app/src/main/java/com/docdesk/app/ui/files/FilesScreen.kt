package com.docdesk.app.ui.files

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.DocType
import com.docdesk.app.data.FileRepository
import com.docdesk.app.data.StoredFile
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.CheckRow
import com.docdesk.app.ui.components.ConfirmDialog
import com.docdesk.app.ui.components.KeyValue
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.TextInputDialog
import com.docdesk.app.ui.components.formatSize
import java.text.DateFormat
import java.util.Date
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class SortBy(val label: String) { DATE("Date (newest first)"), NAME("Name"), SIZE("Size (largest first)"), TYPE("File type") }

@Composable
fun FilesScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var refresh by remember { mutableIntStateOf(0) }
    var query by rememberSaveable { mutableStateOf("") }
    var sort by rememberSaveable { mutableStateOf(SortBy.DATE) }
    var sortMenu by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<Pair<String, NoteKind>?>(null) }
    var renaming by remember { mutableStateOf<StoredFile?>(null) }
    var deleting by remember { mutableStateOf<StoredFile?>(null) }
    var info by remember { mutableStateOf<StoredFile?>(null) }
    var protecting by remember { mutableStateOf<StoredFile?>(null) }
    var exporting by remember { mutableStateOf<StoredFile?>(null) }
    val pages = remember { mutableStateMapOf<String, String>() }

    val all = remember(refresh) { app.files.listMyFiles() }
    val shown = remember(all, query, sort) {
        all.filter { query.isBlank() || it.name.contains(query, true) }.let { l ->
            when (sort) {
                SortBy.DATE -> l.sortedByDescending { it.modified }
                SortBy.NAME -> l.sortedBy { it.name.lowercase() }
                SortBy.SIZE -> l.sortedByDescending { it.size }
                SortBy.TYPE -> l.sortedWith(compareBy({ it.type.ordinal }, { it.name.lowercase() }))
            }
        }
    }

    val importer = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        scope.launch {
            val r = withContext(Dispatchers.IO) { uris.map { runCatching { app.files.importToMyFiles(it) } } }
            val failed = r.count { it.isFailure }
            message = (if (failed == 0) "Imported ${r.size} file(s) into My Files." else "Imported ${r.size - failed}; $failed could not be copied.") to (if (failed == 0) NoteKind.INFO else NoteKind.WARNING)
            refresh++
        }
    }
    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri: Uri? ->
        val f = exporting ?: return@rememberLauncherForActivityResult
        exporting = null
        if (uri != null) scope.launch {
            message = withContext(Dispatchers.IO) { runCatching { app.files.exportTo(f.file, uri) } }
                .fold({ "Saved a copy of \"${f.name}\" to your device." to NoteKind.INFO }, { it.userMessage() to NoteKind.ERROR })
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("My Files") }, actions = {
                Box {
                    IconButton(onClick = { sortMenu = true }) { Icon(Icons.AutoMirrored.Filled.Sort, "Sort files") }
                    DropdownMenu(sortMenu, { sortMenu = false }) {
                        SortBy.entries.forEach { s -> DropdownMenuItem(text = { Text((if (s == sort) "✓ " else "") + s.label) }, onClick = { sort = s; sortMenu = false }) }
                    }
                }
            })
        },
        floatingActionButton = { ExtendedFloatingActionButton(onClick = { importer.launch(arrayOf("*/*")) }, icon = { Icon(Icons.Default.Add, null) }, text = { Text("Import") }) },
    ) { pad ->
        LazyColumn(Modifier.fillMaxSize().padding(pad), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, leadingIcon = { Icon(Icons.Default.Search, null) }, label = { Text("Search files") })
                    message?.let { (m, k) -> Notice(m, k) { message = null } }
                    Text("Files you save in DocDesk are stored privately in the app. Use \"Save to device\" or Share to put a copy elsewhere.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (shown.isEmpty()) item { Text(if (all.isEmpty()) "No files yet. Converted and edited files you save will appear here." else "No files match your search.", Modifier.padding(vertical = 24.dp)) }
            items(shown, key = { it.file.path }) { f ->
                var menu by remember { mutableStateOf(false) }
                if (f.type == DocType.PDF && pages[f.file.path] == null) LaunchedEffect(f.file.path) {
                    pages[f.file.path] = withContext(Dispatchers.IO) { runCatching { PageRenderer.open(f.file).use { "${it.pageCount} pages" } }.getOrElse { "protected" } }
                }
                ListItem(
                    headlineContent = { Text(f.name, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                    supportingContent = { Text(listOfNotNull(f.type.label, formatSize(f.size), pages[f.file.path], DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(f.modified))).joinToString(" · ")) },
                    leadingContent = { Icon(iconFor(f.type), null) },
                    trailingContent = {
                        Box {
                            IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, "Actions for ${f.name}") }
                            DropdownMenu(menu, { menu = false }) {
                                @Composable fun item(label: String, action: () -> Unit) = DropdownMenuItem(text = { Text(label) }, onClick = { menu = false; action() })
                                item("Open") { open(f, nav, context) { message = it to NoteKind.WARNING } }
                                item("Share") { runCatching { context.startActivity(app.files.shareIntent(listOf(f.file))) } }
                                item("Open with another app") { runCatching { context.startActivity(app.files.openWithIntent(f.file)) }.onFailure { message = "No app on this phone can open this file." to NoteKind.WARNING } }
                                item("Save to device…") { exporting = f; saver.launch(f.name) }
                                item("Rename") { renaming = f }
                                if (f.type == DocType.PDF) {
                                    item("Edit / annotate") { nav.to(Routes.EDIT, Uri.fromFile(f.file)) }
                                    item("Organise pages") { nav.to(Routes.ORGANIZE, Uri.fromFile(f.file)) }
                                    item("Add password") { protecting = f }
                                }
                                item("Details") { info = f }
                                item("Delete") { deleting = f }
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp).clickable { open(f, nav, context) { message = it to NoteKind.WARNING } },
                )
            }
        }
    }

    renaming?.let { f ->
        TextInputDialog("Rename file", f.name, "File name", onConfirm = { n ->
            runCatching { app.files.rename(f.file, n) }.onFailure { message = it.userMessage() to NoteKind.ERROR }
            renaming = null; refresh++
        }, onDismiss = { renaming = null })
    }
    deleting?.let { f ->
        ConfirmDialog("Delete file?", "\"${f.name}\" will be permanently deleted from My Files. Copies you saved elsewhere are not affected.", "Delete",
            onConfirm = { app.files.delete(f.file); deleting = null; refresh++ }, onDismiss = { deleting = null })
    }
    info?.let { f ->
        AlertDialog(onDismissRequest = { info = null }, confirmButton = { TextButton(onClick = { info = null }) { Text("Close") } }, title = { Text("Details") }, text = {
            Column {
                KeyValue("Name", f.name); KeyValue("Format", f.type.label); KeyValue("Size", formatSize(f.size))
                KeyValue("Modified", DateFormat.getDateTimeInstance().format(Date(f.modified)))
                pages[f.file.path]?.let { KeyValue("Pages", it) }
                KeyValue("Stored", "Privately in DocDesk")
            }
        })
    }
    protecting?.let { f -> ProtectDialog(f, onDismiss = { protecting = null }) { user, owner, print, copy, edit ->
        protecting = null
        Operations.run("Protect PDF", onError = { message = it to NoteKind.ERROR }, onResult = nav.resultCallback()) { progress ->
            progress.step("Encrypting with AES-256…", null)
            val out = app.files.newOutputFile(FileRepository.baseName(f.name) + " (protected).pdf")
            PdfDocs.open(f.file).use { doc ->
                PdfDocs.require(doc, com.docdesk.app.pdf.PdfAction.MODIFY)
                PdfOps.protect(doc, out, user, owner, print, copy, edit)
            }
            OperationResult(
                OperationReport("Protect PDF", listOf(f.name), Outcome.SUCCESS, notes = listOf(
                    "Encrypted with AES-256. Opening it requires the password you set. Very old PDF readers (before Acrobat X, 2010) may not support AES-256.",
                    "Keep the password safe: DocDesk cannot recover it.",
                )),
                listOf(OutputFile(out)), Preview.Pdf(out),
            )
        }
    } }
}

private fun open(f: StoredFile, nav: Nav, context: android.content.Context, onError: (String) -> Unit) {
    val uri = Uri.fromFile(f.file)
    when (f.type) {
        DocType.PDF -> nav.to(Routes.VIEWER, uri)
        DocType.WORD, DocType.LEGACY_WORD -> nav.to(Routes.WORD_PDF, uri)
        DocType.EXCEL, DocType.LEGACY_EXCEL -> nav.to(Routes.EXCEL_PDF, uri)
        else -> runCatching { context.startActivity(DocDeskApp.instance.files.openWithIntent(f.file).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.onFailure { onError("No app on this phone can open this file.") }
    }
}

fun iconFor(t: DocType) = when (t) {
    DocType.PDF -> Icons.Default.PictureAsPdf
    DocType.WORD, DocType.LEGACY_WORD, DocType.TEXT -> Icons.Default.Description
    DocType.EXCEL, DocType.LEGACY_EXCEL -> Icons.Default.GridOn
    DocType.IMAGE -> Icons.Default.Image
    else -> Icons.AutoMirrored.Filled.InsertDriveFile
}

@Composable
private fun ProtectDialog(f: StoredFile, onDismiss: () -> Unit, onConfirm: (String, String, Boolean, Boolean, Boolean) -> Unit) {
    var pw by remember { mutableStateOf("") }
    var pw2 by remember { mutableStateOf("") }
    var owner by remember { mutableStateOf("") }
    var print by remember { mutableStateOf(true) }
    var copy by remember { mutableStateOf(false) }
    var edit by remember { mutableStateOf(false) }
    val mismatch = pw2.isNotEmpty() && pw != pw2
    AlertDialog(
        onDismissRequest = onDismiss, title = { Text("Add password") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Creates a protected copy of \"${f.name}\". The original stays unchanged.", style = MaterialTheme.typography.bodyMedium)
                val kb = KeyboardOptions(keyboardType = KeyboardType.Password)
                OutlinedTextField(pw, { pw = it }, label = { Text("Password to open") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = kb)
                OutlinedTextField(pw2, { pw2 = it }, label = { Text("Repeat password") }, singleLine = true, isError = mismatch, visualTransformation = PasswordVisualTransformation(), keyboardOptions = kb)
                OutlinedTextField(owner, { owner = it }, label = { Text("Permissions password (optional)") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = kb,
                    supportingText = { Text("Needed to change permissions later. If left empty, a random one is used.") })
                Row { CheckRow("Allow printing", print) { print = it } }
                Row { CheckRow("Allow copying text", copy) { copy = it } }
                Row { CheckRow("Allow editing", edit) { edit = it } }
            }
        },
        confirmButton = {
            TextButton(enabled = pw.length >= 4 && pw == pw2, onClick = {
                val ownerPw = owner.ifEmpty { java.util.UUID.randomUUID().toString() }
                onConfirm(pw, ownerPw, print, copy, edit)
            }) { Text("Protect") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
