package com.docdesk.app.ui.tools

import android.graphics.Bitmap
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PdfAction
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
import com.docdesk.app.ui.convert.PageSelection
import com.docdesk.app.ui.convert.selectedPages
import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.pdmodel.PDResources
import com.tom_roush.pdfbox.pdmodel.graphics.form.PDFormXObject
import com.tom_roush.pdfbox.pdmodel.graphics.image.PDImageXObject
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

enum class ImageFormat(val label: String, val ext: String) { JPG("JPG (smaller files)", "jpg"), PNG("PNG (lossless, sharper text)", "png") }
enum class Dpi(val label: String, val dpi: Int) { LOW("Screen – 96 dpi", 96), MEDIUM("Standard – 150 dpi", 150), HIGH("Print – 300 dpi", 300) }

/** PDF pages → JPG/PNG images, or extract the pictures embedded in a PDF. */
@Composable
fun ExportImagesScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var extract by remember { mutableStateOf(false) }
    var format by remember { mutableStateOf(ImageFormat.JPG) }
    var dpi by remember { mutableStateOf(Dpi.MEDIUM) }
    var zip by remember { mutableStateOf(true) }
    var allPages by remember { mutableStateOf(true) }
    var range by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    ToolScaffold("PDF to JPG / PNG", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info
        if (d == null || info == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "Save pages as pictures, or pull out the photos inside", Icons.Default.Image) { picker.launch(arrayOf("application/pdf")) }
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        SectionCard("What to export") {
            RadioOptions(listOf(false, true), extract, { if (it) "Extract the pictures inside the PDF" else "Each page as an image" }) { extract = it }
            if (!extract) {
                RadioOptions(ImageFormat.entries, format, { it.label }) { format = it }
                RadioOptions(Dpi.entries, dpi, { it.label }) { dpi = it }
            }
        }
        val pages = selectedPages(info.pageCount, allPages, range).getOrNull()
        SectionCard("Pages") { PageSelection(info.pageCount, allPages, { allPages = it }, range) { range = it } }
        SwitchRow("Pack all images into one ZIP file", zip, "Easier to share many images at once.") { zip = it }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Export images", enabled = pages != null && job == null, icon = Icons.Default.Image) {
            val pw = holder.password; val sel = pages!!; val ex = extract; val fmt = format; val res = dpi.dpi; val asZip = zip
            val base = FileRepository.baseName(d.name)
            Operations.run(if (ex) "Extract images" else "PDF to images", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val files = mutableListOf<File>()
                val failed = mutableListOf<PageIssue>()
                if (!ex) {
                    val r = if (info.encrypted) PageRenderer.openDecryptedCopy(app, d.uri, pw ?: "", app.files.workDir) else PageRenderer.open(app, d.uri, app.files.workDir)
                    r.use {
                        for ((k, i) in sel.withIndex()) {
                            p.step("Page ${i + 1} (${k + 1} of ${sel.size})", k.toFloat() / sel.size)
                            val (w, _) = it.pageSize(i)
                            val bmp = it.render(i, (w / 72f * res).toInt(), cache = false)
                            if (bmp == null) { failed.add(PageIssue(i + 1, "Could not render")); continue }
                            val f = app.files.newOutputFile("$base - page ${i + 1}.${fmt.ext}")
                            f.outputStream().use { o -> bmp.compress(if (fmt == ImageFormat.PNG) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, 90, o) }
                            bmp.recycle(); files.add(f)
                        }
                    }
                } else {
                    PdfDocs.open(app, d.uri, pw).use { doc ->
                        PdfDocs.require(doc, PdfAction.EXTRACT)
                        val seen = HashSet<Any>()
                        fun walk(res2: PDResources?, page: Int, depth: Int) {
                            if (res2 == null || depth > 3) return
                            for (name: COSName in res2.xObjectNames.toList()) {
                                when (val x = runCatching { res2.getXObject(name) }.getOrNull()) {
                                    is PDFormXObject -> walk(x.resources, page, depth + 1)
                                    is PDImageXObject -> if (seen.add(x.cosObject) && x.width * x.height >= 64 * 64) {
                                        val bmp = runCatching { x.image }.getOrNull() ?: continue
                                        val jpg = x.suffix == "jpg" && !bmp.hasAlpha()
                                        val f = app.files.newOutputFile("$base - p${page + 1} image ${files.size + 1}.${if (jpg) "jpg" else "png"}")
                                        f.outputStream().use { o -> bmp.compress(if (jpg) Bitmap.CompressFormat.JPEG else Bitmap.CompressFormat.PNG, 95, o) }
                                        bmp.recycle(); files.add(f)
                                    }
                                    else -> Unit
                                }
                            }
                        }
                        for ((k, i) in sel.withIndex()) { p.step("Scanning page ${i + 1}", k.toFloat() / sel.size); walk(doc.getPage(i).resources, i, 0) }
                    }
                    if (files.isEmpty()) throw OperationFailed("No pictures were found in the selected pages. (Text and drawings are not pictures – use \"Each page as an image\" instead.)")
                }
                val outputs = if (asZip && files.size > 1) {
                    p.step("Creating ZIP…", 0.95f)
                    val z = app.files.newOutputFile("$base images.zip")
                    ZipOutputStream(z.outputStream().buffered()).use { zos -> files.forEach { f -> zos.putNextEntry(ZipEntry(f.name)); f.inputStream().use { it.copyTo(zos) }; zos.closeEntry() } }
                    listOf(OutputFile(z))
                } else files.map { OutputFile(it) }
                OperationResult(OperationReport(if (ex) "Extract images" else "PDF to images", listOf(d.name), if (failed.isEmpty()) Outcome.SUCCESS else Outcome.PARTIAL, pagesSelected = sel.size,
                    pagesProcessed = sel.size - failed.size, failedPages = failed, notes = listOf("${files.size} image(s) created.")), outputs, Preview.Image(files.first()))
            }
        }
        Text("Tip: PNG keeps text sharper; JPG makes smaller files for photos.", style = MaterialTheme.typography.bodySmall)
    }
    PasswordPromptFor(holder)
}
