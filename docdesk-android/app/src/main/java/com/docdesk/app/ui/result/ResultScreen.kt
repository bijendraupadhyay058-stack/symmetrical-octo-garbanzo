package com.docdesk.app.ui.result

import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.SaveAlt
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.DocType
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.KeyValue
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.app.ui.components.formatSize
import com.docdesk.core.Align
import com.docdesk.core.DocBlock
import com.docdesk.core.DocDocument
import com.docdesk.core.XCell
import com.docdesk.core.XSheet
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ResultScreen(nav: Nav, id: Long) {
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val entry = remember(id) { app.results.get(id) }
    var message by remember { mutableStateOf<Pair<String, NoteKind>?>(null) }
    var saved by remember { mutableStateOf<List<File>?>(null) }
    var exporting by remember { mutableStateOf<OutputFile?>(null) }
    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri: Uri? ->
        val f = exporting ?: return@rememberLauncherForActivityResult
        exporting = null
        if (uri != null) scope.launch {
            message = withContext(Dispatchers.IO) { runCatching { app.files.exportTo(f.file, uri) } }
                .fold({ "Saved \"${f.displayName}\" to the selected location." to NoteKind.INFO }, { it.userMessage() to NoteKind.ERROR })
        }
    }

    ToolScaffold("Result", nav::back) {
        if (entry == null) {
            Notice("This result is no longer available (the app was restarted). Saved files are in My Files.", NoteKind.WARNING)
            SecondaryAction("Go to My Files", icon = Icons.Default.Folder) { nav.to(Routes.FILES) }
            return@ToolScaffold
        }
        val (result, historyId) = entry
        ReportCard(result.report)
        message?.let { (m, k) -> Notice(m, k) { message = null } }
        val outputs = result.outputs.filter { it.file.exists() }
        if (outputs.isNotEmpty()) {
            SectionCard(if (outputs.size == 1) "Output file" else "${outputs.size} output files") {
                outputs.forEach { o ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(o.displayName, style = MaterialTheme.typography.bodyLarge)
                            Text(formatSize(o.file.length()), style = MaterialTheme.typography.bodySmall)
                        }
                        TextButton(onClick = { exporting = o; saver.launch(o.displayName) }) { Text("Save to device") }
                    }
                }
                if (saved == null) PrimaryAction(if (outputs.size == 1) "Save to My Files" else "Save all to My Files", icon = Icons.Default.SaveAlt) {
                    scope.launch {
                        val r = withContext(Dispatchers.IO) { runCatching { outputs.map { app.files.saveToMyFiles(it.file, it.displayName) } } }
                        r.onSuccess { files ->
                            saved = files
                            message = "Saved to My Files." to NoteKind.INFO
                            historyId?.let { hid -> withContext(Dispatchers.IO) { app.history.setOutputs(hid, files.map { it.path }) } }
                        }.onFailure { message = it.userMessage() to NoteKind.ERROR }
                    }
                } else Notice("Saved in My Files: ${saved!!.joinToString { it.name }}")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SecondaryAction("Share", icon = Icons.Default.Share, modifier = Modifier.weight(1f)) {
                        runCatching { context.startActivity(app.files.shareIntent((saved ?: outputs.map { it.file }))) }
                    }
                    if (outputs.size == 1) SecondaryAction("Open with", icon = Icons.Default.OpenInNew, modifier = Modifier.weight(1f)) {
                        runCatching { context.startActivity(app.files.openWithIntent(saved?.first() ?: outputs[0].file)) }
                            .onFailure { message = "No app on this phone can open ${DocType.of(outputs[0].displayName).label} files. You can still share or save it." to NoteKind.WARNING }
                    }
                }
                val pdf = (saved ?: outputs.map { it.file }).firstOrNull { it.name.endsWith(".pdf", true) }
                if (pdf != null && outputs.size == 1) SecondaryAction("Open in DocDesk viewer") { nav.to(Routes.VIEWER, Uri.fromFile(pdf)) }
                Text("Unsaved results are deleted automatically within a day.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        when (val p = result.preview) {
            is Preview.Pdf -> if (p.file.exists()) PdfPreview(p.file)
            is Preview.Word -> SectionCard("Preview (text and structure)") { WordPreview(p.doc) }
            is Preview.Sheets -> SectionCard("Preview") { SheetsPreview(p.sheets) }
            is Preview.Text -> SectionCard("Preview") { Text(p.text.take(5000), style = MaterialTheme.typography.bodyMedium) }
            is Preview.Image -> SectionCard("Preview") {
                val bmp = remember(p.file) { runCatching { BitmapFactory.decodeFile(p.file.path, BitmapFactory.Options().apply { inSampleSize = 2 }) }.getOrNull() }
                if (bmp != null) Image(bmp.asImageBitmap(), "First image", Modifier.fillMaxWidth().border(1.dp, MaterialTheme.colorScheme.outlineVariant))
            }
            null -> Unit
        }
    }
}

