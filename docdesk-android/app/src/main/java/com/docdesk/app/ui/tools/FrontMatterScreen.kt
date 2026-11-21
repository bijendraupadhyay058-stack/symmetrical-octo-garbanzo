package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.pdf.Bookmarks
import com.docdesk.app.pdf.FrontMatter
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.pdf.PdfTextExtractor
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
import com.docdesk.core.HeadingFinder

private enum class TocSource(val label: String) { NONE("No contents page"), BOOKMARKS("From the PDF's bookmarks"), HEADINGS("From headings found in the text") }

/** Cover page, contents page and blank pages. */
@Composable
fun FrontMatterScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var cover by remember { mutableStateOf(true) }
    var title by remember { mutableStateOf("") }; var subtitle by remember { mutableStateOf("") }
    var forWhom by remember { mutableStateOf("") }; var byWhom by remember { mutableStateOf("") }
    var date by remember { mutableStateOf(java.time.LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("d MMMM yyyy"))) }
    var toc by remember { mutableStateOf(TocSource.BOOKMARKS) }
    var blanks by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    ToolScaffold("Cover & contents pages", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val pdf = holder.info
        if (d == null || pdf == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "Add a cover page, contents page or blank pages", Icons.Default.MenuBook) { picker.launch(arrayOf("application/pdf")) }
            return@ToolScaffold
        }
        if (title.isEmpty()) title = FileRepository.baseName(d.name)
        FileHeader(d.name, "${pdf.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        SectionCard("Cover page") {
            SwitchRow("Add a cover page", cover) { cover = it }
            if (cover) {
                OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Title") })
                OutlinedTextField(subtitle, { subtitle = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Subtitle (optional)") })
                OutlinedTextField(forWhom, { forWhom = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Prepared for (optional)") })
                OutlinedTextField(byWhom, { byWhom = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Prepared by (optional)") })
                OutlinedTextField(date, { date = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Date") })
            }
        }
        SectionCard("Contents page") {
            RadioOptions(TocSource.entries, toc, { it.label }) { toc = it }
            Text("Entries link to their pages and show the final page numbers. To edit the entries first, use Bookmarks.", style = MaterialTheme.typography.bodySmall)
        }
        SectionCard("Blank pages") {
            OutlinedTextField(blanks, { blanks = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Insert a blank page after pages") }, placeholder = { Text("e.g. 3, 7 (0 = before page 1)") })
        }
        val blankList = blanks.split(',', ' ').mapNotNull { it.trim().takeIf { t -> t.isNotEmpty() } }.map { it.toIntOrNull() }
        val blanksOk = blankList.all { it != null && it in 0..pdf.pageCount }
        if (!blanksOk) Notice("Blank pages: enter page numbers between 0 and ${pdf.pageCount}, separated by commas.", NoteKind.WARNING)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create new PDF", enabled = job == null && blanksOk && (cover || toc != TocSource.NONE || blankList.isNotEmpty()) && (!cover || title.isNotBlank()), icon = Icons.Default.MenuBook) {
            val pw = holder.password; val c = if (cover) FrontMatter.Cover(title.trim(), subtitle.trim(), forWhom.trim(), byWhom.trim(), date.trim()) else null
            val src = toc; val bl = blankList.filterNotNull()
            Operations.run("Cover & contents pages", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (with cover).pdf")
                val notes = mutableListOf<String>(); var warn: String? = null
                val r = PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.ASSEMBLE)
                    val entries = when (src) {
                        TocSource.NONE -> null
                        TocSource.BOOKMARKS -> Bookmarks.readEntries(doc).also { if (it.isEmpty()) notes.add("This PDF has no bookmarks, so no contents page was made. Try “From headings”, or add bookmarks first.") }
                        TocSource.HEADINGS -> HeadingFinder.find((0 until doc.numberOfPages).map { PdfTextExtractor.extract(doc, it) }).also { if (it.isEmpty()) notes.add("No headings were found (scanned pages need OCR first), so no contents page was made.") }
                    }
                    val res = FrontMatter.apply(doc, c, entries, bl, p)
                    warn = PdfOps.keepProtectionForSave(doc, pw)
                    PdfOps.saveAtomically(doc, out); res
                }
                OperationResult(OperationReport("Cover & contents pages", listOf(d.name), Outcome.SUCCESS, warnings = listOfNotNull(warn),
                    notes = listOf("Added: ${r.coverPages} cover page(s), ${r.contentsPages} contents page(s) with ${r.contentsEntries} entr(ies), ${r.blankPages} blank page(s). The original is unchanged.") + notes),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}
