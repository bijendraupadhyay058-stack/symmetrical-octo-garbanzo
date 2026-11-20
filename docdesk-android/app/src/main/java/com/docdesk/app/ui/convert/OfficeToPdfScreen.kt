package com.docdesk.app.ui.convert

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.DocToPdfRenderer
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.convert.SheetToPdfRenderer
import com.docdesk.app.data.DocType
import com.docdesk.app.data.FileRepository
import com.docdesk.app.data.InputDoc
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.CheckRow
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.core.DocDocument
import com.docdesk.core.DocxReader
import com.docdesk.core.Margins
import com.docdesk.core.Orientation
import com.docdesk.core.PageSetup
import com.docdesk.core.PaperSize
import com.docdesk.core.Scaling
import com.docdesk.core.SheetPrintOptions
import com.docdesk.core.Workbook
import com.docdesk.core.XlsxReader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class WordPaper(val label: String) { DOCUMENT("As set in the document"), A4("A4"), LETTER("Letter") }

class OfficeVm : ViewModel() {
    var doc by mutableStateOf<InputDoc?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var workbook by mutableStateOf<Workbook?>(null)
    var word by mutableStateOf<DocDocument?>(null)
    var selectedSheets by mutableStateOf(setOf<Int>())
    var print by mutableStateOf(SheetPrintOptions())
    var wordPaper by mutableStateOf(WordPaper.DOCUMENT)
    var pageNumbers by mutableStateOf(true)
    var fileName by mutableStateOf("")

    fun load(uri: Uri, excel: Boolean) {
        val app = DocDeskApp.instance
        val d = app.files.describe(uri)
        error = null; workbook = null; word = null
        when (d.type) {
            DocType.LEGACY_WORD, DocType.LEGACY_EXCEL -> { error = "\"${d.name}\" is an older ${d.type.label} file, which is not supported yet. Open it in Word/Excel or Google Docs/Sheets and save it as ${if (excel) ".xlsx" else ".docx"}, then try again."; return }
            DocType.WORD -> if (excel) { error = "That is a Word file. Use Word to PDF instead."; return }
            DocType.EXCEL -> if (!excel) { error = "That is an Excel file. Use Excel to PDF instead."; return }
            else -> { error = "Choose a ${if (excel) "Excel (.xlsx)" else "Word (.docx)"} file."; return }
        }
        doc = d; fileName = FileRepository.baseName(d.name); loading = true
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    app.contentResolver.openInputStream(uri)?.use { s ->
                        if (excel) workbook = XlsxReader.read(s) else word = DocxReader.read(s)
                    } ?: throw OperationFailed("The file could not be opened.")
                }
                workbook?.let { wb -> selectedSheets = wb.sheets.indices.filter { !wb.sheets[it].hidden }.toSet() }
            } catch (e: Throwable) { error = e.userMessage(); doc = null } finally { loading = false }
        }
    }
}

@Composable
fun OfficeToPdfScreen(nav: Nav, input: Uri?, excel: Boolean) {
    val vm: OfficeVm = viewModel(key = if (excel) "excel" else "word")
    val app = DocDeskApp.instance
    val job by app.jobs.state.collectAsStateWithLifecycle()
    LaunchedEffect(input) { if (input != null && vm.doc == null) vm.load(input, excel) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> vm.load(u, excel) } }
    val mimes = if (excel) arrayOf(DocType.EXCEL.mime, DocType.LEGACY_EXCEL.mime) else arrayOf(DocType.WORD.mime, DocType.LEGACY_WORD.mime)

    ToolScaffold(if (excel) "Excel to PDF" else "Word to PDF", nav::back) {
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        val d = vm.doc
        if (d == null || (vm.workbook == null && vm.word == null)) {
            if (vm.loading) Text("Reading file…")
            else FilePickTarget(if (excel) "Choose an Excel file (.xlsx)" else "Choose a Word file (.docx)", "Converted on this phone", if (excel) Icons.Default.GridOn else Icons.Default.Description) { picker.launch(mimes) }
            Notice(if (excel) "Values, number formats, bold/italic, fills, borders, merged cells and column widths are reproduced. Formulas show their last saved result. Charts, images and conditional formatting are not drawn."
                else "Text, headings, bold/italic/underline, lists, tables, images, page breaks, headers and footers are reproduced. Fonts are replaced with the phone's fonts, so line and page breaks may differ from Word.")
            return@ToolScaffold
        }
        FileHeader(d.name, formatSize(d.size), if (excel) Icons.Default.GridOn else Icons.Default.Description) { picker.launch(mimes) }
        if (excel) ExcelOptions(vm) else WordOptions(vm)
        OutlinedTextField(vm.fileName, { vm.fileName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") }, suffix = { Text(".pdf") })
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create PDF", enabled = job == null && (!excel || vm.selectedSheets.isNotEmpty()), icon = Icons.Default.PictureAsPdf) {
            val name = vm.fileName.ifBlank { "Converted" } + ".pdf"
            if (excel) {
                val wb = vm.workbook!!; val sheets = vm.selectedSheets.sorted().map { wb.sheets[it] }; val opts = vm.print
                Operations.run("Excel to PDF", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                    val out = app.files.newOutputFile(name)
                    val stats = SheetToPdfRenderer.render(sheets, opts, out, p)
                    val warnings = wb.warnings.toMutableList()
                    if (stats.truncatedCells > 0) warnings.add("${stats.truncatedCells} cell(s) did not fit their column and were cut off or shown as ###. Try a smaller scale or landscape.")
                    OperationResult(OperationReport("Excel to PDF", listOf(d.name), if (warnings.isEmpty()) Outcome.SUCCESS else Outcome.PARTIAL,
                        pagesProcessed = stats.pages, pagesSelected = stats.pages, warnings = warnings,
                        notes = listOf("${sheets.size} sheet(s) → ${stats.pages} page(s). Check the preview for page breaks before sharing.")), listOf(OutputFile(out)), Preview.Pdf(out))
                }
            } else {
                val src = vm.word!!
                val page = when (vm.wordPaper) { WordPaper.DOCUMENT -> src.page; WordPaper.A4 -> PageSetup.A4.copy(marginLeftPt = src.page.marginLeftPt, marginRightPt = src.page.marginRightPt, marginTopPt = src.page.marginTopPt, marginBottomPt = src.page.marginBottomPt); WordPaper.LETTER -> PageSetup.LETTER.copy(marginLeftPt = src.page.marginLeftPt, marginRightPt = src.page.marginRightPt, marginTopPt = src.page.marginTopPt, marginBottomPt = src.page.marginBottomPt) }
                val numbers = vm.pageNumbers
                Operations.run("Word to PDF", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                    val out = app.files.newOutputFile(name)
                    val renderer = DocToPdfRenderer(src.copy(page = page), numbers)
                    val pages = renderer.render(out, p)
                    val warnings = mutableListOf<String>()
                    src.unsupported.forEach { (what, n) -> warnings.add("Not fully supported: $what ($n).") }
                    if (src.fontsUsed.isNotEmpty()) warnings.add("Fonts used in the document (${src.fontsUsed.take(5).joinToString()}) are replaced with the phone's fonts; line and page breaks may differ from Word.")
                    if (renderer.clippedItems > 0) warnings.add("${renderer.clippedItems} item(s) were taller than a page and were cut off.")
                    if (renderer.skippedImages > 0) warnings.add("${renderer.skippedImages} image(s) could not be decoded.")
                    OperationResult(OperationReport("Word to PDF", listOf(d.name), if (warnings.size <= 1) Outcome.SUCCESS else Outcome.PARTIAL, pagesProcessed = pages, pagesSelected = pages, warnings = warnings,
                        notes = listOf(Limitations.GENERAL)), listOf(OutputFile(out)), Preview.Pdf(out))
                }
            }
        }
    }
}