@Composable
private fun ReportCard(r: OperationReport) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val (icon, tint) = when (r.outcome) {
                Outcome.SUCCESS -> Icons.Default.CheckCircle to MaterialTheme.colorScheme.primary
                Outcome.FAILED -> Icons.Default.Error to MaterialTheme.colorScheme.error
                else -> Icons.Default.Warning to MaterialTheme.colorScheme.tertiary
            }
            Icon(icon, null, tint = tint)
            Text("${r.operation}: ${r.outcome.label}", Modifier.padding(start = 10.dp), style = MaterialTheme.typography.titleMedium)
        }
        if (r.inputNames.isNotEmpty()) KeyValue("Input", r.inputNames.joinToString(", "))
        r.documentKind?.let { KeyValue("Document type", it) }
        if (r.pagesSelected != null) KeyValue("Pages processed", "${r.pagesProcessed ?: 0} of ${r.pagesSelected}")
        if (r.failedPages.isNotEmpty()) {
            Text("Pages that could not be processed", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.error)
            r.failedPages.forEach { Text("• Page ${it.page}: ${it.message}", style = MaterialTheme.typography.bodySmall) }
        }
        if (r.warnings.isNotEmpty()) {
            Text("Please review", style = MaterialTheme.typography.labelLarge)
            r.warnings.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) }
        }
        if (r.checks.isNotEmpty()) {
            Text("Checks", style = MaterialTheme.typography.labelLarge)
            r.checks.forEach { Text(if (it.startsWith("Table ")) it else "• $it", style = MaterialTheme.typography.bodySmall) }
        }
        r.notes.forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

@Composable
private fun PdfPreview(file: File) {
    val renderer = remember(file) { runCatching { PageRenderer.open(file) }.getOrNull() }
    DisposableEffect(renderer) { onDispose { renderer?.close() } }
    if (renderer == null) { Notice("Preview unavailable for this PDF.", NoteKind.WARNING); return }
    var shown by remember { mutableIntStateOf(3) }
    SectionCard("Preview · ${renderer.pageCount} page(s)") {
        (0 until minOf(shown, renderer.pageCount)).forEach { i ->
            Text("Page ${i + 1}", style = MaterialTheme.typography.labelMedium)
            PageImage(renderer, i, 900, Modifier.border(1.dp, MaterialTheme.colorScheme.outlineVariant))
        }
        if (shown < renderer.pageCount) TextButton(onClick = { shown += 5 }) { Text("Show more pages") }
    }
}

