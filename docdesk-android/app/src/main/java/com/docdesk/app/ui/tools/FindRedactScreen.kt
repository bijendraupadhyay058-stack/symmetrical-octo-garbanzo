package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageTextSource
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.edit.Annot
import com.docdesk.app.edit.NRect
import com.docdesk.app.edit.RedactionApplier
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.CheckRow
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.PageText
import com.docdesk.core.SensitiveFinder
import com.docdesk.core.SensitiveKind
import com.docdesk.core.SensitiveMatch

/** Find personal/financial identifiers or chosen words, confirm, and redact them permanently. */
@Composable
fun FindRedactScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val settings by app.settings.settings.collectAsStateWithLifecycle(com.docdesk.app.data.AppSettings())
    var kinds by remember { mutableStateOf(SensitiveKind.entries.toSet() - SensitiveKind.ACCOUNT - SensitiveKind.CUSTOM) }
    var terms by remember { mutableStateOf("") }
    var useOcr by remember { mutableStateOf(true) }
    var found by remember { mutableStateOf<Pair<List<SensitiveMatch>, Map<Int, PageText>>?>(null) }
    var chosen by remember { mutableStateOf(setOf<Int>()) }
    var error by remember { mutableStateOf<String?>(null) }

    ToolScaffold("Find & redact", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info
        if (d == null || info == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF to clean", "Find and permanently remove PAN, Aadhaar, account numbers and more", Icons.Default.Shield) { picker.launch(arrayOf("application/pdf")) }
            Notice("Use before sharing statements, KYC copies or invoices. You review every match before anything is removed.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")); found = null }
        val f = found
        if (f == null) {
            SectionCard("Look for") {
                SensitiveKind.entries.filter { it != SensitiveKind.CUSTOM }.forEach { k -> CheckRow(k.label, k in kinds) { on -> kinds = if (on) kinds + k else kinds - k } }
                OutlinedTextField(terms, { terms = it }, Modifier.fillMaxWidth(), label = { Text("Also find these words (comma-separated)") }, placeholder = { Text("e.g. client name, address") })
                SwitchRow("Read scanned pages with OCR", useOcr) { useOcr = it }
            }
            job?.let { JobProgressCard(it) { app.jobs.cancel() } }
            PrimaryAction("Find", enabled = job == null && (kinds.isNotEmpty() || terms.isNotBlank()), icon = Icons.Default.Search) {
                val pw = holder.password; val k = kinds; val t = terms.split(',').map { it.trim() }.filter { it.isNotEmpty() }; val ocr = if (useOcr) OcrMode.AUTO else OcrMode.NEVER
                val lang = settings.ocrLanguage
                app.jobs.start("Searching", { p ->
                    val pages = mutableMapOf<Int, PageText>(); val all = mutableListOf<SensitiveMatch>()
                    PdfDocs.open(app, d.uri, pw).use { doc ->
                        PdfDocs.require(doc, PdfAction.EXTRACT)
                        PageTextSource(app, d.uri, pw, doc, app.files.workDir, ocr, lang).use { src ->
                            for (i in 0 until doc.numberOfPages) {
                                p.step("Page ${i + 1} of ${doc.numberOfPages}", i.toFloat() / doc.numberOfPages)
                                val pt = src.get(i); pages[i] = pt
                                all.addAll(SensitiveFinder.find(pt, k, t))
                            }
                        }
                    }
                    all.toList() to pages.toMap()
                }) { r -> r.onSuccess { found = it; chosen = it.first.indices.toSet() }.onFailure { error = it.userMessage() } }
            }
        } else {
            val (matches, pages) = f
            if (matches.isEmpty()) {
                Notice("Nothing found. Scanned pages without OCR, or very unusual formats, can't be searched.", NoteKind.INFO)
                TextButton(onClick = { found = null }) { Text("Search again") }
                return@ToolScaffold
            }
            SectionCard("${matches.size} match(es) – untick anything that should stay") {
                androidx.compose.foundation.layout.Row {
                    TextButton(onClick = { chosen = matches.indices.toSet() }) { Text("Select all") }
                    TextButton(onClick = { chosen = emptySet() }) { Text("Select none") }
                    TextButton(onClick = { found = null }) { Text("Search again") }
                }
                matches.withIndex().groupBy { it.value.kind }.forEach { (kind, list) ->
                    Text("${kind.label} (${list.size})", style = MaterialTheme.typography.labelLarge)
                    list.forEach { (i, m) -> CheckRow("p${m.page + 1}: ${m.text}", i in chosen) { on -> chosen = if (on) chosen + i else chosen - i } }
                }
            }
            Notice("Pages with redactions are rebuilt as images so the information is permanently removed; those pages won't be searchable afterwards.", NoteKind.WARNING)
            job?.let { JobProgressCard(it) { app.jobs.cancel() } }
            PrimaryAction("Redact ${chosen.size} item(s)", enabled = chosen.isNotEmpty() && job == null, icon = Icons.Default.Shield) {
                val pw = holder.password
                var id = 1L
                val boxes = chosen.sorted().map { matches[it] }.flatMap { m ->
                    val pt = pages.getValue(m.page)
                    m.rects.map { r -> Annot.Box(id++, m.page, Annot.BoxKind.REDACT, NRect((r[0] - 1.5f) / pt.width, (r[1] - 1f) / pt.height, (r[2] + 1.5f) / pt.width, (r[3] + 1f) / pt.height), android.graphics.Color.BLACK, 1f) }
                }
                val count = chosen.size; val kindsUsed = chosen.map { matches[it].kind.label }.distinct()
                Operations.run("Find & redact", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                    val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (redacted).pdf")
                    val note = RedactionApplier.redactToFile(app, d.uri, pw, boxes, out, app.files.workDir, p)
                    val redPages = boxes.map { it.page + 1 }.distinct().sorted()
                    OperationResult(OperationReport("Find & redact", listOf(d.name), Outcome.SUCCESS, pagesSelected = redPages.size, pagesProcessed = redPages.size,
                        warnings = listOf("Automatic detection can miss items written in unusual ways (e.g. split across lines or in images). Check the result before sharing."),
                        notes = listOfNotNull("$count item(s) redacted (${kindsUsed.joinToString()}) on page(s) ${redPages.joinToString()}. Those pages are now images.", note)),
                        listOf(OutputFile(out)), Preview.Pdf(out))
                }
            }
        }
    }
    PasswordPromptFor(holder)
}
