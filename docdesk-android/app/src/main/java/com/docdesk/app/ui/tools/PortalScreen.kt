package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AspectRatio
import androidx.compose.material.icons.filled.ContentCut
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.FilterChip
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
import com.docdesk.app.pdf.FitOrientation
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PortalTools
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
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.core.PaperSize
import com.docdesk.core.SizeSplitter

enum class PortalTool(val title: String) { TARGET_SIZE("Compress to size"), SPLIT_SIZE("Split by size"), FIT_PAGES("Resize pages") }

private val sizePresets = listOf("100 KB", "200 KB", "500 KB", "1 MB", "2 MB", "5 MB", "10 MB", "25 MB")

/** Make PDFs fit upload portals: a maximum file size, parts under a size, or uniform A4/Letter pages. */
@Composable
fun PortalScreen(nav: Nav, input: Uri?, tool: PortalTool) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var sizeText by remember { mutableStateOf(if (tool == PortalTool.SPLIT_SIZE) "10 MB" else "2 MB") }
    var paper by remember { mutableStateOf(PaperSize.A4) }
    var orientation by remember { mutableStateOf(FitOrientation.AUTO) }
    var margin by remember { mutableFloatStateOf(18f) }
    var error by remember { mutableStateOf<String?>(null) }

    ToolScaffold(tool.title, nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info
        if (d == null || info == null) {
            if (holder.loading) Text("Opening…")
            else FilePickTarget("Choose a PDF", when (tool) { PortalTool.TARGET_SIZE -> "Make it small enough for an upload limit"; PortalTool.SPLIT_SIZE -> "Split into parts under a size limit"; PortalTool.FIT_PAGES -> "Put every page on A4 or Letter" },
                when (tool) { PortalTool.TARGET_SIZE -> Icons.Default.UploadFile; PortalTool.SPLIT_SIZE -> Icons.Default.ContentCut; PortalTool.FIT_PAGES -> Icons.Default.AspectRatio }) { picker.launch(arrayOf("application/pdf")) }
            Notice(when (tool) {
                PortalTool.TARGET_SIZE -> "For GST, Income Tax, bank, passport or exam portals with a maximum file size. DocDesk first shrinks images (text stays sharp and searchable). Only if that isn't enough are pages rebuilt as images at the best quality that fits – then text is no longer selectable."
                PortalTool.SPLIT_SIZE -> "For e-mail attachment limits or portals that accept several smaller files. Pages stay in order; each part is checked after saving."
                PortalTool.FIT_PAGES -> "Scans and documents of mixed sizes become uniform A4 (or Letter) pages with margins. Content is scaled, not cropped, and text stays sharp and searchable."
            })
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages · ${formatSize(d.size)}", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val limit = SizeSplitter.parseSize(sizeText)
        when (tool) {
            PortalTool.TARGET_SIZE, PortalTool.SPLIT_SIZE -> SectionCard(if (tool == PortalTool.TARGET_SIZE) "Maximum file size" else "Maximum size of each part") {
                androidx.compose.foundation.layout.FlowRow { sizePresets.forEach { p -> FilterChip(selected = sizeText == p, onClick = { sizeText = p }, label = { Text(p) }) } }
                OutlinedTextField(sizeText, { sizeText = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Size (e.g. 2 MB or 500 KB)") },
                    isError = limit == null, supportingText = { Text(if (limit == null) "Enter a size between 20 KB and 2 GB" else "Current file: ${formatSize(d.size)}") })
                if (tool == PortalTool.TARGET_SIZE && limit != null && d.size in 1..limit) Notice("This file is already within the limit.")
            }
            PortalTool.FIT_PAGES -> SectionCard("Page size") {
                RadioOptions(listOf(PaperSize.A4, PaperSize.LETTER, PaperSize.LEGAL), paper, { it.label }) { paper = it }
                RadioOptions(FitOrientation.entries, orientation, { it.label }) { orientation = it }
                Text("Margin ${margin.toInt()} pt (${"%.1f".format(margin / 72f * 25.4f)} mm)")
                Slider(margin, { margin = it }, valueRange = 0f..72f, modifier = Modifier.semantics { contentDescription = "Margin" })
            }
        }
        if (info.encrypted) Notice("The result will not be password-protected. Use Protect PDF afterwards if needed.", NoteKind.WARNING)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction(tool.title, enabled = job == null && (tool == PortalTool.FIT_PAGES || limit != null)) {
            val pw = holder.password; val enc = info.encrypted; val base = FileRepository.baseName(d.name)
            Operations.run(tool.title, onError = { error = it }, onResult = nav.resultCallback()) { p ->
                when (tool) {
                    PortalTool.TARGET_SIZE -> {
                        val r = PortalTools.compressToSize(app, d.uri, pw, enc, limit!!, { app.files.newOutputFile(it) }, app.files.workDir, p)
                        val named = java.io.File(r.file.parentFile, FileRepository.sanitize("$base (${formatSize(r.bytes).replace(" ", "")}).pdf")).also { r.file.renameTo(it) }
                        val notes = mutableListOf("${formatSize(d.size)} → ${formatSize(r.bytes)}. Method: ${r.method}.")
                        val warnings = mutableListOf<String>()
                        if (r.rasterised) warnings.add("Pages were rebuilt as images to reach the size: text can no longer be selected or searched, and small print may be less sharp. Check readability in the preview.")
                        if (!r.reached) warnings.add("Could not get below ${formatSize(limit)}; this is the smallest version possible without making the pages unreadable. Try splitting the file (Split by size) or removing pages.")
                        OperationResult(OperationReport("Compress to size", listOf(d.name), if (r.reached) Outcome.SUCCESS else Outcome.PARTIAL, warnings = warnings, notes = notes), listOf(OutputFile(named)), Preview.Pdf(named))
                    }
                    PortalTool.SPLIT_SIZE -> PdfDocs.open(app, d.uri, pw).use { doc ->
                        PdfDocs.require(doc, PdfAction.ASSEMBLE)
                        val parts = PortalTools.splitBySize(doc, limit!!, { k -> app.files.newOutputFile("$base - part $k.pdf") }, app.files.workDir, p)
                        val over = parts.filter { it.first.length() > limit }
                        val notes = parts.mapIndexed { i, (f, pages) -> "Part ${i + 1}: pages ${com.docdesk.core.PageRanges.format(pages)} – ${formatSize(f.length())}" }
                        OperationResult(OperationReport("Split by size", listOf(d.name), if (over.isEmpty()) Outcome.SUCCESS else Outcome.PARTIAL, pagesSelected = info.pageCount, pagesProcessed = info.pageCount,
                            warnings = if (over.isEmpty()) emptyList() else listOf("${over.size} single page(s) are larger than ${formatSize(limit)} on their own. Compress those parts with Compress to size."),
                            notes = listOf("${parts.size} part(s) created.") + notes), parts.map { OutputFile(it.first) }, Preview.Pdf(parts.first().first))
                    }
                    PortalTool.FIT_PAGES -> {
                        val out = app.files.newOutputFile("$base (${paper.label}).pdf")
                        PdfDocs.open(app, d.uri, pw).use { doc -> PdfDocs.require(doc, PdfAction.ASSEMBLE); PortalTools.fitPages(doc, out, paper, orientation, margin, p) }
                        OperationResult(OperationReport("Resize pages", listOf(d.name), Outcome.SUCCESS, pagesSelected = info.pageCount, pagesProcessed = info.pageCount,
                            notes = listOf("Every page now fits ${paper.label} with ${margin.toInt()} pt margins; content was scaled, not cropped.", "Links, comments and form fields from the original are not carried over.")),
                            listOf(OutputFile(out)), Preview.Pdf(out))
                    }
                }
            }
        }
    }
    PasswordPromptFor(holder)
}

