package com.docdesk.app.ui.split

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallSplit
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.pdf.PageRef
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.core.PageRanges

enum class SplitMode(val label: String, val help: String) {
    EVERY_PAGE("Every page as a separate PDF", "A 10-page file gives 10 PDFs."),
    RANGES("By custom page ranges", "Each range becomes one PDF, e.g. 1-5, 6-10, 11-15."),
    AFTER_SELECTED("Split after selected pages", "Tap pages below; a new file starts after each selected page."),
    EXTRACT("Extract selected pages into one PDF", "Tap the pages you want to keep together."),
}

@Composable
fun SplitScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    var mode by remember { mutableStateOf(SplitMode.RANGES) }
    var ranges by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(setOf<Int>()) }
    var baseName by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val info = holder.info
    val r = holder.renderer
    LaunchedEffect(holder.doc) { holder.doc?.let { baseName = FileRepository.baseName(it.name) } }

    val groups: Result<List<List<Int>>> = remember(mode, ranges, selected, info) {
        val n = info?.pageCount ?: 0
        runCatching {
            when (mode) {
                SplitMode.EVERY_PAGE -> (0 until n).map { listOf(it) }
                SplitMode.RANGES -> PageRanges.parseGroups(ranges.ifBlank { throw PageRanges.ParseException("Enter page ranges, for example 1-5, 6-10.") }, n)
                SplitMode.AFTER_SELECTED -> if (selected.isEmpty()) throw PageRanges.ParseException("Select at least one page to split after.") else PageRanges.splitAfter(selected.map { it + 1 }, n)
                SplitMode.EXTRACT -> if (selected.isEmpty()) throw PageRanges.ParseException("Select the pages to extract.") else listOf(selected.sorted())
            }
        }
    }

    ToolScaffold("Split PDF", nav::back, scroll = false) {
        LazyVerticalGrid(GridCells.Adaptive(104.dp), Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    holder.error?.let { Notice(it, NoteKind.ERROR) }
                    error?.let { Notice(it, NoteKind.ERROR) { error = null } }
                    val d = holder.doc
                    if (d == null || info == null) {
                        if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF to split", "Your original file is not changed", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
                    } else {
                        FileHeader(d.name, "${info.pageCount} pages · ${formatSize(d.size)}", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
                        RadioOptions(SplitMode.entries, mode, { it.label }, { it.help }) { mode = it }
                        if (mode == SplitMode.RANGES) OutlinedTextField(ranges, { ranges = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Page ranges") }, placeholder = { Text("1-5, 6-10, 11-${info.pageCount}") })
                        OutlinedTextField(baseName, { baseName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Output name") })
                        groups.fold(
                            { g -> Text("Creates ${g.size} PDF file${if (g.size == 1) "" else "s"}: " + g.take(4).joinToString("; ") { "pages ${PageRanges.format(it)}" } + if (g.size > 4) "; …" else "", style = MaterialTheme.typography.bodyMedium) },
                            { e -> Text(e.message ?: "", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) },
                        )
                        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
                        PrimaryAction("Split PDF", enabled = groups.isSuccess && job == null, icon = Icons.AutoMirrored.Filled.CallSplit) {
                            val g = groups.getOrThrow(); val pw = holder.password; val m = mode
                            val base = baseName.ifBlank { FileRepository.baseName(d.name) }
                            Operations.run("Split PDF", onError = { error = it }, onResult = nav.resultCallback()) { progress ->
                                PdfDocs.open(app, d.uri, pw).use { doc ->
                                    PdfDocs.require(doc, PdfAction.ASSEMBLE)
                                    val outs = g.mapIndexed { i, pages ->
                                        progress.step("Creating file ${i + 1} of ${g.size}", i.toFloat() / g.size)
                                        val name = when (m) {
                                            SplitMode.EVERY_PAGE -> "$base - page ${pages[0] + 1}.pdf"
                                            SplitMode.EXTRACT -> "$base - extracted pages.pdf"
                                            else -> "$base - part ${i + 1} (pages ${PageRanges.format(pages).replace(", ", ",")}).pdf"
                                        }
                                        val out = app.files.newOutputFile(name)
                                        PdfOps.assemble(listOf(doc), pages.map { PageRef(0, it) }, out)
                                        OutputFile(out)
                                    }
                                    OperationResult(OperationReport("Split PDF", listOf(d.name), Outcome.SUCCESS, pagesSelected = g.sumOf { it.size }, pagesProcessed = g.sumOf { it.size },
                                        notes = listOf("${outs.size} file(s) created. The original PDF was not changed.")), outs, Preview.Pdf(outs.first().file))
                                }
                            }
                        }
                        if (mode == SplitMode.AFTER_SELECTED || mode == SplitMode.EXTRACT) {
                            androidx.compose.foundation.layout.Row {
                                TextButton(onClick = { selected = (0 until info.pageCount).toSet() }) { Text("Select all") }
                                TextButton(onClick = { selected = emptySet() }) { Text("Clear selection") }
                            }
                        }
                        Text("Pages", style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
            if (r != null && info != null) items((0 until r.pageCount).toList(), key = { it }) { i ->
                val isSel = i in selected
                val selectable = mode == SplitMode.AFTER_SELECTED || mode == SplitMode.EXTRACT
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    border = if (isSel && selectable) BorderStroke(3.dp, MaterialTheme.colorScheme.primary) else BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                    modifier = Modifier.toggleable(value = isSel, enabled = selectable, role = Role.Checkbox) { on -> selected = if (on) selected + i else selected - i },
                ) {
                    Box {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            PageImage(r, i, 240, description = "Page ${i + 1}" + if (isSel) ", selected" else "")
                            Text("${i + 1}", Modifier.padding(4.dp), style = MaterialTheme.typography.labelMedium)
                        }
                        if (isSel && selectable) Icon(Icons.Default.CheckCircle, null, Modifier.align(Alignment.TopEnd).padding(4.dp), tint = MaterialTheme.colorScheme.primary)
                    }
                }
            }
        }
    }
    PasswordPromptFor(holder)
}

