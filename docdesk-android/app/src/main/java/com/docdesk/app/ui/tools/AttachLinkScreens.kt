package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Undo
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.ui.unit.dp
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.data.InputDoc
import com.docdesk.app.pdf.Attachment
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfAttachments
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfLinks
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.CheckRow
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.app.ui.convert.PageSelection
import com.docdesk.app.ui.convert.selectedPages
import com.docdesk.core.FoundLink
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val MAX_ATTACH_BYTES = 100L * 1024 * 1024

/** Files attached inside a PDF: see, save out, remove, or attach new ones. */
@Composable
fun AttachmentsScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var items by remember { mutableStateOf<List<Attachment>?>(null) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var removing by remember { mutableStateOf(setOf<String>()) }
    var toAdd by remember { mutableStateOf(listOf<InputDoc>()) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableStateOf(0) }
    val adder = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        val docs = uris.map { app.files.describe(it) }
        val big = docs.filter { it.size > MAX_ATTACH_BYTES }
        if (big.isNotEmpty()) error = "${big.joinToString { it.name }}: larger than ${formatSize(MAX_ATTACH_BYTES)} – too big to attach."
        toAdd = (toAdd + docs.filter { it.size <= MAX_ATTACH_BYTES }).distinctBy { it.uri }
    }
    val d = holder.doc; val pdf = holder.info

    LaunchedEffect(d?.uri, pdf, reload) {
        items = null; selected = emptySet(); removing = emptySet(); toAdd = emptyList()
        if (d == null || pdf == null) return@LaunchedEffect
        val pw = holder.password
        withContext(Dispatchers.IO) { runCatching { PdfDocs.open(app, d.uri, pw).use { PdfAttachments.list(it) } } }
            .onSuccess { items = it }.onFailure { error = it.message ?: "Couldn't read the attachments."; items = emptyList() }
    }

    ToolScaffold("Attachments", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        if (d == null || pdf == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "See, save or add files attached inside it", Icons.Default.AttachFile) { picker.launch(arrayOf("application/pdf")) }
            Notice("PDFs can carry other files inside them – for example the Excel sheet behind a report, or supporting documents for an application. They travel with the PDF wherever it goes.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pdf.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val list = items
        if (list == null) { Text("Reading attachments…"); return@ToolScaffold }
        SectionCard(if (list.isEmpty()) "No attached files" else "${list.size} attached file(s)") {
            list.forEach { a ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(a.key in selected, { c -> selected = if (c) selected + a.key else selected - a.key })
                    Column(Modifier.weight(1f)) {
                        Text(a.name, maxLines = 1, overflow = TextOverflow.Ellipsis, textDecoration = if (a.key in removing) TextDecoration.LineThrough else null)
                        Text(listOfNotNull(a.size?.let { formatSize(it) }, a.onPage?.let { "on page ${it + 1}" }, a.description?.take(60)).joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                    }
                    val marked = a.key in removing
                    IconButton({ removing = if (marked) removing - a.key else removing + a.key }) {
                        Icon(if (marked) Icons.AutoMirrored.Filled.Undo else Icons.Default.Delete, if (marked) "Keep ${a.name}" else "Remove ${a.name}")
                    }
                }
            }
            if (list.isNotEmpty()) {
                Text("Tick files to save them to your phone; use the bin to remove a file from the PDF.", style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SecondaryAction(if (selected.isEmpty()) "Save all to My Files" else "Save ${selected.size} to My Files", enabled = job == null, icon = Icons.Default.FileDownload, modifier = Modifier.weight(1f)) {
                        val keys = if (selected.isEmpty()) list.map { it.key } else selected.toList(); val pw = holder.password
                        Operations.run("Save attachments", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                            val outs = mutableListOf<OutputFile>(); val warnings = mutableListOf<String>()
                            PdfDocs.open(app, d.uri, pw).use { doc ->
                                PdfDocs.require(doc, PdfAction.EXTRACT)
                                keys.forEachIndexed { k, key ->
                                    val a = list.first { it.key == key }
                                    p.step("Saving ${a.name}", k.toFloat() / keys.size)
                                    runCatching { val f = app.files.newOutputFile(a.name); PdfAttachments.open(doc, key).use { inp -> f.outputStream().use { inp.copyTo(it) } }; outs.add(OutputFile(f)) }
                                        .onFailure { warnings.add("${a.name}: ${it.message ?: "couldn't be read"}") }
                                }
                            }
                            OperationResult(OperationReport("Save attachments", listOf(d.name), if (warnings.isEmpty()) Outcome.SUCCESS else if (outs.isEmpty()) Outcome.FAILED else Outcome.PARTIAL,
                                warnings = warnings, notes = listOf("${outs.size} file(s) saved to My Files.", "Only open attachments from people you trust – like e-mail attachments, they can contain harmful files.")), outs)
                        }
                    }
                }
            }
        }
        SectionCard("Add files") {
            toAdd.forEach { a ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${a.name} (${formatSize(a.size)})", Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    IconButton({ toAdd = toAdd - a }) { Icon(Icons.Default.Close, "Don't attach ${a.name}") }
                }
            }
            SecondaryAction("Choose files to attach", icon = Icons.Default.AttachFile) { adder.launch(arrayOf("*/*")) }
        }
        if (removing.isNotEmpty()) Notice("The PDF copy will be saved without the ${removing.size} crossed-out file(s).", NoteKind.WARNING)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Save PDF copy", enabled = job == null && (toAdd.isNotEmpty() || removing.isNotEmpty()), icon = Icons.Default.AttachFile) {
            val pw = holder.password; val adds = toAdd; val drop = removing
            Operations.run("Attachments", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (attachments).pdf")
                var warn: String? = null; var removed = 0; val names = mutableListOf<String>()
                PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    removed = PdfAttachments.remove(doc, drop)
                    adds.forEachIndexed { k, a ->
                        p.step("Attaching ${a.name}", k.toFloat() / adds.size.coerceAtLeast(1))
                        val mime = app.contentResolver.getType(a.uri)
                        app.contentResolver.openInputStream(a.uri)!!.use { names.add(PdfAttachments.add(doc, a.name, mime, it)) }
                    }
                    warn = PdfOps.keepProtectionForSave(doc, pw)
                    PdfOps.saveAtomically(doc, out)
                }
                OperationResult(OperationReport("Attachments", listOf(d.name) + adds.map { it.name }, Outcome.SUCCESS, warnings = listOfNotNull(warn),
                    notes = listOfNotNull(names.takeIf { it.isNotEmpty() }?.let { "Attached: ${it.joinToString()}." }, if (removed > 0) "$removed file(s) removed." else null,
                        "Most PDF readers show attachments under a paperclip icon. The original is unchanged.")), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}

/** Makes web addresses, e-mails and phone numbers in the text clickable. */
@Composable
fun AutoLinkScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var web by remember { mutableStateOf(true) }; var email by remember { mutableStateOf(true) }; var phone by remember { mutableStateOf(false) }
    var allPages by remember { mutableStateOf(true) }; var range by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    ToolScaffold("Make links clickable", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val pdf = holder.info
        if (d == null || pdf == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "Turn web addresses and e-mails into links", Icons.Default.Link) { picker.launch(arrayOf("application/pdf")) }
            Notice("Many PDFs show addresses like www.example.com as plain text. DocDesk finds them and makes them tappable, without changing how the page looks.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pdf.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        SectionCard("What to link") {
            CheckRow("Web addresses (www…, https://…, example.com)", web) { web = it }
            CheckRow("E-mail addresses", email) { email = it }
            CheckRow("Phone numbers (Indian mobile, landline, 1800)", phone) { phone = it }
        }
        SectionCard("Pages") { PageSelection(pdf.pageCount, allPages, { allPages = it }, range) { range = it } }
        if (pdf.textPages.size < pdf.pageCount) Notice("${pdf.pageCount - pdf.textPages.size} page(s) are scanned images without text; run OCR first to link those.", NoteKind.WARNING)
        val pages = selectedPages(pdf.pageCount, allPages, range).getOrNull()
        val kinds = buildSet { if (web) add(FoundLink.Kind.WEB); if (email) add(FoundLink.Kind.EMAIL); if (phone) add(FoundLink.Kind.PHONE) }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create links", enabled = job == null && pages != null && kinds.isNotEmpty(), icon = Icons.Default.Link) {
            val pw = holder.password; val sel = pages!!
            Operations.run("Make links clickable", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (links).pdf")
                var warn: String? = null
                val st = PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    val s = PdfLinks.autoLink(doc, kinds, sel, p)
                    warn = PdfOps.keepProtectionForSave(doc, pw)
                    if (s.total > 0) PdfOps.saveAtomically(doc, out)
                    s
                }
                if (st.total == 0) throw com.docdesk.app.jobs.OperationFailed(
                    if (st.skippedExisting > 0) "All addresses found are already links." else "No web addresses, e-mails or phone numbers were found in the text." + if (st.pagesWithoutText > 0) " ${st.pagesWithoutText} page(s) have no text – run OCR first." else "")
                OperationResult(OperationReport("Make links clickable", listOf(d.name), Outcome.SUCCESS, pagesSelected = sel.size,
                    warnings = listOfNotNull(warn, st.pagesWithoutText.takeIf { it > 0 }?.let { "$it page(s) had no text (scans) and were skipped." }),
                    checks = listOf("Tap each link in the preview to make sure it opens the right place – addresses split across two lines are linked only on the first line."),
                    notes = listOf("Links created: ${st.web} web, ${st.email} e-mail, ${st.phone} phone." + if (st.skippedExisting > 0) " ${st.skippedExisting} already were links." else "", "The original is unchanged.")),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}
