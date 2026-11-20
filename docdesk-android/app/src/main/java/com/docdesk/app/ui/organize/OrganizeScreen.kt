package com.docdesk.app.ui.organize

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Redo
import androidx.compose.material.icons.automirrored.filled.RotateLeft
import androidx.compose.material.icons.automirrored.filled.RotateRight
import androidx.compose.material.icons.automirrored.filled.Undo
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.FileUpload
import androidx.compose.material.icons.filled.NoteAdd
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.SelectAll
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.AssistChip
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.data.InputDoc
import com.docdesk.app.pdf.PageRef
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.ToolScaffold
import com.tom_roush.pdfbox.pdmodel.PDDocument
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyGridState

private data class Item(val key: Long, val source: Int, val page: Int, val rotation: Int = 0)
private data class Source(val doc: InputDoc, val password: String?, val renderer: PageRenderer)

@Composable
fun OrganizeScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val main = remember { PdfInputHolder(scope) }
    val inserter = remember { PdfInputHolder(scope) }
    val sources = remember { mutableStateListOf<Source>() }
    var items by remember { mutableStateOf(listOf<Item>()) }
    var selected by remember { mutableStateOf(setOf<Long>()) }
    val undo = remember { mutableStateListOf<List<Item>>() }
    val redo = remember { mutableStateListOf<List<Item>>() }
    var nextKey by remember { mutableStateOf(1L) }
    var outName by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    DisposableEffect(Unit) { onDispose { main.close(); inserter.close(); sources.drop(1).forEach { it.renderer.close() } } }

    fun commit(new: List<Item>) { undo.add(items); if (undo.size > 50) undo.removeAt(0); redo.clear(); items = new }

    fun selectMain(u: Uri) {
        main.select(u) {
            val r = main.renderer ?: return@select
            sources.forEach { if (it.renderer !== r) it.renderer.close() }
            sources.clear(); sources.add(Source(main.doc!!, main.password, r))
            items = (0 until r.pageCount).map { Item(nextKey++, 0, it) }
            undo.clear(); redo.clear(); selected = emptySet()
            outName = FileRepository.baseName(main.doc!!.name) + " (organised)"
        }
    }
    LaunchedEffect(input) { if (input != null && main.doc == null) selectMain(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let(::selectMain) }
    val insertPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u ->
        u ?: return@rememberLauncherForActivityResult
        inserter.select(u) {
            val r = inserter.renderer ?: return@select
            // Hand the renderer over to the sources list (inserter must not close it).
            val src = Source(inserter.doc!!, inserter.password, r)
            sources.add(src)
            val idx = sources.lastIndex
            val newItems = (0 until r.pageCount).map { Item(nextKey++, idx, it) }
            val at = items.indexOfLast { it.key in selected }.let { if (it < 0) items.size else it + 1 }
            commit(items.subList(0, at) + newItems + items.subList(at, items.size))
            inserterDetach(inserter)
        }
    }

    val gridState = rememberLazyGridState()
    val reorder = rememberReorderableLazyGridState(gridState) { from, to ->
        val f = items.indexOfFirst { it.key == from.key }; val t = items.indexOfFirst { it.key == to.key }
        if (f >= 0 && t >= 0) { val l = items.toMutableList(); l.add(t, l.removeAt(f)); items = l }
    }
    var dragStart by remember { mutableStateOf<List<Item>?>(null) }

    fun rotate(deg: Int) = commit(items.map { if (it.key in selected) it.copy(rotation = (it.rotation + deg + 360) % 360) else it })
    fun move(delta: Int) {
        val l = items.toMutableList()
        val idx = l.indices.filter { l[it].key in selected }.let { if (delta > 0) it.reversed() else it }
        for (i in idx) { val j = i + delta; if (j in l.indices && l[j].key !in selected) { val x = l[i]; l[i] = l[j]; l[j] = x } }
        commit(l)
    }

    fun save(pagesToSave: List<Item>, name: String, label: String) {
        val snap = sources.map { it.doc to it.password }
        Operations.run(label, onError = { error = it }, onResult = nav.resultCallback()) { progress ->
            val docs = mutableListOf<PDDocument>()
            try {
                snap.forEach { (d, pw) -> val doc = PdfDocs.open(app, d.uri, pw); docs.add(doc); PdfDocs.require(doc, PdfAction.ASSEMBLE) }
                val out = app.files.newOutputFile("$name.pdf")
                PdfOps.assemble(docs, pagesToSave.map { PageRef(it.source, it.page, it.rotation) }, out, progress)
                OperationResult(OperationReport(label, snap.map { it.first.name }.distinct(), Outcome.SUCCESS, pagesSelected = pagesToSave.size, pagesProcessed = pagesToSave.size,
                    notes = listOf("Saved as a new file; the original PDF was not changed.")), listOf(OutputFile(out)), Preview.Pdf(out))
            } finally { docs.forEach { runCatching { it.close() } } }
        }
    }

    val hasSel = selected.isNotEmpty()
    ToolScaffold("Organise Pages", nav::back, scroll = false, actions = {
        IconButton(onClick = { redo.add(items); items = undo.removeAt(undo.lastIndex) }, enabled = undo.isNotEmpty()) { Icon(Icons.AutoMirrored.Filled.Undo, "Undo") }
        IconButton(onClick = { undo.add(items); items = redo.removeAt(redo.lastIndex) }, enabled = redo.isNotEmpty()) { Icon(Icons.AutoMirrored.Filled.Redo, "Redo") }
    }, bottomBar = {
        if (items.isNotEmpty()) BottomAppBar {
            Row(Modifier.horizontalScroll(rememberScrollState())) {
                IconButton(onClick = { selected = if (selected.size == items.size) emptySet() else items.map { it.key }.toSet() }) { Icon(Icons.Default.SelectAll, "Select all or none") }
                IconButton(onClick = { rotate(-90) }, enabled = hasSel) { Icon(Icons.AutoMirrored.Filled.RotateLeft, "Rotate selected left 90 degrees") }
                IconButton(onClick = { rotate(90) }, enabled = hasSel) { Icon(Icons.AutoMirrored.Filled.RotateRight, "Rotate selected right 90 degrees") }
                IconButton(onClick = { rotate(180) }, enabled = hasSel) { Icon(Icons.Default.Sync, "Rotate selected 180 degrees") }
                IconButton(onClick = { move(-1) }, enabled = hasSel) { Icon(Icons.Default.ChevronLeft, "Move selected earlier") }
                IconButton(onClick = { move(1) }, enabled = hasSel) { Icon(Icons.Default.ChevronRight, "Move selected later") }
                IconButton(onClick = {
                    val l = mutableListOf<Item>()
                    items.forEach { l.add(it); if (it.key in selected) l.add(it.copy(key = nextKey++)) }
                    commit(l)
                }, enabled = hasSel) { Icon(Icons.Default.ContentCopy, "Duplicate selected") }
                IconButton(onClick = {
                    if (selected.size == items.size) error = "A PDF needs at least one page. Deselect some pages first."
                    else { commit(items.filter { it.key !in selected }); selected = emptySet() }
                }, enabled = hasSel) { Icon(Icons.Default.Delete, "Delete selected") }
                IconButton(onClick = { save(items.filter { it.key in selected }, "$outName - extracted", "Extract pages") }, enabled = hasSel && job == null) { Icon(Icons.Default.FileUpload, "Extract selected into a new PDF") }
                IconButton(onClick = { insertPicker.launch(arrayOf("application/pdf")) }) { Icon(Icons.Default.NoteAdd, "Insert pages from another PDF") }
                IconButton(onClick = { save(items, outName.ifBlank { "Organised" }, "Organise pages") }, enabled = job == null) { Icon(Icons.Default.Save, "Save as new PDF") }
            }
        }
    }) {
        LazyVerticalGrid(GridCells.Adaptive(110.dp), state = gridState, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    main.error?.let { Notice(it, NoteKind.ERROR) }
                    inserter.error?.let { Notice(it, NoteKind.ERROR) { inserter.error = null } }
                    error?.let { Notice(it, NoteKind.ERROR) { error = null } }
                    if (items.isEmpty()) {
                        if (main.loading) Text("Opening…") else FilePickTarget("Choose a PDF to organise", "Reorder, rotate, delete, duplicate or extract pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
                    } else {
                        Text("Tap pages to select them. Long-press and drag a page to move it. Changes are saved as a new file.", style = MaterialTheme.typography.bodyMedium)
                        OutlinedTextField(outName, { outName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("New file name") }, suffix = { Text(".pdf") })
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            AssistChip(onClick = { save(items, outName.ifBlank { "Organised" }, "Organise pages") }, enabled = job == null, label = { Text("Save as new PDF (${items.size} pages)") }, leadingIcon = { Icon(Icons.Default.Save, null) })
                        }
                        if (hasSel) Text("${selected.size} selected", style = MaterialTheme.typography.labelLarge)
                        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
                    }
                }
            }
            items(items, key = { it.key }) { item ->
                ReorderableItem(reorder, key = item.key) { dragging ->
                    val isSel = item.key in selected
                    val src = sources.getOrNull(item.source)
                    val pos = items.indexOf(item) + 1
                    Surface(
                        shape = RoundedCornerShape(8.dp), tonalElevation = if (dragging) 8.dp else 0.dp,
                        border = if (isSel) BorderStroke(3.dp, MaterialTheme.colorScheme.primary) else BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        modifier = Modifier
                            .longPressDraggableHandle(onDragStarted = { dragStart = items }, onDragStopped = { dragStart?.let { if (it != items) { undo.add(it); redo.clear() } }; dragStart = null })
                            .clickable { selected = if (isSel) selected - item.key else selected + item.key }
                            .semantics {
                                contentDescription = "Position $pos: page ${item.page + 1}" + (if (item.source > 0) " from ${src?.doc?.name}" else "") + if (item.rotation != 0) ", rotated ${item.rotation} degrees" else ""
                                stateDescription = if (isSel) "Selected" else "Not selected"
                            },
                    ) {
                        Box {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                if (src != null) Box(Modifier.padding(6.dp)) { PageImage(src.renderer, item.page, 240, rotation = item.rotation) }
                                Text("$pos" + if (item.source > 0) " · ins." else "", Modifier.padding(bottom = 4.dp), style = MaterialTheme.typography.labelMedium)
                            }
                            if (isSel) Icon(Icons.Default.CheckCircle, null, Modifier.align(Alignment.TopEnd).padding(4.dp), tint = MaterialTheme.colorScheme.primary)
                        }
                    }
                }
            }
        }
    }
    PasswordPromptFor(main)
    PasswordPromptFor(inserter)
}

/** After insertion the renderer belongs to the sources list; forget it in the holder without closing. */
private fun inserterDetach(h: PdfInputHolder) { h.detachRenderer() }
