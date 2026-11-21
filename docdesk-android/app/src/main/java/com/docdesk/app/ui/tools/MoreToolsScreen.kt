package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.pdf.CompressLevel
import com.docdesk.app.pdf.HeaderFooterItem
import com.docdesk.app.pdf.NumberingOptions
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfEnhance
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.pdf.Position
import com.docdesk.app.pdf.WatermarkOptions
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.app.ui.convert.PageSelection
import com.docdesk.app.ui.convert.selectedPages
import java.time.LocalDate
import java.time.format.DateTimeFormatter

enum class MoreTool(val title: String) { WATERMARK("Add watermark"), NUMBERS("Page numbers, header & footer"), COMPRESS("Compress PDF") }

@Composable
fun MoreToolsScreen(nav: Nav, input: Uri?, tool: MoreTool) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var error by remember { mutableStateOf<String?>(null) }
    var allPages by remember { mutableStateOf(true) }
    var range by remember { mutableStateOf("") }
    // Watermark
    var wmText by remember { mutableStateOf("CONFIDENTIAL") }
    var wmOpacity by remember { mutableFloatStateOf(0.2f) }
    var wmDiagonal by remember { mutableStateOf(true) }
    var wmSize by remember { mutableFloatStateOf(60f) }
    // Numbers
    var numTemplate by remember { mutableStateOf("Page {n} of {total}") }
    var numPos by remember { mutableStateOf(Position.BOTTOM_CENTER) }
    var header by remember { mutableStateOf("") }
    var headerPos by remember { mutableStateOf(Position.TOP_RIGHT) }
    var footer by remember { mutableStateOf("") }
    var startAt by remember { mutableStateOf("1") }
    var fontSize by remember { mutableFloatStateOf(10f) }
    // Compress
    var level by remember { mutableStateOf(CompressLevel.MEDIUM) }

    ToolScaffold(tool.title, nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info
        if (d == null || info == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "A new file is created; the original stays unchanged", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
            Notice(when (tool) {
                MoreTool.WATERMARK -> "Adds text such as CONFIDENTIAL, DRAFT or COPY across every page, semi-transparent."
                MoreTool.NUMBERS -> "Adds page numbers and optional header/footer text. Use {n} for the page number, {total} for the page count, {date}, {file}, and {n:4} for Bates numbering like INV-0001."
                MoreTool.COMPRESS -> "Makes PDFs smaller by reducing the resolution and quality of large photos and scans. Text stays sharp. Best for scanned documents and PDFs with photos."
            })
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages · ${formatSize(d.size)}", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val pages = selectedPages(info.pageCount, allPages, range).getOrNull()
        when (tool) {
            MoreTool.WATERMARK -> SectionCard("Watermark") {
                OutlinedTextField(wmText, { wmText = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Text") })
                Text("Size ${wmSize.toInt()} pt"); Slider(wmSize, { wmSize = it }, valueRange = 20f..120f, modifier = Modifier.semantics { contentDescription = "Watermark size" })
                Text("Opacity ${(wmOpacity * 100).toInt()}%"); Slider(wmOpacity, { wmOpacity = it }, valueRange = 0.05f..0.6f, modifier = Modifier.semantics { contentDescription = "Watermark opacity" })
                SwitchRow("Diagonal", wmDiagonal) { wmDiagonal = it }
            }
            MoreTool.NUMBERS -> {
                SectionCard("Page numbers") {
                    OutlinedTextField(numTemplate, { numTemplate = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Format (empty = none)") }, supportingText = { Text("{n} page, {total} pages, {n:4} = 0001") })
                    RadioOptions(Position.entries, numPos, { it.label }) { numPos = it }
                    OutlinedTextField(startAt, { startAt = it.filter(Char::isDigit).take(6) }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Start numbering at") })
                }
                SectionCard("Header and footer (optional)") {
                    OutlinedTextField(header, { header = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Header text") }, placeholder = { Text("e.g. ACME Pvt Ltd – FY 2024-25") })
                    if (header.isNotBlank()) RadioOptions(listOf(Position.TOP_LEFT, Position.TOP_CENTER, Position.TOP_RIGHT), headerPos, { it.label }) { headerPos = it }
                    OutlinedTextField(footer, { footer = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Footer text (bottom left)") }, placeholder = { Text("e.g. Confidential · {date}") })
                    Text("Text size ${fontSize.toInt()} pt"); Slider(fontSize, { fontSize = it }, valueRange = 6f..20f, modifier = Modifier.semantics { contentDescription = "Text size" })
                }
            }
            MoreTool.COMPRESS -> SectionCard("Compression") {
                RadioOptions(CompressLevel.entries, level, { it.label }) { level = it }
                Text("Photos are re-encoded as JPEG at up to ${level.maxSide} px. Images with transparency and black-and-white scans are kept as they are.", style = MaterialTheme.typography.bodySmall)
            }
        }
        if (tool != MoreTool.COMPRESS) SectionCard("Pages") { PageSelection(info.pageCount, allPages, { allPages = it }, range) { range = it } }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create new PDF", enabled = job == null && (tool == MoreTool.COMPRESS || pages != null)) {
            val pw = holder.password; val sel = pages ?: (0 until info.pageCount).toList()
            val wm = WatermarkOptions(wmText.ifBlank { "CONFIDENTIAL" }, wmSize, wmOpacity, wmDiagonal)
            val date = LocalDate.now().format(DateTimeFormatter.ofPattern("dd-MM-yyyy"))
            val items = buildList {
                if (numTemplate.isNotBlank()) add(HeaderFooterItem(numTemplate, numPos))
                if (header.isNotBlank()) add(HeaderFooterItem(header, headerPos))
                if (footer.isNotBlank()) add(HeaderFooterItem(footer, if (numPos == Position.BOTTOM_LEFT) Position.BOTTOM_RIGHT else Position.BOTTOM_LEFT))
            }
            if (tool == MoreTool.NUMBERS && items.isEmpty()) { error = "Enter a page-number format, header or footer."; return@PrimaryAction }
            val num = NumberingOptions(items, startAt.toIntOrNull() ?: 1, fontSize, fileName = d.name, date = date)
            val lvl = level
            val suffix = when (tool) { MoreTool.WATERMARK -> "watermarked"; MoreTool.NUMBERS -> "numbered"; MoreTool.COMPRESS -> "compressed" }
            Operations.run(tool.title, onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile("${FileRepository.baseName(d.name)} ($suffix).pdf")
                val notes = mutableListOf("Saved as a new file; the original was not changed.")
                val warnings = mutableListOf<String>()
                var outcome = Outcome.SUCCESS
                PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    when (tool) {
                        MoreTool.WATERMARK -> { PdfEnhance.watermark(doc, sel, wm, p); notes.add("Watermark added to ${sel.size} page(s). It is part of the page content and cannot be removed easily.") }
                        MoreTool.NUMBERS -> { val img = PdfEnhance.numbering(doc, sel, num, p); notes.add("Added to ${sel.size} page(s)."); if (img > 0) warnings.add("Text with non-English characters was added as images ($img).") }
                        MoreTool.COMPRESS -> {
                            val st = PdfEnhance.compress(doc, lvl, p)
                            notes.add("${st.imagesRecompressed} of ${st.imagesSeen} image(s) recompressed.")
                        }
                    }
                    PdfOps.keepProtectionForSave(doc, pw)?.let { notes.add(it) }
                    p.step("Saving…", 0.95f)
                    PdfOps.saveAtomically(doc, out)
                }
                if (tool == MoreTool.COMPRESS) {
                    val before = d.size; val after = out.length()
                    if (before > 0) {
                        val pct = ((1 - after.toDouble() / before) * 100).toInt()
                        if (after >= before) { outcome = Outcome.PARTIAL; warnings.add("The file could not be made smaller (${formatSize(before)} → ${formatSize(after)}). It is probably mostly text or already optimised – keep the original.") }
                        else notes.add(0, "Size: ${formatSize(before)} → ${formatSize(after)} ($pct% smaller).")
                    }
                }
                OperationResult(OperationReport(tool.title, listOf(d.name), outcome, pagesSelected = sel.size, pagesProcessed = sel.size, warnings = warnings, notes = notes), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}
