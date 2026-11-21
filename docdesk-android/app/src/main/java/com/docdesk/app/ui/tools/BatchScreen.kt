package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DynamicFeed
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.PdfToExcelEngine
import com.docdesk.app.convert.PdfToWordEngine
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.AppSettings
import com.docdesk.app.data.FileRepository
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.CompressLevel
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfEnhance
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.MultiPdfList
import com.docdesk.app.ui.components.MultiPdfState
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.ExcelExportOptions
import com.docdesk.core.TableOptions
import com.docdesk.core.WordMode
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

enum class BatchAction(val label: String, val help: String) {
    EXCEL("Convert each to Excel", "Tables from every page, with Source text and Review sheets."),
    WORD("Convert each to Word", "Editable text mode."),
    COMPRESS("Compress each", "Medium compression."),
    PROTECT("Add the same password to each", "AES-256."),
    SPLIT("Split each by page ranges", "e.g. 1-2, 3- makes two parts from every file."),
}

private fun BatchAction.word() = when (this) { BatchAction.EXCEL -> "Excel"; BatchAction.WORD -> "Word"; BatchAction.COMPRESS -> "compressed"; BatchAction.PROTECT -> "protected"; BatchAction.SPLIT -> "split" }

class BatchVm : ViewModel() {
    val files = MultiPdfState(viewModelScope)
    var action by mutableStateOf(BatchAction.EXCEL)
    var password by mutableStateOf("")
    var zip by mutableStateOf(true)
    var pattern by mutableStateOf(com.docdesk.core.BatchNaming.DEFAULT)
    var ranges by mutableStateOf("")
    var error by mutableStateOf<String?>(null)
}