@Composable
private fun ExcelOptions(vm: OfficeVm) {
    val wb = vm.workbook ?: return
    wb.warnings.forEach { Notice(it, NoteKind.WARNING) }
    SectionCard("Worksheets") {
        wb.sheets.forEachIndexed { i, s ->
            CheckRow(s.name + (if (s.hidden) " (hidden)" else "") + (if (s.maxRow < 0) " – empty" else "") + (if (s.printArea != null) " – has print area" else ""), i in vm.selectedSheets) { on ->
                vm.selectedSheets = if (on) vm.selectedSheets + i else vm.selectedSheets - i
            }
        }
    }
    val o = vm.print
    SectionCard("Page setup") {
        RadioOptions(Orientation.entries, o.orientation, { it.name.lowercase().replaceFirstChar { c -> c.uppercase() } }) { vm.print = o.copy(orientation = it) }
        Text("Paper size", style = MaterialTheme.typography.labelLarge)
        RadioOptions(PaperSize.entries, o.paper, { it.label }) { vm.print = o.copy(paper = it) }
        Text("Margins", style = MaterialTheme.typography.labelLarge)
        RadioOptions(Margins.entries, o.margins, { it.label }) { vm.print = o.copy(margins = it) }
        Text("Scaling", style = MaterialTheme.typography.labelLarge)
        RadioOptions(Scaling.entries, o.scaling, { it.label }) { vm.print = o.copy(scaling = it) }
        if (o.scaling == Scaling.CUSTOM) {
            Text("${o.customPercent}%")
            Slider(o.customPercent.toFloat(), { vm.print = o.copy(customPercent = it.toInt()) }, valueRange = 25f..200f, steps = 6)
        }
    }
    SectionCard("Print options") {
        SwitchRow("Use print area when defined", o.usePrintArea) { vm.print = o.copy(usePrintArea = it) }
        SwitchRow("Gridlines", o.gridlines) { vm.print = o.copy(gridlines = it) }
        SwitchRow("Sheet name at top of page", o.sheetNameHeader) { vm.print = o.copy(sheetNameHeader = it) }
        SwitchRow("Page numbers", o.pageNumbers) { vm.print = o.copy(pageNumbers = it) }
    }
}

@Composable
private fun WordOptions(vm: OfficeVm) {
    val w = vm.word ?: return
    val paragraphs = w.blocks.count { it is com.docdesk.core.DocBlock.Paragraph }
    val tables = w.blocks.count { it is com.docdesk.core.DocBlock.Table }
    val images = w.blocks.count { it is com.docdesk.core.DocBlock.Image }
    SectionCard("Document") {
        Text("$paragraphs paragraphs · $tables tables · $images images · page ${"%.0f".format(w.page.widthPt)}×${"%.0f".format(w.page.heightPt)} pt", style = MaterialTheme.typography.bodyMedium)
        if (w.unsupported.isNotEmpty()) Notice("Some content cannot be reproduced exactly: " + w.unsupported.entries.joinToString { "${it.key} (${it.value})" } + ".", NoteKind.WARNING)
    }
    SectionCard("Page setup") {
        RadioOptions(WordPaper.entries, vm.wordPaper, { it.label }) { vm.wordPaper = it }
        SwitchRow("Add page numbers", vm.pageNumbers) { vm.pageNumbers = it }
    }
}