@Composable
fun WordPreview(doc: DocDocument, limit: Int = 120) {
    Column(Modifier.fillMaxWidth().background(androidx.compose.ui.graphics.Color.White).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        var page = 1
        Text("Page 1", style = MaterialTheme.typography.labelSmall, color = androidx.compose.ui.graphics.Color.Gray)
        doc.blocks.take(limit).forEach { b ->
            when (b) {
                is DocBlock.PageBreak -> { page++; Text("— Page $page —", style = MaterialTheme.typography.labelSmall, color = androidx.compose.ui.graphics.Color.Gray) }
                is DocBlock.Paragraph -> {
                    val size = when (b.headingLevel) { -1 -> 24.sp; 1 -> 20.sp; 2 -> 18.sp; 3 -> 16.sp; else -> 14.sp }
                    val bold = b.headingLevel != 0 || (b.runs.isNotEmpty() && b.runs.all { it.bold })
                    Text((b.listLabel?.let { "$it " } ?: "") + b.text, fontSize = size, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
                        fontStyle = if (b.runs.isNotEmpty() && b.runs.all { it.italic }) FontStyle.Italic else FontStyle.Normal,
                        textAlign = when (b.align) { Align.CENTER -> TextAlign.Center; Align.RIGHT -> TextAlign.End; Align.JUSTIFY -> TextAlign.Justify; else -> TextAlign.Start },
                        color = androidx.compose.ui.graphics.Color.Black, modifier = Modifier.fillMaxWidth().padding(start = (b.indentLeftPt / 2).dp))
                }
                is DocBlock.Table -> Column(Modifier.horizontalScroll(rememberScrollState())) {
                    b.rows.take(30).forEach { row ->
                        Row { row.forEach { c -> Text(c.blocks.filterIsInstance<DocBlock.Paragraph>().joinToString(" ") { it.text }, Modifier.width(110.dp).border(0.5.dp, androidx.compose.ui.graphics.Color.Gray).padding(4.dp), fontSize = 12.sp, color = androidx.compose.ui.graphics.Color.Black) } }
                    }
                    if (b.rows.size > 30) Text("… ${b.rows.size - 30} more rows", fontSize = 12.sp, color = androidx.compose.ui.graphics.Color.Gray)
                }
                is DocBlock.Image -> {
                    val bmp = remember(b) { runCatching { BitmapFactory.decodeByteArray(b.bytes, 0, b.bytes.size, BitmapFactory.Options().apply { inSampleSize = 4 }) }.getOrNull() }
                    if (bmp != null) Image(bmp.asImageBitmap(), "Image from the document", Modifier.heightIn(max = 160.dp))
                    else Text("[image]", color = androidx.compose.ui.graphics.Color.Gray)
                }
            }
        }
        if (doc.blocks.size > limit) Text("… preview shortened. Open the file to see everything.", style = MaterialTheme.typography.bodySmall, color = androidx.compose.ui.graphics.Color.Gray)
    }
}

@Composable
private fun SheetsPreview(sheets: List<XSheet>) {
    var tab by remember { mutableIntStateOf(0) }
    ScrollableTabRow(selectedTabIndex = tab, edgePadding = 0.dp) { sheets.forEachIndexed { i, s -> Tab(selected = tab == i, onClick = { tab = i }, text = { Text(s.name) }) } }
    val s = sheets[tab.coerceIn(0, sheets.lastIndex)]
    Column(Modifier.horizontalScroll(rememberScrollState())) {
        s.rows.take(60).forEach { row ->
            Row {
                row.forEach { c ->
                    val text = when (val x = c.cell) {
                        is XCell.Text -> x.value
                        is XCell.Number -> com.docdesk.core.NumberFormatter.format(x.value.toDouble(), x.format ?: "General")
                        is XCell.Date -> com.docdesk.core.NumberFormatter.format(x.serial.toDouble(), x.format)
                        XCell.Blank -> ""
                    }
                    Text(text, Modifier.width(120.dp).border(0.5.dp, MaterialTheme.colorScheme.outlineVariant)
                        .background(if (c.highlight) MaterialTheme.colorScheme.tertiaryContainer else MaterialTheme.colorScheme.surface).padding(4.dp),
                        fontSize = 12.sp, fontWeight = if (c.bold) FontWeight.Bold else FontWeight.Normal, maxLines = 3)
                }
            }
        }
        if (s.rows.size > 60) Text("… ${s.rows.size - 60} more rows in the file", style = MaterialTheme.typography.bodySmall)
    }
}