/** Apply one action to many PDFs in one go. */
@Composable
fun BatchScreen(nav: Nav, input: Uri?) {
    val vm: BatchVm = viewModel()
    val app = DocDeskApp.instance
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    LaunchedEffect(input) { if (input != null && vm.files.items.isEmpty()) vm.files.add(listOf(input)) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.files.add(it) }

    ToolScaffold("Batch process", nav::back) {
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        vm.files.skipped?.let { Notice(it, NoteKind.WARNING) { vm.files.skipped = null } }
        if (vm.files.items.isEmpty()) {
            FilePickTarget("Choose several PDFs", "Convert, compress or protect them all at once", Icons.Default.DynamicFeed) { picker.launch(arrayOf("application/pdf")) }
            return@ToolScaffold
        }
        SectionCard("${vm.files.items.size} file(s)") {
            MultiPdfList(vm.files)
            SecondaryAction("Add files", icon = Icons.Default.Add) { picker.launch(arrayOf("application/pdf")) }
        }
        SectionCard("Action") {
            RadioOptions(BatchAction.entries, vm.action, { it.label }, { it.help }) { vm.action = it }
            if (vm.action == BatchAction.PROTECT) OutlinedTextField(vm.password, { vm.password = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Password (min 4)") },
                visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        }
        if (vm.action == BatchAction.SPLIT) OutlinedTextField(vm.ranges, { vm.ranges = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Page ranges, one part each") }, placeholder = { Text("1-2, 3-") },
            supportingText = { Text("“3-” means page 3 to the end. Files too short for a range are reported, not guessed.") })
        SectionCard("Output names") {
            OutlinedTextField(vm.pattern, { vm.pattern = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Name pattern") })
            Text(com.docdesk.core.BatchNaming.tokens.joinToString(" · ") { "${it.first} = ${it.second}" }, style = MaterialTheme.typography.bodySmall)
            Text("Example: " + com.docdesk.core.BatchNaming.name(vm.pattern, vm.files.items.firstOrNull()?.doc?.name?.let { FileRepository.baseName(it) } ?: "Statement April", 0, vm.files.items.size, vm.action.word(), java.time.LocalDate.now(), if (vm.action == BatchAction.SPLIT) 1 else null), style = MaterialTheme.typography.bodySmall)
        }
        SwitchRow("Pack results into one ZIP", vm.zip, "The ZIP also contains a batch report (CSV).") { vm.zip = it }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Start", enabled = vm.files.allReady && job == null && (vm.action != BatchAction.PROTECT || vm.password.length >= 4) && (vm.action != BatchAction.SPLIT || vm.ranges.isNotBlank()), icon = Icons.Default.DynamicFeed) {
            val items = vm.files.items.map { Triple(it.doc, it.password, it.pages!!) }
            val action = vm.action; val pwNew = vm.password; val asZip = vm.zip; val pattern = vm.pattern; val ranges = vm.ranges; val today = java.time.LocalDate.now()
            val style = settings.numberStyle; val order = settings.dateOrder; val lang = settings.ocrLanguage
            Operations.run("Batch: ${action.label}", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                p.allowPartialResults()
                val outs = mutableListOf<File>(); val failed = mutableListOf<PageIssue>(); val warnings = mutableListOf<String>()
                var cancelled = false
                data class Line(val name: String, var status: String, var pages: Int, val notes: MutableList<String> = mutableListOf(), val outputs: MutableList<String> = mutableListOf())
                val report = mutableListOf<Line>()
                for ((i, t) in items.withIndex()) {
                    val (d, pw, pages) = t
                    if (p.cancelRequested) { cancelled = true; break }
                    p.step("${d.name} (${i + 1} of ${items.size})", i.toFloat() / items.size)
                    val base = com.docdesk.core.BatchNaming.name(pattern, FileRepository.baseName(d.name), i, items.size, action.word(), today)
                    val line = Line(d.name, "Done", pages).also { report.add(it) }
                    val before = outs.size; val warnBefore = warnings.size
                    try {
                        when (action) {
                            BatchAction.EXCEL -> {
                                val ex = PdfToExcelEngine.extract(app, d.uri, pw, (0 until pages).toList(), OcrMode.AUTO, lang, TableOptions(style, order), app.files.workDir, p)
                                if (ex.tables.isEmpty()) throw OperationFailed("no tables found")
                                val out = app.files.newOutputFile("$base.xlsx")
                                val b = PdfToExcelEngine.export(ex.tables, ExcelExportOptions(numberStyle = style, dateOrder = order), listOf("Source file" to d.name), out)
                                if (b.flaggedCells > 0) warnings.add("${d.name}: ${b.flaggedCells} cell(s) flagged for review.")
                                outs.add(out)
                            }
                            BatchAction.WORD -> {
                                val r = PdfToWordEngine.convert(app, d.uri, d.name, pw, (0 until pages).toList(), WordMode.EDITABLE, OcrMode.AUTO, lang, true, app.files.workDir, app.files.newOutputFile("$base.docx"), p)
                                if (r.report.failedPages.isNotEmpty()) warnings.add("${d.name}: ${r.report.failedPages.size} page(s) not converted.")
                                outs.addAll(r.outputs.map { it.file })
                            }
                            BatchAction.COMPRESS -> PdfDocs.open(app, d.uri, pw).use { doc ->
                                PdfDocs.require(doc, PdfAction.MODIFY)
                                PdfEnhance.compress(doc, CompressLevel.MEDIUM, null)
                                PdfOps.keepProtectionForSave(doc, pw)
                                val out = app.files.newOutputFile("$base.pdf"); PdfOps.saveAtomically(doc, out)
                                if (d.size > 0 && out.length() >= d.size) warnings.add("${d.name}: could not be made smaller.")
                                outs.add(out)
                            }
                            BatchAction.PROTECT -> PdfDocs.open(app, d.uri, pw).use { doc ->
                                PdfDocs.require(doc, PdfAction.MODIFY)
                                val out = app.files.newOutputFile("$base.pdf")
                                com.docdesk.app.pdf.PdfSecurity.protect(doc, out, pwNew, null, com.docdesk.app.pdf.Allowed.EVERYTHING, com.docdesk.app.pdf.Strength.AES256)
                                outs.add(out)
                            }
                            BatchAction.SPLIT -> PdfDocs.open(app, d.uri, pw).use { doc ->
                                PdfDocs.require(doc, PdfAction.ASSEMBLE)
                                val groups = try { com.docdesk.core.PageRanges.parseGroups(ranges, pages) } catch (e: com.docdesk.core.PageRanges.ParseException) { throw OperationFailed(e.message ?: "invalid page ranges") }
                                groups.forEachIndexed { gi, g ->
                                    val name = com.docdesk.core.BatchNaming.name(pattern, FileRepository.baseName(d.name), i, items.size, action.word(), today, part = gi + 1)
                                    val out = app.files.newOutputFile("$name.pdf")
                                    com.docdesk.app.pdf.PdfOps.assemble(listOf(doc), g.map { com.docdesk.app.pdf.PageRef(0, it) }, out)
                                    outs.add(out)
                                }
                            }
                        }
                        if (warnings.size > warnBefore) { line.status = "Done with warnings"; line.notes.addAll(warnings.subList(warnBefore, warnings.size)) }
                    } catch (e: Exception) {
                        if (e is com.docdesk.app.jobs.OperationCancelled) throw e
                        failed.add(PageIssue(i + 1, "${d.name}: ${e.userMessage()}"))
                        line.status = "Failed"; line.pages = 0; line.notes.add(e.userMessage())
                    }
                    line.outputs.addAll(outs.subList(before, outs.size).map { it.name })
                }
                if (outs.isEmpty()) throw OperationFailed("No file could be processed. " + failed.joinToString("; ") { it.message })
                if (cancelled) items.drop(report.size).forEach { report.add(Line(it.first.name, "Not started (cancelled)", 0)) }
                fun q(v: String) = if (v.any { it == ',' || it == '"' || it == '\n' }) "\"" + v.replace("\"", "\"\"") + "\"" else v
                val csv = "\uFEFFFile,Status,Pages,Outputs,Notes\n" + report.joinToString("") { l -> listOf(l.name, l.status, l.pages.toString(), l.outputs.joinToString(" | "), l.notes.joinToString(" | ")).joinToString(",") { q(it) } + "\n" }
                val reportFile = app.files.newOutputFile("Batch report.csv").also { it.writeText(csv) }
                val outputs = if (asZip && outs.size > 1) {
                    val z = app.files.newOutputFile("Batch ${action.word()} (${outs.size} files).zip")
                    val names = com.docdesk.core.BatchNaming.unique(outs.map { it.name } + reportFile.name)
                    ZipOutputStream(z.outputStream().buffered()).use { zos -> (outs + reportFile).forEachIndexed { k, f -> zos.putNextEntry(ZipEntry(names[k])); f.inputStream().use { it.copyTo(zos) }; zos.closeEntry() } }
                    listOf(OutputFile(z))
                } else outs.map { OutputFile(it) } + OutputFile(reportFile)
                OperationResult(OperationReport("Batch: ${action.label}", items.map { it.first.name }, when { cancelled -> Outcome.CANCELLED; failed.isNotEmpty() -> Outcome.PARTIAL; else -> Outcome.SUCCESS },
                    failedPages = failed, warnings = warnings, notes = listOf("${report.count { it.status.startsWith("Done") }} of ${items.size} file(s) processed (${report.count { it.status == "Done with warnings" }} with warnings, ${report.count { it.status == "Failed" }} failed); ${outs.size} output file(s).") +
                        report.map { l -> "${l.name}: ${l.status}" + (if (l.pages > 0) ", ${l.pages} page(s)" else "") + (if (l.outputs.isNotEmpty()) " → ${l.outputs.joinToString()}" else "") } +
                        "Results are saved in My Files when you tap Save. A batch report (CSV) lists every file."),
                    outputs, outs.firstOrNull { it.extension == "pdf" }?.let { Preview.Pdf(it) })
            }
        }
    }
}
