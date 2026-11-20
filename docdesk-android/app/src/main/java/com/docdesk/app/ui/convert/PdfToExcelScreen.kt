package com.docdesk.app.ui.convert

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.TableChart
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.ExtractionResult
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PdfToExcelEngine
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.AppSettings
import com.docdesk.app.data.FileRepository
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.pdf.PdfDocs
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
import com.docdesk.core.CellFlag
import com.docdesk.core.ColumnType
import com.docdesk.core.DateOrder
import com.docdesk.core.ExcelExportOptions
import com.docdesk.core.ExtractedTable
import com.docdesk.core.NormRect
import com.docdesk.core.NumberStyle
import com.docdesk.core.SheetMode
import com.docdesk.core.TableCell
import com.docdesk.core.TableOptions
import com.docdesk.core.TextSource

class PdfToExcelVm : ViewModel() {
    val holder = PdfInputHolder(viewModelScope)
    var allPages by mutableStateOf(true)
    var range by mutableStateOf("")
    var ocrMode by mutableStateOf(OcrMode.AUTO)
    var language by mutableStateOf<OcrLanguage?>(null)
    var numberStyle by mutableStateOf<NumberStyle?>(null)
    var dateOrder by mutableStateOf<DateOrder?>(null)
    var useArea by mutableStateOf(false)
    var area by mutableStateOf<NormRect?>(null)
    var mergeWrapped by mutableStateOf(true)
    var extraction by mutableStateOf<ExtractionResult?>(null)
    var tables by mutableStateOf<List<ExtractedTable>>(emptyList())
    var sheetMode by mutableStateOf(SheetMode.ONE_SHEET)
    var includeSource by mutableStateOf(true)
    var includeReview by mutableStateOf(true)
    var convertValues by mutableStateOf(true)
    var fileName by mutableStateOf("")
    var error by mutableStateOf<String?>(null)
    var tab by mutableIntStateOf(0)

    override fun onCleared() { holder.close() }

    fun editCell(t: Int, r: Int, c: Int, text: String) {
        tables = tables.mapIndexed { ti, table ->
            if (ti != t) table else table.copy(rows = table.rows.mapIndexed { ri, row ->
                if (ri != r) row else row.copy(cells = row.cells.mapIndexed { ci, cell -> if (ci != c) cell else TableCell(text, cell.confidence, setOf(CellFlag.EDITED)) })
            })
        }
    }

    fun setType(t: Int, c: Int, type: ColumnType) {
        tables = tables.mapIndexed { ti, table -> if (ti != t) table else table.copy(columnTypes = table.columnTypes.mapIndexed { i, x -> if (i == c) type else x }) }
    }

    fun toggleHeader(t: Int) {
        tables = tables.mapIndexed { ti, table ->
            if (ti != t) table else table.copy(rows = table.rows.mapIndexed { i, row -> if (i == 0) row.copy(isHeader = !row.isHeader) else row })
        }
    }
}

