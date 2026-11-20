package com.docdesk.app.ui.create

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.NoteAdd
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.DocToPdfRenderer
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.Preview
import com.docdesk.app.convert.SheetToPdfRenderer
import com.docdesk.app.data.DocType
import com.docdesk.app.data.FileRepository
import com.docdesk.app.data.InputDoc
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.Progress
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PageRef
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.scan.ImageLoader
import com.docdesk.app.scan.ScanPdfBuilder
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.app.ui.files.iconFor
import com.docdesk.core.DocxReader
import com.docdesk.core.Orientation
import com.docdesk.core.PaperSize
import com.docdesk.core.Scaling
import com.docdesk.core.SheetPrintOptions
import com.docdesk.core.XlsxReader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import java.io.File

class CreatePdfVm : ViewModel() {
    val files = mutableStateListOf<InputDoc>()
    var combine by mutableStateOf(true)
    var name by mutableStateOf("Combined document")
    var excelLandscape by mutableStateOf(false)
    var paper by mutableStateOf(PaperSize.A4)
    var error by mutableStateOf<String?>(null)
    var consumedPending = false
}

private val ACCEPTED = setOf(DocType.WORD, DocType.EXCEL, DocType.IMAGE, DocType.PDF)

/**
 * "Create PDF": turn Word, Excel and image files (and existing PDFs) into PDF – each as its own
 * file or combined into one PDF in the order shown.
 */
