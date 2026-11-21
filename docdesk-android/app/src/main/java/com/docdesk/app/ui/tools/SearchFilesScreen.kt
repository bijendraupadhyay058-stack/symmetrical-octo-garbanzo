package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.IconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.DocType
import com.docdesk.app.data.StoredFile
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.files.iconFor
import com.docdesk.core.DocBlock
import com.docdesk.core.DocReader
import com.docdesk.core.DocxReader
import com.docdesk.core.XlsReader
import com.docdesk.core.XlsxReader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private data class Hit(val file: StoredFile, val where: String, val snippet: String)

/** Searches the text inside every document in My Files (on the phone, nothing is indexed or uploaded). */
@Composable
fun SearchFilesScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    val hits = remember { mutableStateListOf<Hit>() }
    var status by remember { mutableStateOf<String?>(null) }
    var running by remember { mutableStateOf<Job?>(null) }

    fun snippet(text: String, i: Int, len: Int) = "…" + text.substring((i - 40).coerceAtLeast(0), (i + len + 60).coerceAtMost(text.length)).replace(Regex("""\s+"""), " ") + "…"

    fun search() {
        val q = query.trim(); if (q.length < 2) return
        running?.cancel(); hits.clear()
        running = scope.launch {
            val files = app.files.listMyFiles()
            var skipped = 0
            for ((k, f) in files.withIndex()) {
                status = "Searching ${k + 1} of ${files.size}: ${f.name}"
                val found = withContext(Dispatchers.IO) {
                    val out = mutableListOf<Hit>()
                    fun scan(text: String, where: String) { var i = text.indexOf(q, ignoreCase = true); var n = 0; while (i >= 0 && n < 3) { out.add(Hit(f, where, snippet(text, i, q.length))); n++; i = text.indexOf(q, i + q.length, ignoreCase = true) } }
                    runCatching {
                        when (f.type) {
                            DocType.PDF -> PdfDocs.open(f.file).use { doc -> for (p in 0 until doc.numberOfPages) { ensureActive(); scan(PdfTextExtractor.plainText(doc, p), "page ${p + 1}") } }
                            DocType.WORD, DocType.LEGACY_WORD -> (if (f.type == DocType.WORD) DocxReader.read(f.file.inputStream()) else DocReader.read(f.file.inputStream())).let { d ->
                                fun txt(b: DocBlock): String = when (b) { is DocBlock.Paragraph -> b.text; is DocBlock.Table -> b.rows.joinToString("\n") { r -> r.joinToString(" | ") { c -> c.blocks.joinToString(" ") { txt(it) } } }; else -> "" }
                                scan(d.blocks.joinToString("\n") { txt(it) }, "document")
                            }
                            DocType.EXCEL, DocType.LEGACY_EXCEL -> (if (f.type == DocType.EXCEL) XlsxReader.read(f.file.inputStream()) else XlsReader.read(f.file.inputStream())).sheets.forEach { s ->
                                scan(s.cells.toSortedMap().values.joinToString("\n") { r -> r.toSortedMap().values.joinToString(" | ") { it.display } }, "sheet ${s.name}")
                            }
                            DocType.TEXT -> scan(f.file.readText(), "text")
                            else -> Unit
                        }
                    }.onFailure { skipped++ }
                    out
                }
                hits.addAll(found)
            }
            status = "${hits.size} match(es) in ${hits.map { it.file }.distinct().size} file(s)" + if (skipped > 0) " · $skipped file(s) could not be searched (e.g. password-protected)" else ""
            running = null
        }
    }

    ToolScaffold("Search inside files", nav::back) {
        Row {
            OutlinedTextField(query, { query = it }, Modifier.weight(1f), singleLine = true, label = { Text("Word, name, amount, PAN…") },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { search() }))
            IconButton(onClick = { search() }) { Icon(Icons.Default.Search, "Search") }
        }
        Text("Searches the text of PDFs, Word, Excel and text files saved in My Files. Scanned PDFs are only searchable after making them searchable with OCR.", style = MaterialTheme.typography.bodySmall)
        if (running != null) { LinearProgressIndicator(Modifier.fillMaxWidth()); TextButton(onClick = { running?.cancel(); running = null; status = "Stopped." }) { Text("Stop") } }
        status?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        if (status != null && running == null && hits.isEmpty()) Notice("No matches.")
        hits.forEach { h ->
            ListItem(
                headlineContent = { Text(h.file.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                supportingContent = { Text("${h.where}: ${h.snippet}", maxLines = 3, overflow = TextOverflow.Ellipsis) },
                leadingContent = { Icon(iconFor(h.file.type), null) },
                modifier = Modifier.clickable {
                    val u = Uri.fromFile(h.file.file)
                    when (h.file.type) { DocType.PDF -> nav.to(Routes.VIEWER, u); DocType.WORD, DocType.LEGACY_WORD -> nav.to(Routes.WORD_PDF, u); DocType.EXCEL, DocType.LEGACY_EXCEL -> nav.to(Routes.EXCEL_PDF, u); else -> nav.to(Routes.FILES) }
                },
            )
        }
    }
}
