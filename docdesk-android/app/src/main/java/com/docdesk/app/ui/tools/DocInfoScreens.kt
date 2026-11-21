package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.FormatIndentDecrease
import androidx.compose.material.icons.automirrored.filled.FormatIndentIncrease
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Bookmarks
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.pdf.Bookmarks
import com.docdesk.app.pdf.DocProperties
import com.docdesk.app.pdf.DocProps
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.ConfirmDialog
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.KeyValue
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.HeadingFinder
import com.docdesk.core.Outline
import com.docdesk.core.OutlineEntry
import com.docdesk.core.TextSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.DateFormat

private const val SHOW_MAX = 300

/** Add, rename, reorder, nest and delete bookmarks, or create them automatically from headings. */
@Composable
fun BookmarksScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var items by remember { mutableStateOf<List<OutlineEntry>?>(null) }
    var original by remember { mutableStateOf<List<OutlineEntry>>(emptyList()) }
    var busy by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var confirmClear by remember { mutableStateOf(false) }
    var rev by remember { mutableStateOf(0) } // bumps to reset text fields after structural edits
    val d = holder.doc; val pdf = holder.info

    LaunchedEffect(d?.uri, pdf) {
        items = null
        if (d == null || pdf == null) return@LaunchedEffect
        val pw = holder.password
        val read = withContext(Dispatchers.IO) { runCatching { PdfDocs.open(app, d.uri, pw).use { Bookmarks.readEntries(it) } } }
        read.onSuccess { items = it; original = it; rev++ }.onFailure { error = it.message ?: "Couldn't read the bookmarks."; items = emptyList() }
    }

    fun auto(perPage: Boolean) {
        val doc = d ?: return; val pw = holder.password
        busy = if (perPage) "Reading pages…" else "Looking for headings…"
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching {
                    PdfDocs.open(app, doc.uri, pw).use { pd ->
                        val pages = (0 until pd.numberOfPages).map { PdfTextExtractor.extract(pd, it) }
                        val noText = pages.count { it.source == TextSource.NONE || it.words.isEmpty() }
                        Pair(if (perPage) HeadingFinder.perPage(pages) else HeadingFinder.find(pages), noText)
                    }
                }
            }
            busy = null
            r.onSuccess { (found, noText) ->
                if (found.isEmpty()) error = if (noText > 0) "No headings found. $noText page(s) have no text layer (scans) – run OCR first, or add bookmarks by hand." else "No headings found – the text is all one size. Try “One per page” or add bookmarks by hand."
                else { items = found; rev++; info = "${found.size} bookmark(s) created. Check them, then tap Save." + if (noText > 0) " $noText scanned page(s) without text were skipped." else "" }
            }.onFailure { error = it.message ?: "Couldn't read the text." }
        }
    }

    ToolScaffold("Bookmarks", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        if (d == null || pdf == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "Add or edit its bookmarks (table of contents)", Icons.Default.Bookmarks) { picker.launch(arrayOf("application/pdf")) }
            Notice("Bookmarks appear in the side panel of PDF readers and let people jump straight to a chapter. DocDesk can create them from the document's headings.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pdf.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val list = items
        if (list == null) { Text("Reading bookmarks…"); return@ToolScaffold }
        info?.let { Notice(it) { info = null } }
        SectionCard("Create automatically") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SecondaryAction("From headings", enabled = busy == null, icon = Icons.Default.AutoAwesome, modifier = Modifier.weight(1f)) { auto(false) }
                SecondaryAction("One per page", enabled = busy == null, modifier = Modifier.weight(1f)) { auto(true) }
            }
            busy?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
            Text("This replaces the list below. Nothing is saved until you tap Save.", style = MaterialTheme.typography.bodySmall)
        }
        SectionCard(if (list.isEmpty()) "No bookmarks yet" else "${list.size} bookmark(s)") {
            if (list.size > SHOW_MAX) Notice("Showing the first $SHOW_MAX for editing; the rest are kept as they are.")
            list.take(SHOW_MAX).forEachIndexed { i, e ->
                key(rev, i) {
                    var title by remember { mutableStateOf(e.title) }
                    var page by remember { mutableStateOf((e.page + 1).toString()) }
                    val pageOk = page.toIntOrNull()?.let { it in 1..pdf.pageCount } == true
                    Row(Modifier.fillMaxWidth().padding(start = (e.level * 16).dp), verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(title, { title = it; items = items?.toMutableList()?.also { l -> l[i] = l[i].copy(title = it) } },
                            Modifier.weight(1f), singleLine = true, label = { Text(if (e.level == 0) "Title" else "Sub-level ${e.level}") }, isError = title.isBlank())
                        OutlinedTextField(page, { v -> page = v.filter { it.isDigit() }.take(5); page.toIntOrNull()?.let { p -> if (p in 1..pdf.pageCount) items = items?.toMutableList()?.also { l -> l[i] = l[i].copy(page = p - 1) } } },
                            Modifier.width(76.dp), singleLine = true, label = { Text("Page") }, isError = !pageOk, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                    }
                    Row(Modifier.padding(start = (e.level * 16).dp)) {
                        IconButton({ items = Outline.move(list, i, up = true); rev++ }, enabled = i > 0) { Icon(Icons.Default.KeyboardArrowUp, "Move up") }
                        IconButton({ items = Outline.move(list, i, up = false); rev++ }, enabled = i < list.size - 1) { Icon(Icons.Default.KeyboardArrowDown, "Move down") }
                        IconButton({ items = Outline.shift(list, i, -1); rev++ }, enabled = e.level > 0) { Icon(Icons.AutoMirrored.Filled.FormatIndentDecrease, "Make higher level") }
                        IconButton({ items = Outline.shift(list, i, +1); rev++ }, enabled = i > 0 && e.level <= list[i - 1].level) { Icon(Icons.AutoMirrored.Filled.FormatIndentIncrease, "Make sub-level") }
                        IconButton({ items = Outline.remove(list, i); rev++ }) { Icon(Icons.Default.Delete, "Delete bookmark") }
                    }
                    HorizontalDivider()
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SecondaryAction("Add bookmark", icon = Icons.Default.Add, modifier = Modifier.weight(1f)) {
                    val lastPage = list.lastOrNull()?.page?.let { (it + 1).coerceAtMost(pdf.pageCount - 1) } ?: 0
                    items = list + OutlineEntry("New bookmark", list.lastOrNull()?.level ?: 0, lastPage); rev++
                }
                if (list.isNotEmpty()) SecondaryAction("Remove all", icon = Icons.Default.Delete, modifier = Modifier.weight(1f)) { confirmClear = true }
            }
        }
        val valid = list.all { it.title.isNotBlank() && it.page in 0 until pdf.pageCount }
        if (!valid) Notice("Every bookmark needs a title and a page between 1 and ${pdf.pageCount}.", NoteKind.WARNING)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Save", enabled = job == null && valid && busy == null && list != original, icon = Icons.Default.Bookmarks) {
            val pw = holder.password; val toSave = list
            Operations.run("Bookmarks", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                p.step("Writing bookmarks", 0.3f)
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (bookmarks).pdf")
                var warn: String? = null
                PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    // Entries past SHOW_MAX weren't shown but are part of the list, so they are saved unchanged.
                    Bookmarks.write(doc, toSave, openPanel = toSave.isNotEmpty())
                    warn = PdfOps.keepProtectionForSave(doc, pw)
                    PdfOps.saveAtomically(doc, out)
                }
                OperationResult(OperationReport("Bookmarks", listOf(d.name), Outcome.SUCCESS, warnings = listOfNotNull(warn),
                    notes = listOf(if (toSave.isEmpty()) "All bookmarks removed." else "${toSave.size} bookmark(s) saved. The bookmarks panel opens automatically in most PDF readers.", "The original is unchanged.")),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    if (confirmClear) ConfirmDialog("Remove all bookmarks?", "The list is cleared. Nothing changes in the file until you tap Save.", "Remove all", { items = emptyList(); rev++; confirmClear = false }, { confirmClear = false })
    PasswordPromptFor(holder)
}

/** View and edit title, author, subject and keywords, or remove all hidden information. */
@Composable
fun PropertiesScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var props by remember { mutableStateOf<DocProps?>(null) }
    var title by remember { mutableStateOf("") }; var author by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("") }; var keywords by remember { mutableStateOf("") }
    var creator by remember { mutableStateOf("") }
    var strip by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val d = holder.doc; val pdf = holder.info

    LaunchedEffect(d?.uri, pdf) {
        props = null
        if (d == null || pdf == null) return@LaunchedEffect
        val pw = holder.password
        withContext(Dispatchers.IO) { runCatching { PdfDocs.open(app, d.uri, pw).use { DocProperties.read(it) } } }
            .onSuccess { props = it; title = it.title; author = it.author; subject = it.subject; keywords = it.keywords; creator = it.creator }
            .onFailure { error = it.message ?: "Couldn't read the properties." }
    }

    ToolScaffold("Document properties", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        if (d == null || pdf == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "See and change its title, author and keywords", Icons.Default.Info) { picker.launch(arrayOf("application/pdf")) }
            Notice("PDFs carry hidden information such as the author's name, the program that made them and dates. Check it before sharing, change it, or remove it all.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pdf.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val p = props
        if (p == null) { Text("Reading properties…"); return@ToolScaffold }
        SectionCard("Remove everything") {
            SwitchRow("Remove all hidden information", strip, "Clears author, title, program names, dates, XMP metadata and page thumbnails. Page content is not changed.") { strip = it }
        }
        if (!strip) SectionCard("Description") {
            OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Title") })
            OutlinedTextField(author, { author = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Author") })
            OutlinedTextField(subject, { subject = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Subject") })
            OutlinedTextField(keywords, { keywords = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Keywords (separate with commas)") })
            OutlinedTextField(creator, { creator = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Created with (application)") })
            Text("Leave a field empty to remove it. The title is shown instead of the file name in most PDF readers.", style = MaterialTheme.typography.bodySmall)
        }
        SectionCard("Other information") {
            val fmt = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
            KeyValue("Produced by", p.producer.ifEmpty { "—" })
            KeyValue("Created", p.created?.let { fmt.format(it.time) } ?: "—")
            KeyValue("Modified", p.modified?.let { fmt.format(it.time) } ?: "—")
            KeyValue("XMP metadata", if (p.hasXmp) "Yes" else "No")
            if (p.customKeys.isNotEmpty()) KeyValue("Other fields", p.customKeys.joinToString(", ").take(200))
        }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction(if (strip) "Remove and save" else "Save", enabled = job == null, icon = Icons.Default.Info) {
            val pw = holder.password
            val edited = DocProps(title, author, subject, keywords, creator)
            Operations.run("Document properties", onError = { error = it }, onResult = nav.resultCallback()) { pr ->
                pr.step("Saving", 0.3f)
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + if (strip) " (clean).pdf" else ".pdf")
                var warn: String? = null; var removed = 0
                PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    if (strip) removed = DocProperties.stripAll(doc) else DocProperties.write(doc, edited)
                    warn = PdfOps.keepProtectionForSave(doc, pw)
                    PdfOps.saveAtomically(doc, out)
                }
                OperationResult(OperationReport("Document properties", listOf(d.name), Outcome.SUCCESS, warnings = listOfNotNull(warn),
                    notes = listOf(if (strip) "$removed hidden item(s) removed." else "Properties saved.", "The original is unchanged.")),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}
