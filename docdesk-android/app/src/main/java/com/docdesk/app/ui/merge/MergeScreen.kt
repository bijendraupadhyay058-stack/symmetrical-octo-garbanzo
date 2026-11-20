package com.docdesk.app.ui.merge

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CallMerge
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.InputDoc
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PageRef
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PasswordRequiredException
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PasswordDialog
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.PageRanges
import com.tom_roush.pdfbox.pdmodel.PDDocument
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState

private class MergeItem(val id: Long, val doc: InputDoc) {
    var password by mutableStateOf<String?>(null)
    var pages by mutableStateOf<Int?>(null)
    var needsPassword by mutableStateOf<Boolean?>(null)
    var error by mutableStateOf<String?>(null)
    var range by mutableStateOf("all")
    var renderer by mutableStateOf<PageRenderer?>(null)
}

@Composable
fun MergeScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val items = remember { mutableStateListOf<MergeItem>() }
    var nextId by remember { mutableStateOf(1L) }
    var outName by remember { mutableStateOf("Merged document") }
    var error by remember { mutableStateOf<String?>(null) }
    var preview by remember { mutableStateOf(false) }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    DisposableEffect(Unit) { onDispose { items.forEach { it.renderer?.close() } } }

    fun inspect(item: MergeItem) = scope.launch {
        try {
            val (n, _) = withContext(Dispatchers.IO) { PdfDocs.open(app, item.doc.uri, item.password).use { PdfDocs.require(it, PdfAction.ASSEMBLE); it.numberOfPages to it.isEncrypted } }
            item.pages = n; item.needsPassword = null; item.error = null
        } catch (e: PasswordRequiredException) { item.needsPassword = e.wrongPassword } catch (e: Throwable) { item.error = e.userMessage() }
    }

    fun add(uris: List<Uri>) {
        for (u in uris) {
            val d = app.files.describe(u)
            if (!d.name.endsWith(".pdf", true) && d.type != com.docdesk.app.data.DocType.PDF) { error = "\"${d.name}\" is not a PDF and was skipped."; continue }
            val it = MergeItem(nextId++, d); items.add(it); inspect(it)
        }
    }
    LaunchedEffect(input) { if (input != null && items.isEmpty()) add(listOf(input)) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { add(it) }

    val listState = rememberLazyListState()
    val reorder = rememberReorderableLazyListState(listState) { from, to ->
        // Offset 1 for the header item at the top of the list.
        val f = from.index - 1; val t = to.index - 1
        if (f in items.indices && t in items.indices) items.add(t, items.removeAt(f))
    }

    fun rangeOf(item: MergeItem): Result<List<Int>> = runCatching { PageRanges.parse(item.range, item.pages ?: 0) }
    val totalPages = items.sumOf { rangeOf(it).getOrNull()?.size ?: 0 }
    val ready = items.size >= 2 && items.all { it.pages != null && rangeOf(it).isSuccess }

    ToolScaffold("Merge PDFs", nav::back, scroll = false) {
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item(key = "header") {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Add two or more PDFs. Drag the handle (or use the arrows) to change the order. You can choose which pages to take from each file.", style = MaterialTheme.typography.bodyMedium)
                    error?.let { Notice(it, NoteKind.WARNING) { error = null } }
                    SecondaryAction("Add PDF files", icon = Icons.Default.Add) { picker.launch(arrayOf("application/pdf")) }
                }
            }
            items(items, key = { it.id }) { item ->
                ReorderableItem(reorder, key = item.id) { dragging ->
                    Card(colors = CardDefaults.cardColors(containerColor = if (dragging) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainerLow)) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                IconButton(onClick = {}, modifier = Modifier.draggableHandle()) { Icon(Icons.Default.DragHandle, "Drag to reorder ${item.doc.name}") }
                                Column(Modifier.weight(1f)) {
                                    Text("${items.indexOf(item) + 1}. ${item.doc.name}", style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    Text(when { item.error != null -> item.error!!; item.needsPassword != null -> "Password required"; item.pages == null -> "Checking…"; else -> "${item.pages} pages" + if (item.password != null) " · unlocked" else "" },
                                        style = MaterialTheme.typography.bodySmall, color = if (item.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                val idx = items.indexOf(item)
                                IconButton(onClick = { items.add(idx - 1, items.removeAt(idx)) }, enabled = idx > 0) { Icon(Icons.Default.KeyboardArrowUp, "Move ${item.doc.name} up") }
                                IconButton(onClick = { items.add(idx + 1, items.removeAt(idx)) }, enabled = idx < items.lastIndex) { Icon(Icons.Default.KeyboardArrowDown, "Move ${item.doc.name} down") }
                                IconButton(onClick = { item.renderer?.close(); items.remove(item) }) { Icon(Icons.Default.Delete, "Remove ${item.doc.name}") }
                            }
                            if (item.pages != null) {
                                val r = rangeOf(item)
                                OutlinedTextField(item.range, { item.range = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Pages to include (e.g. all, 1-3, 5)") },
                                    isError = r.isFailure, supportingText = { Text(r.exceptionOrNull()?.message ?: "${r.getOrNull()?.size ?: 0} page(s) selected") })
                            }
                        }
                    }
                }
            }
            item(key = "footer") {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (items.size >= 2) {
                        Text("Result: $totalPages pages from ${items.size} files", style = MaterialTheme.typography.titleMedium)
                        SwitchRow("Preview final page order", preview) { on ->
                            preview = on
                            if (on) items.filter { it.renderer == null && it.pages != null }.forEach { item ->
                                scope.launch {
                                    item.renderer = withContext(Dispatchers.IO) { runCatching {
                                        if (item.password != null) PageRenderer.openDecryptedCopy(app, item.doc.uri, item.password!!, app.files.workDir) else PageRenderer.open(app, item.doc.uri, app.files.workDir)
                                    }.getOrNull() }
                                }
                            }
                        }
                        if (preview) {
                            val order = items.flatMap { it2 -> (rangeOf(it2).getOrNull() ?: emptyList()).map { p -> it2 to p } }
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                items(order.size) { k ->
                                    val (it2, p) = order[k]
                                    Column(Modifier.width(90.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                        it2.renderer?.let { rr -> PageImage(rr, p, 180, description = "Output page ${k + 1}: ${it2.doc.name} page ${p + 1}") } ?: Text("…")
                                        Text("${k + 1}", style = MaterialTheme.typography.labelSmall)
                                    }
                                }
                            }
                        }
                    }
                    OutlinedTextField(outName, { outName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Output file name") }, suffix = { Text(".pdf") })
                    job?.let { JobProgressCard(it) { app.jobs.cancel() } }
                    PrimaryAction("Merge ${items.size} files", enabled = ready && job == null, icon = Icons.Default.CallMerge) {
                        val snapshot = items.map { Triple(it.doc, it.password, rangeOf(it).getOrThrow()) }
                        val name = outName.ifBlank { "Merged document" } + ".pdf"
                        Operations.run("Merge PDFs", onError = { error = it }, onResult = nav.resultCallback()) { progress ->
                            val docs = mutableListOf<PDDocument>()
                            try {
                                snapshot.forEachIndexed { i, (d, pw, _) ->
                                    progress.step("Opening ${d.name}", i.toFloat() / snapshot.size * 0.3f)
                                    val doc = PdfDocs.open(app, d.uri, pw); docs.add(doc); PdfDocs.require(doc, PdfAction.ASSEMBLE)
                                }
                                val refs = snapshot.flatMapIndexed { i, (_, _, pages) -> pages.map { PageRef(i, it) } }
                                val out = app.files.newOutputFile(name)
                                PdfOps.assemble(docs, refs, out, progress)
                                val notes = mutableListOf<String>()
                                if (snapshot.any { it.second != null }) notes.add("Some source files were password-protected. The merged PDF is NOT protected; use Files › Add password if needed.")
                                notes.add("Bookmarks, form fields and links from the source files are not carried over.")
                                OperationResult(OperationReport("Merge PDFs", snapshot.map { it.first.name }, Outcome.SUCCESS, pagesSelected = refs.size, pagesProcessed = refs.size, notes = notes), listOf(OutputFile(out)), Preview.Pdf(out))
                            } finally { docs.forEach { runCatching { it.close() } } }
                        }
                    }
                }
            }
        }
    }
    items.firstOrNull { it.needsPassword != null }?.let { item ->
        PasswordDialog(item.doc.name, wrong = item.needsPassword == true, onSubmit = { pw -> item.password = pw; item.needsPassword = null; inspect(item) }, onDismiss = { items.remove(item) })
    }
}
