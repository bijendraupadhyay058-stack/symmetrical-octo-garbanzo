package com.docdesk.app.ui.scan

import android.app.Activity
import android.graphics.Bitmap
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.RotateLeft
import androidx.compose.material.icons.automirrored.filled.RotateRight
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.TextFields
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.AppSettings
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.ocr.OcrEngine
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.scan.ColorMode
import com.docdesk.app.scan.ImageLoader
import com.docdesk.app.scan.ImageProcessor
import com.docdesk.app.scan.PageAdjust
import com.docdesk.app.scan.ScanPdfBuilder
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.LineGrouper
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class ScanPage(val id: Long, val uri: Uri, val adjust: PageAdjust = PageAdjust())

class ScanVm : ViewModel() {
    val pages = mutableStateListOf<ScanPage>()
    var selected by mutableIntStateOf(0)
    var nextId = 1L
    var name by mutableStateOf("Scan")
    var searchable by mutableStateOf(true)
    var language by mutableStateOf<OcrLanguage?>(null)
    var error by mutableStateOf<String?>(null)
    fun add(uris: List<Uri>) { uris.forEach { pages.add(ScanPage(nextId++, it)) } }
    fun update(i: Int, f: (PageAdjust) -> PageAdjust) { if (i in pages.indices) pages[i] = pages[i].copy(adjust = f(pages[i].adjust)) }
}