@Composable
fun CreatePdfScreen(nav: Nav, input: Uri?) {
    val vm: CreatePdfVm = viewModel()
    val app = DocDeskApp.instance
    val job by app.jobs.state.collectAsStateWithLifecycle()

    fun add(uris: List<Uri>) {
        val skipped = mutableListOf<String>()
        for (u in uris) {
            val d = app.files.describe(u)
            when {
                d.type in ACCEPTED -> vm.files.add(d)
                d.type == DocType.LEGACY_WORD || d.type == DocType.LEGACY_EXCEL -> skipped.add("${d.name} (old ${d.type.label} format – save it as .docx/.xlsx first)")
                else -> skipped.add("${d.name} (unsupported type)")
            }
        }
        if (skipped.isNotEmpty()) vm.error = "Skipped: " + skipped.joinToString("; ")
        if (vm.files.size == 1) vm.name = FileRepository.baseName(vm.files[0].name)
    }
    LaunchedEffect(input) {
        if (!vm.consumedPending) {
            vm.consumedPending = true
            val pending = app.takePendingInputs()
            when { pending.isNotEmpty() -> add(pending); input != null -> add(listOf(input)) }
        }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { add(it) }
    val mimes = arrayOf(DocType.WORD.mime, DocType.EXCEL.mime, "image/*", "application/pdf", DocType.LEGACY_WORD.mime, DocType.LEGACY_EXCEL.mime)

    ToolScaffold("Create PDF", nav::back) {
        vm.error?.let { Notice(it, NoteKind.WARNING) { vm.error = null } }
        if (vm.files.isEmpty()) {
            FilePickTarget("Choose Word, Excel or photo files", "Convert each to PDF, or combine them into one PDF", Icons.Default.NoteAdd) { picker.launch(mimes) }
            Notice("Supported: Word (.docx), Excel (.xlsx), photos (JPG/PNG) and PDFs. Tip: in WhatsApp, Gmail or Files, use Share › DocDesk to send files here directly.")
            return@ToolScaffold
        }
        SectionCard("${vm.files.size} file(s) – in this order") {
            vm.files.forEachIndexed { i, d ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(iconFor(d.type), null)
                    Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                        Text("${i + 1}. ${d.name}", style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text("${d.type.label} · ${formatSize(d.size)}", style = MaterialTheme.typography.bodySmall)
                    }
                    IconButton(onClick = { vm.files.add(i - 1, vm.files.removeAt(i)) }, enabled = i > 0) { Icon(Icons.Default.KeyboardArrowUp, "Move ${d.name} up") }
                    IconButton(onClick = { vm.files.add(i + 1, vm.files.removeAt(i)) }, enabled = i < vm.files.lastIndex) { Icon(Icons.Default.KeyboardArrowDown, "Move ${d.name} down") }
                    IconButton(onClick = { vm.files.removeAt(i) }) { Icon(Icons.Default.Delete, "Remove ${d.name}") }
                }
            }
            SecondaryAction("Add more files", icon = Icons.Default.Add) { picker.launch(mimes) }
        }
        if (vm.files.size > 1) SectionCard("Output") {
            RadioOptions(listOf(true, false), vm.combine, { if (it) "Combine into one PDF" else "A separate PDF for each file" }) { vm.combine = it }
        }
        SectionCard("Page setup") {
            Text("Paper for Excel and photos", style = MaterialTheme.typography.labelLarge)
            RadioOptions(listOf(PaperSize.A4, PaperSize.LETTER), vm.paper, { it.label }) { vm.paper = it }
            if (vm.files.any { it.type == DocType.EXCEL }) RadioOptions(listOf(false, true), vm.excelLandscape, { if (it) "Excel sheets in landscape" else "Excel sheets in portrait" }) { vm.excelLandscape = it }
            Text("Word files keep their own page size. Excel sheets are scaled to fit all columns on the page width. For more Excel options (print area, margins, scaling) use the Excel to PDF tool.", style = MaterialTheme.typography.bodySmall)
        }
        if (vm.combine && vm.files.size > 1 || vm.files.size == 1) OutlinedTextField(vm.name, { vm.name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") }, suffix = { Text(".pdf") })
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create PDF", enabled = job == null, icon = Icons.Default.PictureAsPdf) {
            val files = vm.files.toList(); val combine = vm.combine || files.size == 1; val name = vm.name.ifBlank { "Document" }
            val print = SheetPrintOptions(orientation = if (vm.excelLandscape) Orientation.LANDSCAPE else Orientation.PORTRAIT, paper = vm.paper, scaling = Scaling.FIT_COLUMNS)
            val paper = vm.paper
            Operations.run("Create PDF", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                val made = mutableListOf<Pair<InputDoc, File>>()
                val failed = mutableListOf<PageIssue>()
                val warnings = mutableListOf<String>()
                // Consecutive images become one multi-page section.
                var i = 0
                while (i < files.size) {
                    val d = files[i]
                    p.step("Converting ${d.name} (${i + 1} of ${files.size})", i.toFloat() / files.size * 0.85f)
                    try {
                        if (d.type == DocType.IMAGE) {
                            val group = files.drop(i).takeWhile { it.type == DocType.IMAGE }.let { if (combine) it else listOf(d) }
                            val out = app.files.newOutputFile(FileRepository.baseName(d.name) + ".pdf")
                            imagesToPdf(group, paper, out, p)
                            group.forEach { g -> made.add(g to out) }
                            i += group.size; continue
                        }
                        val out = app.files.newOutputFile(FileRepository.baseName(d.name) + ".pdf")
                        when (d.type) {
                            DocType.WORD -> {
                                val doc = app.contentResolver.openInputStream(d.uri)?.use { DocxReader.read(it) } ?: throw OperationFailed("Could not open ${d.name}.")
                                DocToPdfRenderer(doc, pageNumbers = false).render(out, null)
                                if (doc.unsupported.isNotEmpty()) warnings.add("${d.name}: not fully reproduced – " + doc.unsupported.keys.joinToString())
                            }
                            DocType.EXCEL -> {
                                val wb = app.contentResolver.openInputStream(d.uri)?.use { XlsxReader.read(it) } ?: throw OperationFailed("Could not open ${d.name}.")
                                val sheets = wb.sheets.filter { !it.hidden && it.maxRow >= 0 }
                                if (sheets.isEmpty()) throw OperationFailed("${d.name} has no data.")
                                SheetToPdfRenderer.render(sheets, print, out, null)
                                wb.warnings.filter { !it.startsWith("Fonts") }.forEach { warnings.add("${d.name}: $it") }
                            }
                            DocType.PDF -> app.contentResolver.openInputStream(d.uri)?.use { s -> out.outputStream().use { s.copyTo(it) } }
                            else -> throw OperationFailed("Unsupported file")
                        }
                        made.add(d to out)
                    } catch (e: Exception) {
                        failed.add(PageIssue(i + 1, "${d.name}: ${e.userMessage()}"))
                    }
                    i++
                }
                if (made.isEmpty()) throw OperationFailed("None of the files could be converted. " + failed.joinToString("; ") { it.message })
                val outputs: List<OutputFile> = if (combine && made.map { it.second }.distinct().size > 1) {
                    p.step("Combining into one PDF…", 0.9f)
                    val parts = made.map { it.second }.distinct()
                    val docs = mutableListOf<PDDocument>()
                    try {
                        parts.forEach { docs.add(PdfDocs.open(it)) }
                        val refs = docs.flatMapIndexed { di, doc -> (0 until doc.numberOfPages).map { PageRef(di, it) } }
                        val out = app.files.newOutputFile("$name.pdf")
                        PdfOps.assemble(docs, refs, out)
                        listOf(OutputFile(out))
                    } finally { docs.forEach { runCatching { it.close() } } }
                } else if (files.size == 1 || (combine && made.map { it.second }.distinct().size == 1)) {
                    val f = made.first().second
                    val renamed = File(f.parentFile, FileRepository.sanitize("$name.pdf")); f.renameTo(renamed)
                    listOf(OutputFile(renamed))
                } else made.map { it.second }.distinct().map { OutputFile(it) }
                warnings.add("Fonts are replaced with the phone's fonts, so line and page breaks can differ slightly from Word/Excel. Check the preview.")
                OperationResult(
                    OperationReport("Create PDF", files.map { it.name }, if (failed.isEmpty()) Outcome.SUCCESS else Outcome.PARTIAL, failedPages = failed, warnings = warnings,
                        notes = listOf("${made.size} of ${files.size} file(s) converted" + if (outputs.size == 1) " into one PDF." else ".")),
                    outputs, Preview.Pdf(outputs.first().file),
                )
            }
        }
    }
}

private suspend fun imagesToPdf(images: List<InputDoc>, paper: PaperSize, out: File, p: Progress) {
    val app = DocDeskApp.instance
    ScanPdfBuilder.build(images.size, { i -> ImageLoader.load(app, images[i].uri, 2400) ?: throw OperationFailed("${images[i].name} could not be read.") }, null, out, p, paperWidthPt = paper.widthPt)
}