@Composable
fun PdfToExcelScreen(nav: Nav, input: Uri?) {
    val vm: PdfToExcelVm = viewModel()
    val app = DocDeskApp.instance
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val h = vm.holder
    LaunchedEffect(input) { if (input != null && h.doc == null) h.select(input) }
    LaunchedEffect(h.doc) { h.doc?.let { vm.fileName = FileRepository.baseName(it.name) } }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> vm.extraction = null; h.select(u) } }
    val lang = vm.language ?: settings.ocrLanguage
    val style = vm.numberStyle ?: settings.numberStyle
    val order = vm.dateOrder ?: settings.dateOrder
    val ex = vm.extraction

    ToolScaffold(if (ex == null) "PDF to Excel" else "Review tables", { if (ex != null) vm.extraction = null else nav.back() }) {
        h.error?.let { Notice(it, NoteKind.ERROR) }
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        val d = h.doc; val info = h.info
        if (d == null || info == null) {
            if (h.loading) Text("Opening…") else FilePickTarget("Choose a PDF with tables", "Bank statements, invoices, ledgers, reports", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
            Notice("Works best with text-based PDFs. Scanned pages are read with on-device OCR, which is less accurate. Every value is kept exactly as found; nothing is guessed or filled in.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages · ${info.kind?.label ?: "content protected"} · ${formatSize(d.size)}", Icons.Default.PictureAsPdf, if (ex == null) ({ picker.launch(arrayOf("application/pdf")) }) else null)

        if (ex == null) {
            val pages = selectedPages(info.pageCount, vm.allPages, vm.range).getOrNull()
            SectionCard("Pages") { PageSelection(info.pageCount, vm.allPages, { vm.allPages = it }, vm.range) { vm.range = it } }
            SectionCard("Number and date format") {
                Text("Confirm how amounts and dates are written in this document.", style = MaterialTheme.typography.bodySmall)
                RadioOptions(NumberStyle.entries, style, { it.label }) { vm.numberStyle = it }
                RadioOptions(DateOrder.entries, order, { it.label }) { vm.dateOrder = it }
            }
            SectionCard("Scanned pages (OCR)") {
                RadioOptions(OcrMode.entries, vm.ocrMode, { it.label }) { vm.ocrMode = it }
                if (vm.ocrMode != OcrMode.NEVER) RadioOptions(OcrLanguage.entries, lang, { it.label }) { vm.language = it }
                if (info.kind == com.docdesk.app.pdf.PdfKind.SCANNED && vm.ocrMode == OcrMode.NEVER) Notice("This PDF looks scanned. Without OCR no tables can be found.", NoteKind.WARNING)
            }
            SectionCard("Table detection") {
                SwitchRow("Join wrapped descriptions", vm.mergeWrapped, "Lines that continue a description are joined into the row above.") { vm.mergeWrapped = it }
                SwitchRow("Select table area manually", vm.useArea, "Use when automatic detection picks up headers or footers.") { vm.useArea = it; if (!it) vm.area = null }
                val r = h.renderer
                if (vm.useArea && r != null) {
                    AreaSelector(r, pages?.firstOrNull() ?: 0, vm.area) { vm.area = it }
                    if (vm.area != null) TextButton(onClick = { vm.area = null }) { Text("Clear area") }
                }
            }
            job?.let { JobProgressCard(it) { app.jobs.cancel() } }
            PrimaryAction("Find tables", enabled = pages != null && job == null && (!vm.useArea || vm.area != null), icon = Icons.Default.TableChart) {
                val opts = TableOptions(style, order, if (vm.useArea) vm.area else null, mergeWrappedRows = vm.mergeWrapped)
                val pw = h.password; val mode = vm.ocrMode
                app.jobs.start("Finding tables", { p -> PdfToExcelEngine.extract(app, d.uri, pw, pages!!, mode, lang, opts, app.files.workDir, p) }) { res ->
                    res.onSuccess { vm.extraction = it; vm.tables = it.tables; vm.tab = 0 }.onFailure { vm.error = it.userMessage() }
                }
            }
        } else {
            ReviewSection(vm, ex, style, order)
            job?.let { JobProgressCard(it) { app.jobs.cancel() } }
            PrimaryAction("Export to Excel", enabled = vm.tables.isNotEmpty() && job == null, icon = Icons.Default.TableChart) {
                val tables = vm.tables
                val opts = ExcelExportOptions(vm.sheetMode, style, order, vm.convertValues, vm.convertValues, includeSourceSheet = vm.includeSource, includeReviewSheet = vm.includeReview)
                val name = vm.fileName.ifBlank { "Converted" } + ".xlsx"
                val report = buildReport(d.name, ex, tables, style)
                Operations.run("PDF to Excel", onError = { vm.error = it }, onResult = nav.resultCallback()) { progress ->
                    progress.step("Writing spreadsheet…", 0.5f)
                    val out = app.files.newOutputFile(name)
                    val reportPairs = listOf(
                        "Source file" to d.name, "Document type" to (report.documentKind ?: ""), "Pages processed" to "${report.pagesProcessed} of ${report.pagesSelected}",
                        "Failed pages" to (report.failedPages.joinToString("; ") { "p${it.page}: ${it.message}" }.ifEmpty { "None" }),
                    ) + report.checks.map { "Check" to it } + report.warnings.map { "Warning" to it }
                    val built = PdfToExcelEngine.export(tables, opts, reportPairs, out)
                    OperationResult(report.copy(notes = report.notes + "${built.convertedCells} values converted to numbers/dates; ${built.textCells} kept as text; ${built.flaggedCells} cells flagged (highlighted yellow and listed on the Review sheet)."),
                        listOf(OutputFile(out)), Preview.Sheets(built.sheets))
                }
            }
        }
    }
    PasswordPromptFor(h)
}

private fun buildReport(name: String, ex: ExtractionResult, tables: List<ExtractedTable>, style: NumberStyle): OperationReport {
    val warnings = mutableListOf<String>()
    if (ex.pagesWithoutTables.isNotEmpty()) warnings.add("No table found on page(s) ${ex.pagesWithoutTables.joinToString(", ")}.")
    val flagged = tables.sumOf { it.flaggedCellCount }
    if (flagged > 0) warnings.add("$flagged cell(s) need review (low OCR confidence, joined lines, or values that could not be read as numbers/dates).")
    if (ex.ocrWords > 0) { warnings.add("${ex.ocrWords} words were read with OCR (${ex.lowConfidenceWords} low confidence)."); warnings.add(Limitations.OCR) }
    val checks = PdfToExcelEngine.checks(tables, style, ex.statementLines).flatMap { (i, r) -> listOf("Table ${i + 1}:") + PdfToExcelEngine.describe(r) }
    val outcome = when {
        ex.cancelled -> Outcome.CANCELLED
        ex.pagesDone.isEmpty() -> Outcome.FAILED
        ex.failed.isNotEmpty() || ex.pagesWithoutTables.isNotEmpty() -> Outcome.PARTIAL
        else -> Outcome.SUCCESS
    }
    return OperationReport("PDF to Excel", listOf(name), outcome, PdfDocs.kindLabel(ex.sources.values), ex.pagesSelected, ex.pagesDone.size, ex.failed, warnings,
        checks = if (checks.isEmpty()) emptyList() else checks + Limitations.FINANCIAL, notes = listOf(Limitations.GENERAL))
}

@Composable
private fun ReviewSection(vm: PdfToExcelVm, ex: ExtractionResult, style: NumberStyle, order: DateOrder) {
    val tables = vm.tables
    SectionCard("Summary") {
        Text("${PdfDocs.kindLabel(ex.sources.values)} · ${ex.pagesDone.size} of ${ex.pagesSelected} pages read · ${tables.size} table(s) found", style = MaterialTheme.typography.bodyMedium)
        if (ex.cancelled) Notice("Cancelled: only the pages read before cancelling are included.", NoteKind.WARNING)
        ex.failed.forEach { Notice("Page ${it.page}: ${it.message}", NoteKind.WARNING) }
        if (ex.pagesWithoutTables.isNotEmpty()) Text("No table found on page(s): ${ex.pagesWithoutTables.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
        val flagged = tables.sumOf { it.flaggedCellCount }
        if (flagged > 0) Text("$flagged cell(s) are highlighted for review. Tap a cell to correct it.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.tertiary)
    }
    if (tables.isEmpty()) {
        Notice("No tables were detected. Try selecting the table area manually, choosing different pages, or turning on OCR for scanned PDFs.", NoteKind.WARNING)
        return
    }
    val checks = PdfToExcelEngine.checks(tables, style, ex.statementLines)
    if (checks.isNotEmpty()) SectionCard("Financial checks") {
        checks.forEach { (i, r) -> Text("Table ${i + 1}", style = MaterialTheme.typography.labelLarge); PdfToExcelEngine.describe(r).forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) } }
        Text(Limitations.FINANCIAL, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    if (vm.tab >= tables.size) vm.tab = 0
    ScrollableTabRow(selectedTabIndex = vm.tab, edgePadding = 0.dp) {
        tables.forEachIndexed { i, t -> Tab(selected = vm.tab == i, onClick = { vm.tab = i }, text = { Text("P${t.pageIndex + 1} T${t.tableIndexOnPage + 1}" + if (t.source == TextSource.OCR) " (OCR)" else "") }) }
    }
    val t = tables[vm.tab]
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(selected = t.rows.firstOrNull()?.isHeader == true, onClick = { vm.toggleHeader(vm.tab) }, label = { Text("First row is header") })
    }
    TableEditor(vm, vm.tab, t)
    SectionCard("Export options") {
        RadioOptions(SheetMode.entries, vm.sheetMode, { it.label }) { vm.sheetMode = it }
        SwitchRow("Convert amounts and dates", vm.convertValues, "Writes real numbers/dates (formatted like the PDF). Off = everything as text.") { vm.convertValues = it }
        SwitchRow("Add \"Source text\" sheet", vm.includeSource, "Exact extracted text for comparison with the PDF.") { vm.includeSource = it }
        SwitchRow("Add \"Review\" sheet", vm.includeReview, "Conversion report, checks and every flagged cell.") { vm.includeReview = it }
        OutlinedTextField(vm.fileName, { vm.fileName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") }, suffix = { Text(".xlsx") })
    }
}

@Composable
private fun TableEditor(vm: PdfToExcelVm, ti: Int, t: ExtractedTable) {
    val hs: ScrollState = rememberScrollState()
    Column(Modifier.fillMaxWidth().border(1.dp, MaterialTheme.colorScheme.outlineVariant).horizontalScroll(hs)) {
        // Column type selectors
        Row {
            t.columnTypes.forEachIndexed { c, type ->
                Box(Modifier.width(150.dp).padding(2.dp)) {
                    TextButton(onClick = {
                        val next = ColumnType.entries[(type.ordinal + 1) % ColumnType.entries.size]
                        vm.setType(ti, c, next)
                    }, modifier = Modifier.semantics { contentDescription = "Column ${c + 1} type ${type.name.lowercase()}. Tap to change." }) {
                        Text(when (type) { ColumnType.TEXT -> "Text"; ColumnType.DATE -> "Date"; ColumnType.AMOUNT -> "Amount" } + " ▾", style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
        }
        t.rows.take(400).forEachIndexed { r, row ->
            Row {
                row.cells.forEachIndexed { c, cell ->
                    val flagged = cell.flags.any { it != CellFlag.EDITED }
                    val bg = when { row.isHeader -> MaterialTheme.colorScheme.primaryContainer; flagged -> MaterialTheme.colorScheme.tertiaryContainer; CellFlag.EDITED in cell.flags -> MaterialTheme.colorScheme.secondaryContainer; else -> MaterialTheme.colorScheme.surface }
                    BasicTextField(
                        value = cell.raw, onValueChange = { vm.editCell(ti, r, c, it) },
                        textStyle = TextStyle(color = MaterialTheme.colorScheme.onSurface, fontWeight = if (row.isHeader) FontWeight.Bold else FontWeight.Normal, fontSize = MaterialTheme.typography.bodySmall.fontSize),
                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                        modifier = Modifier.width(150.dp).heightIn(min = 40.dp).background(bg).border(0.5.dp, MaterialTheme.colorScheme.outlineVariant).padding(6.dp)
                            .semantics { contentDescription = "Row ${r + 1}, column ${c + 1}" + if (flagged) ". Needs review: " + cell.flags.filter { it != CellFlag.EDITED }.joinToString { it.message } else "" },
                    )
                }
            }
        }
        if (t.rows.size > 400) Text("Showing the first 400 rows. All ${t.rows.size} rows will be exported.", Modifier.padding(8.dp), style = MaterialTheme.typography.bodySmall)
    }
}