@Composable
fun ScanScreen(nav: Nav) {
    val vm: ScanVm = viewModel()
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val lang = vm.language ?: settings.ocrLanguage

    val scanLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { r ->
        if (r.resultCode == Activity.RESULT_OK) {
            val res = GmsDocumentScanningResult.fromActivityResultIntent(r.data)
            res?.pages?.map { it.imageUri }?.let { vm.add(it) }
        }
    }
    val importer = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(50)) { uris -> vm.add(uris) }

    fun startScanner() {
        val activity = context as? Activity ?: return
        val options = GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(true).setPageLimit(50)
            .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG)
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL).build()
        GmsDocumentScanning.getClient(options).getStartScanIntent(activity)
            .addOnSuccessListener { scanLauncher.launch(IntentSenderRequest.Builder(it).build()) }
            .addOnFailureListener { vm.error = "The camera scanner is not available on this phone (it needs Google Play services, and an internet connection the first time to download the scanner). You can still use \"Import images\"." }
    }

    ToolScaffold("Scan & OCR", nav::back) {
        vm.error?.let { Notice(it, NoteKind.WARNING) { vm.error = null } }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SecondaryAction("Scan with camera", icon = Icons.Default.DocumentScanner, modifier = Modifier.weight(1f)) { startScanner() }
            SecondaryAction("Import images", icon = Icons.Default.PhotoLibrary, modifier = Modifier.weight(1f)) { importer.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
        }
        if (vm.pages.isEmpty()) {
            Notice("The camera scanner finds page edges automatically and lets you crop, straighten and rotate each page. After scanning you can reorder pages and adjust brightness, contrast and colour here. Scanning is provided by Google Play services; the images stay on your phone.")
            Notice(Limitations.OCR)
            SecondaryAction("Extract text from an existing PDF", icon = Icons.Default.TextFields) { nav.to(com.docdesk.app.ui.Routes.OCR) }
            return@ToolScaffold
        }
        Text("${vm.pages.size} page(s). Tap a page to adjust it.", style = MaterialTheme.typography.bodyMedium)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            itemsIndexed(vm.pages, key = { _, p -> p.id }) { i, p ->
                Surface(shape = RoundedCornerShape(8.dp), border = BorderStroke(if (i == vm.selected) 3.dp else 1.dp, if (i == vm.selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant),
                    modifier = Modifier.width(96.dp).clickable { vm.selected = i }.semantics { contentDescription = "Page ${i + 1}" + if (i == vm.selected) ", selected" else "" }) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        AdjustedImage(p, 300, Modifier.padding(4.dp))
                        Text("${i + 1}", style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
        }
        val i = vm.selected.coerceIn(0, vm.pages.lastIndex)
        val page = vm.pages[i]
        SectionCard("Page ${i + 1}") {
            AdjustedImage(page, 1200, Modifier.fillMaxWidth())
            Row {
                IconButton(onClick = { vm.update(i) { it.copy(rotation = (it.rotation + 270) % 360) } }) { Icon(Icons.AutoMirrored.Filled.RotateLeft, "Rotate left") }
                IconButton(onClick = { vm.update(i) { it.copy(rotation = (it.rotation + 90) % 360) } }) { Icon(Icons.AutoMirrored.Filled.RotateRight, "Rotate right") }
                IconButton(onClick = { if (i > 0) { vm.pages.add(i - 1, vm.pages.removeAt(i)); vm.selected = i - 1 } }, enabled = i > 0) { Icon(Icons.Default.ChevronLeft, "Move page earlier") }
                IconButton(onClick = { if (i < vm.pages.lastIndex) { vm.pages.add(i + 1, vm.pages.removeAt(i)); vm.selected = i + 1 } }, enabled = i < vm.pages.lastIndex) { Icon(Icons.Default.ChevronRight, "Move page later") }
                IconButton(onClick = { vm.pages.removeAt(i); vm.selected = (i - 1).coerceAtLeast(0) }) { Icon(Icons.Default.Delete, "Delete page") }
            }
            RadioOptions(ColorMode.entries, page.adjust.mode, { it.label }) { m -> vm.update(i) { it.copy(mode = m) } }
            Text("Brightness", style = MaterialTheme.typography.labelLarge)
            Slider(page.adjust.brightness, { v -> vm.update(i) { it.copy(brightness = v) } }, valueRange = -80f..80f, modifier = Modifier.semantics { contentDescription = "Brightness" })
            Text("Contrast", style = MaterialTheme.typography.labelLarge)
            Slider(page.adjust.contrast, { v -> vm.update(i) { it.copy(contrast = v) } }, valueRange = 0.5f..2f, modifier = Modifier.semantics { contentDescription = "Contrast" })
        }
        SectionCard("Save") {
            OutlinedTextField(vm.name, { vm.name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") }, suffix = { Text(".pdf") })
            SwitchRow("Make text searchable (OCR)", vm.searchable, "Adds an invisible text layer so you can search and copy text. English text only; Hindi text is recognised but cannot be embedded as searchable text.") { vm.searchable = it }
            if (vm.searchable) RadioOptions(OcrLanguage.entries, lang, { it.label }) { vm.language = it }
        }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        val snapshot = vm.pages.toList()
        PrimaryAction("Create PDF (${snapshot.size} pages)", enabled = job == null && snapshot.isNotEmpty(), icon = Icons.Default.PictureAsPdf) {
            val name = vm.name.ifBlank { "Scan" } + ".pdf"; val ocr = vm.searchable
            Operations.run("Scan to PDF", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(name)
                var low = 0; var total = 0
                val stats = ScanPdfBuilder.build(snapshot.size, { idx ->
                    val src = ImageLoader.load(app, snapshot[idx].uri, 2400) ?: throw OperationFailed("Page ${idx + 1} could not be read.")
                    ImageProcessor.apply(src, snapshot[idx].adjust).also { if (it !== src) src.recycle() }
                }, if (ocr) { idx, bmp ->
                    val r = OcrEngine.recognize(bmp, lang, idx, bmp.width.toFloat(), bmp.height.toFloat())
                    low += r.lowConfidenceWords; total += r.totalWords
                    r.page.words
                } else null, out, p)
                val warnings = mutableListOf<String>()
                if (ocr) {
                    warnings.add("$total words recognised; $low with low confidence.")
                    if (stats.wordsSkipped > 0) warnings.add("${stats.wordsSkipped} recognised words (e.g. Hindi) could not be added to the searchable layer. Use Extract text to get them as text.")
                }
                OperationResult(OperationReport("Scan to PDF", listOf("${snapshot.size} scanned page(s)"), Outcome.SUCCESS, pagesSelected = snapshot.size, pagesProcessed = stats.pages, warnings = warnings,
                    notes = if (ocr) listOf(Limitations.OCR) else emptyList()), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
        SecondaryAction("Extract text only", enabled = job == null && snapshot.isNotEmpty(), icon = Icons.Default.TextFields) {
            Operations.run("Extract text", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                val sb = StringBuilder(); var low = 0; var total = 0
                snapshot.forEachIndexed { idx, s ->
                    p.step("Recognising page ${idx + 1} of ${snapshot.size}", idx.toFloat() / snapshot.size)
                    val src = ImageLoader.load(app, s.uri, 2400) ?: throw OperationFailed("Page ${idx + 1} could not be read.")
                    val bmp = ImageProcessor.apply(src, s.adjust); if (bmp !== src) src.recycle()
                    val r = OcrEngine.recognize(bmp, lang, idx, bmp.width.toFloat(), bmp.height.toFloat()); bmp.recycle()
                    low += r.lowConfidenceWords; total += r.totalWords
                    sb.append("--- Page ${idx + 1} ---\n").append(LineGrouper.group(r.page.words).joinToString("\n") { it.text }).append("\n\n")
                }
                val out = app.files.newOutputFile((vm.name.ifBlank { "Scan" }) + ".txt")
                out.writeText(sb.toString())
                OperationResult(OperationReport("Extract text", listOf("${snapshot.size} scanned page(s)"), Outcome.SUCCESS, "Scanned images – read with OCR", snapshot.size, snapshot.size,
                    warnings = listOf("$total words recognised; $low with low confidence. Check names, numbers and amounts carefully."), notes = listOf(Limitations.OCR)), listOf(OutputFile(out)), Preview.Text(sb.toString()))
            }
        }
    }
}

@Composable
private fun AdjustedImage(p: ScanPage, maxSide: Int, modifier: Modifier) {
    val app = DocDeskApp.instance
    val bmp by produceState<Bitmap?>(null, p.uri, p.adjust, maxSide) {
        value = withContext(Dispatchers.Default) { runCatching { ImageLoader.load(app, p.uri, maxSide)?.let { src -> ImageProcessor.apply(src, p.adjust).also { if (it !== src) src.recycle() } } }.getOrNull() }
    }
    val b = bmp
    if (b == null) Box(modifier.aspectRatio(0.707f), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(24.dp)) }
    else Image(b.asImageBitmap(), contentDescription = null, modifier = modifier.aspectRatio(b.width.toFloat() / b.height))
}
