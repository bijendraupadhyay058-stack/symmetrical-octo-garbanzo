package com.docdesk.app.ui.scan

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.TextFields
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.PageTextSource
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.AppSettings
import com.docdesk.app.data.FileRepository
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.ocr.OcrEngine
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.scan.ScanPdfBuilder
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
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.convert.PageSelection
import com.docdesk.app.ui.convert.selectedPages
import com.docdesk.core.LineGrouper
import com.docdesk.core.TextSource

data class OcrOutput(val text: String, val lowWords: List<String>, val failed: List<PageIssue>, val pages: Int, val ocrPages: Int)

class OcrVm : ViewModel() {
    val holder = PdfInputHolder(viewModelScope, wantRenderer = false)
    var allPages by mutableStateOf(true)
    var range by mutableStateOf("")
    var language by mutableStateOf<OcrLanguage?>(null)
    var forceOcr by mutableStateOf(false)
    var output by mutableStateOf<OcrOutput?>(null)
    var text by mutableStateOf("")
    var error by mutableStateOf<String?>(null)
    var info by mutableStateOf<String?>(null)
    override fun onCleared() { holder.close() }
}

@Composable
fun OcrScreen(nav: Nav, input: Uri?) {
    val vm: OcrVm = viewModel()
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val h = vm.holder
    LaunchedEffect(input) { if (input != null && h.doc == null) h.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> vm.output = null; h.select(u) } }
    val lang = vm.language ?: settings.ocrLanguage

    ToolScaffold("Extract text (OCR)", nav::back) {
        h.error?.let { Notice(it, NoteKind.ERROR) }
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        vm.info?.let { Notice(it) { vm.info = null } }
        val d = h.doc; val info = h.info
        if (d == null || info == null) {
            if (h.loading) Text("Opening…") else FilePickTarget("Choose a scanned PDF", "Recognises English and Hindi text on this phone", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
            Notice(Limitations.OCR)
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages · ${info.kind?.label ?: ""}", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val out = vm.output
        val pages = selectedPages(info.pageCount, vm.allPages, vm.range).getOrNull()
        if (out == null) {
            SectionCard("Pages") { PageSelection(info.pageCount, vm.allPages, { vm.allPages = it }, vm.range) { vm.range = it } }
            SectionCard("Language") { RadioOptions(OcrLanguage.entries, lang, { it.label }) { vm.language = it } }
            SectionCard("Pages that already contain text") {
                RadioOptions(listOf(false, true), vm.forceOcr, { if (it) "Run OCR on every page" else "Use the existing text (faster, exact)" }) { vm.forceOcr = it }
            }
            job?.let { JobProgressCard(it) { app.jobs.cancel() } }
            PrimaryAction("Recognise text", enabled = pages != null && job == null, icon = Icons.Default.TextFields) {
                val pw = h.password; val mode = if (vm.forceOcr) OcrMode.ALWAYS else OcrMode.AUTO
                app.jobs.start("Recognising text", { p ->
                    p.allowPartialResults()
                    val sb = StringBuilder(); val low = mutableListOf<String>(); val failed = mutableListOf<PageIssue>(); var ocrPages = 0; var done = 0
                    PdfDocs.open(app, d.uri, pw).use { doc ->
                        PdfDocs.require(doc, PdfAction.EXTRACT)
                        PageTextSource(app, d.uri, pw, doc, app.files.workDir, mode, lang).use { src ->
                            for ((i, pg) in pages!!.withIndex()) {
                                if (p.cancelRequested) break
                                p.step("Page ${pg + 1} (${i + 1} of ${pages.size})", i.toFloat() / pages.size)
                                val t = runCatching { src.get(pg) }.getOrElse { failed.add(PageIssue(pg + 1, it.userMessage())); null } ?: continue
                                if (t.source == TextSource.NONE) { failed.add(PageIssue(pg + 1, "No text found.")); continue }
                                if (t.source == TextSource.OCR) ocrPages++
                                t.words.filter { (it.confidence ?: 1f) < 0.75f }.forEach { low.add("p${pg + 1}: ${it.text}") }
                                sb.append("--- Page ${pg + 1} ---\n").append(LineGrouper.group(t.words).joinToString("\n") { it.text }).append("\n\n")
                                done++
                            }
                        }
                    }
                    OcrOutput(sb.toString(), low, failed, done, ocrPages)
                }) { r -> r.onSuccess { vm.output = it; vm.text = it.text }.onFailure { vm.error = it.userMessage() } }
            }
        } else {
            SectionCard("Result") {
                Text("${out.pages} page(s) read (${out.ocrPages} with OCR). You can correct the text below before saving.", style = MaterialTheme.typography.bodyMedium)
                out.failed.forEach { Notice("Page ${it.page}: ${it.message}", NoteKind.WARNING) }
                if (out.lowWords.isNotEmpty()) {
                    Text("${out.lowWords.size} word(s) with low confidence – please check:", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.tertiary)
                    Text(out.lowWords.take(60).joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                }
            }
            OutlinedTextField(vm.text, { vm.text = it }, Modifier.fillMaxWidth().heightIn(min = 240.dp), label = { Text("Recognised text") })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SecondaryAction("Copy", icon = Icons.Default.ContentCopy, modifier = Modifier.weight(1f)) {
                    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Recognised text", vm.text))
                    vm.info = "Text copied to the clipboard."
                }
                SecondaryAction("Save as .txt", icon = Icons.Default.Save, modifier = Modifier.weight(1f)) {
                    val text = vm.text
                    Operations.run("Extract text", onError = { vm.error = it }, onResult = nav.resultCallback()) { _ ->
                        val f = app.files.newOutputFile(FileRepository.baseName(d.name) + ".txt"); f.writeText(text)
                        OperationResult(OperationReport("Extract text", listOf(d.name), if (out.failed.isEmpty()) Outcome.SUCCESS else Outcome.PARTIAL, null, pages?.size, out.pages, out.failed,
                            if (out.lowWords.isEmpty()) emptyList() else listOf("${out.lowWords.size} low-confidence words."), notes = listOf(Limitations.OCR)), listOf(OutputFile(f)), Preview.Text(text))
                    }
                }
            }
            job?.let { JobProgressCard(it) { app.jobs.cancel() } }
            SecondaryAction("Create searchable PDF", enabled = job == null, icon = Icons.Default.PictureAsPdf) {
                val pw = h.password
                Operations.run("Searchable PDF", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                    val outFile = app.files.newOutputFile(FileRepository.baseName(d.name) + " (searchable).pdf")
                    val renderer = if (info.encrypted) PageRenderer.openDecryptedCopy(app, d.uri, pw ?: "", app.files.workDir) else PageRenderer.open(app, d.uri, app.files.workDir)
                    renderer.use { r ->
                        val list = pages!!
                        val stats = ScanPdfBuilder.build(list.size, { i ->
                            val (w, _) = r.pageSize(list[i]); r.render(list[i], OcrEngine.ocrWidthPx(w.toFloat()), cache = false)!!
                        }, { i, bmp -> OcrEngine.recognize(bmp, lang, list[i], bmp.width.toFloat(), bmp.height.toFloat()).page.words }, outFile, p)
                        OperationResult(OperationReport("Searchable PDF", listOf(d.name), Outcome.SUCCESS, null, list.size, stats.pages,
                            warnings = buildList {
                                add("Pages are stored as images with an invisible text layer; the original vector text and links are not kept.")
                                if (stats.wordsSkipped > 0) add("${stats.wordsSkipped} words (e.g. Hindi) could not be added to the searchable layer.")
                            }, notes = listOf(Limitations.OCR)), listOf(OutputFile(outFile)), Preview.Pdf(outFile))
                    }
                }
            }
            SecondaryAction("Start again") { vm.output = null }
        }
    }
    PasswordPromptFor(h)
}
