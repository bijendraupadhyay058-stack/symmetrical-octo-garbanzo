package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.ViewModule
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.pdf.LayoutTools
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
import com.docdesk.core.PaperSize

/** Pages per sheet (2/4/6/8/9/16) or a fold-and-staple booklet, ready to print. */
@Composable
fun PrintLayoutScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var booklet by remember { mutableStateOf(false) }
    var perSheet by remember { mutableIntStateOf(2) }
    var paper by remember { mutableStateOf(PaperSize.A4) }
    var borders by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    ToolScaffold("Print layout", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val pdf = holder.info
        if (d == null || pdf == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF", "Several pages per sheet, or a booklet", Icons.Default.ViewModule) { picker.launch(arrayOf("application/pdf")) }
            Notice("Save paper by printing 2, 4 or more pages on each sheet, or make a booklet you fold in the middle and staple. Text stays sharp – pages aren't turned into pictures.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pdf.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        SectionCard("Layout") {
            RadioOptions(listOf(false, true), booklet, { if (it) "Booklet" else "Pages per sheet" },
                { if (it) "Two pages side by side, in fold order. Print double-sided, flipping on the short edge, then fold the stack." else "Pages are placed left to right, top to bottom." }) { booklet = it }
            if (!booklet) Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(2, 4, 6, 8, 9, 16).forEach { n -> FilterChip(perSheet == n, { perSheet = n }, label = { Text("$n") }) }
            }
            if (!booklet) SwitchRow("Thin border around each page", borders) { borders = it }
        }
        SectionCard("Paper") {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { PaperSize.entries.forEach { p -> FilterChip(paper == p, { paper = p }, label = { Text(p.label) }) } }
        }
        val sheets = if (booklet) ((pdf.pageCount + 3) / 4) else (pdf.pageCount + perSheet - 1) / perSheet
        Text(if (booklet) "$sheets sheet(s) of paper, printed on both sides." + if (pdf.pageCount % 4 != 0) " ${4 - pdf.pageCount % 4} blank page(s) will be added at the end." else ""
             else "$sheets page(s) instead of ${pdf.pageCount}.", style = MaterialTheme.typography.bodyMedium)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Create layout", enabled = job == null, icon = if (booklet) Icons.Default.AutoStories else Icons.Default.ViewModule) {
            val pw = holder.password; val b = booklet; val n = perSheet; val pp = paper; val br = borders
            Operations.run("Print layout", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + if (b) " (booklet).pdf" else " ($n per sheet).pdf")
                val made = PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.ASSEMBLE)
                    if (b) LayoutTools.booklet(doc, out, pp, p) else LayoutTools.nUp(doc, out, pp, n, 18f, br, p)
                }
                OperationResult(OperationReport("Print layout", listOf(d.name), Outcome.SUCCESS, pagesProcessed = pdf.pageCount,
                    checks = if (b) listOf("Print on both sides with “flip on short edge”. Try one sheet first to check your printer's settings.") else emptyList(),
                    notes = listOf("$made page(s) created on ${pp.label} paper. Links and form fields are not kept in this layout. The original is unchanged.")),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}

/** Merges a scan of the fronts and a scan of the backs into one document in page order. */
@Composable
fun CollateScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val fronts = remember { PdfInputHolder(scope, wantRenderer = false) }
    val backs = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { fronts.close(); backs.close() } }
    val pickF = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> fronts.select(u) } }
    val pickB = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> backs.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var reversed by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    ToolScaffold("Combine double-sided scans", nav::back) {
        listOfNotNull(fronts.error, backs.error).forEach { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        Notice("For a scanner or copier that only scans one side: scan all the fronts, turn the stack over and scan the backs. DocDesk puts the pages back in order: front 1, back 1, front 2…")
        val f = fronts.doc; val fi = fronts.info; val b = backs.doc; val bi = backs.info
        SectionCard("1. Fronts (odd pages)") {
            if (f == null || fi == null) FilePickTarget(if (fronts.loading) "Opening…" else "Choose the fronts scan", "Pages 1, 3, 5…", Icons.Default.PictureAsPdf) { pickF.launch(arrayOf("application/pdf")) }
            else FileHeader(f.name, "${fi.pageCount} pages", Icons.Default.PictureAsPdf) { pickF.launch(arrayOf("application/pdf")) }
        }
        SectionCard("2. Backs (even pages)") {
            if (b == null || bi == null) FilePickTarget(if (backs.loading) "Opening…" else "Choose the backs scan", "Pages 2, 4, 6…", Icons.Default.PictureAsPdf) { pickB.launch(arrayOf("application/pdf")) }
            else FileHeader(b.name, "${bi.pageCount} pages", Icons.Default.PictureAsPdf) { pickB.launch(arrayOf("application/pdf")) }
            SwitchRow("Backs were scanned in reverse order", reversed, "Usual when you turn the whole stack over: the last back is scanned first.") { reversed = it }
        }
        if (fi != null && bi != null && fi.pageCount != bi.pageCount)
            Notice("The scans have different page counts (${fi.pageCount} fronts, ${bi.pageCount} backs). The extra pages are added at the end – check the result.", NoteKind.WARNING)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Combine", enabled = job == null && fi != null && bi != null, icon = Icons.Default.SwapVert) {
            val fd = f!!; val bd = b!!; val fp = fronts.password; val bp = backs.password; val rev = reversed
            Operations.run("Combine double-sided scans", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(FileRepository.baseName(fd.name) + " (combined).pdf")
                val n = PdfDocs.open(app, fd.uri, fp).use { a -> PdfDocs.open(app, bd.uri, bp).use { c ->
                    PdfDocs.require(a, PdfAction.ASSEMBLE); PdfDocs.require(c, PdfAction.ASSEMBLE)
                    LayoutTools.collate(a, c, rev, out, p)
                } }
                OperationResult(OperationReport("Combine double-sided scans", listOf(fd.name, bd.name), Outcome.SUCCESS, pagesProcessed = n,
                    checks = listOf("Flip through the first few pages: if back pages appear in the wrong order, run it again with “reverse order” switched the other way."),
                    notes = listOf("$n pages in the combined file. The originals are unchanged.")), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(fronts)
    PasswordPromptFor(backs)
}
