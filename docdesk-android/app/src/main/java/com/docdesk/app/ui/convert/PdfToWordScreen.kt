package com.docdesk.app.ui.convert

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.PictureAsPdf
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
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.PdfToWordEngine
import com.docdesk.app.data.AppSettings
import com.docdesk.app.data.FileRepository
import com.docdesk.app.ocr.OcrLanguage
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
import com.docdesk.core.WordMode

class PdfToWordVm : ViewModel() {
    val holder = PdfInputHolder(viewModelScope, wantRenderer = false)
    var allPages by mutableStateOf(true)
    var range by mutableStateOf("")
    var mode by mutableStateOf(WordMode.EDITABLE)
    var ocrMode by mutableStateOf(OcrMode.AUTO)
    var language by mutableStateOf<OcrLanguage?>(null)
    var images by mutableStateOf(true)
    var fileName by mutableStateOf("")
    var error by mutableStateOf<String?>(null)
    override fun onCleared() { holder.close() }
}

@Composable
fun PdfToWordScreen(nav: Nav, input: Uri?) {
    val vm: PdfToWordVm = viewModel()
    val app = DocDeskApp.instance
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val h = vm.holder
    LaunchedEffect(input) { if (input != null && h.doc == null) h.select(input) }
    LaunchedEffect(h.doc) { h.doc?.let { vm.fileName = FileRepository.baseName(it.name) } }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> h.select(u) } }
    val lang = vm.language ?: settings.ocrLanguage

    ToolScaffold("PDF to Word", nav::back) {
        h.error?.let { Notice(it, NoteKind.ERROR) }
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        val d = h.doc; val info = h.info
        if (d == null || info == null) {
            if (h.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "Creates an editable Word (.docx) file", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
            Notice(Limitations.GENERAL)
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages · ${info.kind?.label ?: ""} · ${formatSize(d.size)}", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val pages = selectedPages(info.pageCount, vm.allPages, vm.range).getOrNull()
        SectionCard("Pages") { PageSelection(info.pageCount, vm.allPages, { vm.allPages = it }, vm.range) { vm.range = it } }
        SectionCard("Conversion mode") { RadioOptions(WordMode.entries, vm.mode, { it.label }, { it.description }) { vm.mode = it } }
        SectionCard("Scanned pages (OCR)") {
            RadioOptions(OcrMode.entries, vm.ocrMode, { it.label }) { vm.ocrMode = it }
            if (vm.ocrMode != OcrMode.NEVER) { Text("Recognition language"); RadioOptions(OcrLanguage.entries, lang, { it.label }) { vm.language = it } }
        }
        SectionCard("Content") { SwitchRow("Include images", vm.images, "Pictures from text-based pages are copied into the document.") { vm.images = it } }
        OutlinedTextField(vm.fileName, { vm.fileName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") }, suffix = { Text(".docx") })
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Convert to Word", enabled = pages != null && job == null, icon = Icons.Default.Description) {
            val pw = h.password; val mode = vm.mode; val ocr = vm.ocrMode; val img = vm.images
            val name = vm.fileName.ifBlank { "Converted" } + ".docx"
            Operations.run("PDF to Word", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                PdfToWordEngine.convert(app, d.uri, d.name, pw, pages!!, mode, ocr, lang, img, app.files.workDir, app.files.newOutputFile(name), p)
            }
        }
    }
    PasswordPromptFor(h)
}
