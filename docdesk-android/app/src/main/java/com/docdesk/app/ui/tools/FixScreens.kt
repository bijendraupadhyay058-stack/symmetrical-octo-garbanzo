package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Crop
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
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
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PasswordRequiredException
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfFixes
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
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.app.ui.convert.PageSelection
import com.docdesk.app.ui.convert.selectedPages

private const val MM = 72f / 25.4f

/** Crop pages: automatic white-border removal or the same margins (mm) on every selected page. */
@Composable
fun CropScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var auto by remember { mutableStateOf(true) }
    var l by remember { mutableStateOf("10") }; var t by remember { mutableStateOf("10") }
    var r by remember { mutableStateOf("10") }; var b by remember { mutableStateOf("10") }
    var pad by remember { mutableStateOf("3") }
    var allPages by remember { mutableStateOf(true) }; var range by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    ToolScaffold("Crop pages", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info; val rend = holder.renderer
        if (d == null || info == null || rend == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF to crop", "Trim white borders or margins", Icons.Default.Crop) { picker.launch(arrayOf("application/pdf")) }
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        SectionCard("How to crop") {
            RadioOptions(listOf(true, false), auto, { if (it) "Automatically remove white borders" else "Same margins on every page" },
                { if (it) "Each page is checked separately – best for scans and photos." else "Enter how much to cut from each side, in millimetres." }) { auto = it }
            fun num(v: String) = v.replace(',', '.').toFloatOrNull()?.takeIf { it in 0f..200f }
            if (auto) OutlinedTextField(pad, { pad = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Keep a border of (mm)") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), isError = num(pad) == null)
            else {
                Row { OutlinedTextField(l, { l = it }, Modifier.weight(1f), singleLine = true, label = { Text("Left") }, isError = num(l) == null); OutlinedTextField(r, { r = it }, Modifier.weight(1f), singleLine = true, label = { Text("Right") }, isError = num(r) == null) }
                Row { OutlinedTextField(t, { t = it }, Modifier.weight(1f), singleLine = true, label = { Text("Top") }, isError = num(t) == null); OutlinedTextField(b, { b = it }, Modifier.weight(1f), singleLine = true, label = { Text("Bottom") }, isError = num(b) == null) }
                // Preview of page 1 with the crop rectangle.
                val pageSz by produceState<Pair<Int, Int>?>(null, rend) { value = runCatching { rend.pageSize(0) }.getOrNull() }
                val s = pageSz
                if (s != null && listOf(l, r, t, b).all { num(it) != null }) Box(Modifier.width(220.dp)) {
                    PageImage(rend, 0, 500, description = "Page 1 with crop area")
                    Canvas(Modifier.matchParentSize()) {
                        val sx = size.width / s.first; val sy = size.height / s.second
                        val tl = Offset(num(l)!! * MM * sx, num(t)!! * MM * sy)
                        val br = Offset(size.width - num(r)!! * MM * sx, size.height - num(b)!! * MM * sy)
                        drawRect(Color(0x55000000), Offset.Zero, Size(size.width, tl.y)); drawRect(Color(0x55000000), Offset(0f, br.y), Size(size.width, size.height - br.y))
                        drawRect(Color(0xFF1E4FA3), tl, Size(br.x - tl.x, br.y - tl.y), style = Stroke(4f))
                    }
                }
            }
        }
        SectionCard("Pages") { PageSelection(info.pageCount, allPages, { allPages = it }, range) { range = it } }
        Notice("Cropping hides the area outside the new page edges; it doesn't delete it. To remove confidential content permanently, use Find & redact or Edit › Redact.")
        val pages = selectedPages(info.pageCount, allPages, range).getOrNull()
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Crop", enabled = job == null && pages != null, icon = Icons.Default.Crop) {
            fun num(v: String) = v.replace(',', '.').toFloatOrNull()?.takeIf { it in 0f..200f }
            val manual = if (auto) null else listOf(l, t, r, b).map { num(it) ?: run { error = "Enter margins between 0 and 200 mm."; return@PrimaryAction } }.let { PdfFixes.Margins(it[0] * MM, it[1] * MM, it[2] * MM, it[3] * MM) }
            val padPt = (num(pad) ?: 3f) * MM; val pw = holder.password; val sel = pages!!
            Operations.run("Crop pages", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val margins = HashMap<Int, PdfFixes.Margins?>()
                if (manual == null) {
                    val renderer = if (info.encrypted) PageRenderer.openDecryptedCopy(app, d.uri, pw ?: "", app.files.workDir) else PageRenderer.open(app, d.uri, app.files.workDir)
                    renderer.use { rr -> sel.forEachIndexed { k, i -> p.step("Finding borders on page ${i + 1}", 0.6f * k / sel.size); margins[i] = PdfFixes.autoMargins(rr, i, padPt) } }
                }
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (cropped).pdf")
                var n = 0
                PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    n = PdfFixes.crop(doc, sel, { manual ?: margins[it] }, p)
                    PdfOps.keepProtectionForSave(doc, pw)
                    PdfOps.saveAtomically(doc, out)
                }
                OperationResult(OperationReport("Crop pages", listOf(d.name), if (n > 0) Outcome.SUCCESS else Outcome.PARTIAL, pagesSelected = sel.size, pagesProcessed = n,
                    warnings = if (n < sel.size) listOf("${sel.size - n} page(s) were left as they are (blank page, no border found, or margins too large).") else emptyList(),
                    notes = listOf("$n page(s) cropped. The original is unchanged.")), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}

/** Flatten comments, markups, stamps and form fields into the page content. */
@Composable
fun FlattenScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var error by remember { mutableStateOf<String?>(null) }
    ToolScaffold("Flatten PDF", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info
        if (d == null || info == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF to flatten", "Make comments, stamps and form answers permanent", Icons.Default.Layers) { picker.launch(arrayOf("application/pdf")) }
            Notice("Use before sending a final version: highlights, comments, stamps, drawings and filled form fields become part of the page, so they look the same in every app and can't be edited or removed. Links stay clickable.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Flatten", enabled = job == null, icon = Icons.Default.Layers) {
            val pw = holder.password
            Operations.run("Flatten PDF", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (flattened).pdf")
                val st = PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    val s = PdfFixes.flatten(doc, p)
                    PdfOps.keepProtectionForSave(doc, pw)
                    PdfOps.saveAtomically(doc, out); s
                }
                val nothing = st.annotations == 0 && st.formFields == 0
                OperationResult(OperationReport("Flatten PDF", listOf(d.name), if (nothing) Outcome.PARTIAL else Outcome.SUCCESS,
                    warnings = if (nothing) listOf("This PDF had no comments, markups or form fields to flatten.") else emptyList(),
                    notes = listOf("${st.annotations} annotation(s) and ${st.formFields} form field(s) made permanent. The original is unchanged.")), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}

/** Repair damaged PDFs. Does not need the file to open normally first. */
@Composable
fun RepairScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var doc by remember { mutableStateOf<InputDoc?>(null) }
    var needPw by remember { mutableStateOf(false) }
    var pw by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(input) { if (input != null && doc == null) doc = app.files.describe(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> doc = app.files.describe(u); needPw = false; pw = "" } }
    ToolScaffold("Repair PDF", nav::back) {
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = doc
        if (d == null) {
            FilePickTarget("Choose a damaged PDF", "For files that won't open or show errors", Icons.Default.Build) { picker.launch(arrayOf("application/pdf", "application/octet-stream", "*/*")) }
            Notice("Repair first rebuilds the PDF's internal structure, keeping text and images. If that isn't possible, pages that can still be read are rescued as images. Badly truncated downloads may lose their last pages – ask the sender for the file again if pages are missing.")
            return@ToolScaffold
        }
        FileHeader(d.name, formatSize(d.size), Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf", "application/octet-stream", "*/*")) }
        if (needPw) OutlinedTextField(pw, { pw = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("This PDF is password-protected – enter its password") },
            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Repair", enabled = job == null && (!needPw || pw.isNotEmpty()), icon = Icons.Default.Build) {
            val password = pw.ifEmpty { null }
            Operations.run("Repair PDF", onError = { msg -> if (msg.contains("password", true) && !needPw) { needPw = true; error = "Enter the PDF's password." } else error = msg }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (repaired).pdf")
                val r = try { PdfFixes.repair(app, d.uri, password, out, app.files.workDir, p) } catch (e: PasswordRequiredException) { throw com.docdesk.app.jobs.OperationFailed("This PDF needs its password.") }
                OperationResult(OperationReport("Repair PDF", listOf(d.name), Outcome.SUCCESS, pagesProcessed = r.pages,
                    notes = listOf("${r.method}. ${r.pages} page(s) in the repaired file.", "Compare it with what you expected – content that was missing from the damaged file can't be recovered.")),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
        Text("Tip: also try opening the file in the DocDesk viewer – it can often show damaged files.", style = MaterialTheme.typography.bodySmall)
    }
}
