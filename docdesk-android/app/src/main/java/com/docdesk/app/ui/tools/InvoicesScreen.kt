package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ReceiptLong
import androidx.compose.material3.OutlinedTextField
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
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.PageTextSource
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.AppSettings
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.MultiPdfList
import com.docdesk.app.ui.components.MultiPdfState
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.InvoiceExtractor
import com.docdesk.core.InvoiceRecord
import com.docdesk.core.PageText
import com.docdesk.core.XlsxWriter

class InvoicesVm : ViewModel() {
    val files = MultiPdfState(viewModelScope)
    var name by mutableStateOf("GST invoice register")
    var error by mutableStateOf<String?>(null)
}

/** Many GST invoices (PDF or scanned) → one Excel register with tax checks. */
@Composable
fun InvoicesScreen(nav: Nav, input: Uri?) {
    val vm: InvoicesVm = viewModel()
    val app = DocDeskApp.instance
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    LaunchedEffect(input) { if (input != null && vm.files.items.isEmpty()) vm.files.add(listOf(input)) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.files.add(it) }

    ToolScaffold("GST invoice register", nav::back) {
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        vm.files.skipped?.let { Notice(it, NoteKind.WARNING) { vm.files.skipped = null } }
        if (vm.files.items.isEmpty()) {
            FilePickTarget("Choose GST invoices (PDF)", "Purchase or sales invoices → one Excel register", Icons.Default.ReceiptLong) { picker.launch(arrayOf("application/pdf")) }
            Notice("Reads invoice number, date, supplier and buyer GSTIN, taxable value, CGST, SGST/UTGST, IGST, cess and total from labelled text. Checks GSTIN check digits, that taxable value + taxes = total, CGST = SGST, and IGST vs. same-state supply. Values that aren't clearly labelled are left blank – never guessed. A second sheet shows the exact line each value came from.")
            return@ToolScaffold
        }
        SectionCard("${vm.files.items.size} invoice(s)") {
            MultiPdfList(vm.files)
            SecondaryAction("Add invoices", icon = Icons.Default.Add) { picker.launch(arrayOf("application/pdf")) }
        }
        OutlinedTextField(vm.name, { vm.name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") }, suffix = { Text(".xlsx") })
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create register", enabled = vm.files.allReady && job == null, icon = Icons.Default.ReceiptLong) {
            val items = vm.files.items.map { Triple(it.doc, it.password, it.pages!!) }
            val style = settings.numberStyle; val order = settings.dateOrder; val lang = settings.ocrLanguage; val name = vm.name.ifBlank { "GST invoice register" }
            Operations.run("GST invoice register", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                p.allowPartialResults()
                val records = mutableListOf<InvoiceRecord>(); val failed = mutableListOf<PageIssue>()
                var cancelled = false; var ocrUsed = 0
                for ((i, t) in items.withIndex()) {
                    val (d, pw, pages) = t
                    if (p.cancelRequested) { cancelled = true; break }
                    p.step("Reading ${d.name} (${i + 1} of ${items.size})", i.toFloat() / items.size)
                    try {
                        PdfDocs.open(app, d.uri, pw).use { doc ->
                            PdfDocs.require(doc, PdfAction.EXTRACT)
                            PageTextSource(app, d.uri, pw, doc, app.files.workDir, OcrMode.AUTO, lang).use { src ->
                                val texts = mutableListOf<PageText>()
                                for (pg in 0 until minOf(pages, 3)) texts.add(src.get(pg))
                                if (src.ocrWords > 0) ocrUsed++
                                records.add(InvoiceExtractor.extract(texts, d.name, style, order))
                            }
                        }
                    } catch (e: Exception) {
                        if (e is com.docdesk.app.jobs.OperationCancelled) throw e
                        failed.add(PageIssue(i + 1, "${d.name}: ${e.userMessage()}"))
                    }
                }
                if (records.isEmpty()) throw OperationFailed("No invoice could be read. " + failed.joinToString("; ") { it.message })
                val sheets = InvoiceExtractor.toSheets(records)
                val out = app.files.newOutputFile("$name.xlsx")
                out.outputStream().buffered().use { XlsxWriter.write(sheets, it) }
                val flagged = records.count { it.flags.isNotEmpty() }
                val dupes = records.groupBy { (it.supplierGstin ?: "") + "|" + (it.invoiceNo ?: "") }.filter { it.key != "|" && it.value.size > 1 }.keys
                val warnings = buildList {
                    if (flagged > 0) add("$flagged invoice(s) need review – see the Review column and the \"Where values came from\" sheet.")
                    if (dupes.isNotEmpty()) add("Possible duplicate invoices (same supplier GSTIN and invoice no.): ${dupes.joinToString { it.substringAfter('|') }}")
                    if (ocrUsed > 0) add("$ocrUsed invoice(s) were scanned and read with OCR – check amounts and GSTINs carefully.")
                }
                OperationResult(OperationReport("GST invoice register", items.map { it.first.name }, when { cancelled -> Outcome.CANCELLED; failed.isNotEmpty() || flagged > 0 -> Outcome.PARTIAL; else -> Outcome.SUCCESS },
                    failedPages = failed, warnings = warnings,
                    notes = listOf("${records.size} invoice(s) in the register. Values are read only from clearly labelled lines; blanks mean the label was not found. Verify against the invoices and GSTR-2B before filing.")),
                    listOf(OutputFile(out)), Preview.Sheets(sheets))
            }
        }
    }
}
