package com.docdesk.app.ui.home

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.Brush
import androidx.compose.material.icons.filled.CallMerge
import androidx.compose.material.icons.filled.CallSplit
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.FileOpen
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.TableChart
import androidx.compose.material.icons.filled.TextSnippet
import androidx.compose.material.icons.filled.ViewModule
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.DocType
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.history.statusLabel
import java.text.DateFormat
import java.util.Date

private data class ToolItem(val label: String, val hint: String, val icon: ImageVector, val route: String)

private val tools = listOf(
    ToolItem("PDF to Excel", "Tables to .xlsx", Icons.Default.TableChart, Routes.PDF_EXCEL),
    ToolItem("PDF to Word", "Editable .docx", Icons.Default.Description, Routes.PDF_WORD),
    ToolItem("Excel to PDF", "Sheets to PDF", Icons.Default.GridOn, Routes.EXCEL_PDF),
    ToolItem("Word to PDF", ".docx to PDF", Icons.Default.PictureAsPdf, Routes.WORD_PDF),
    ToolItem("Edit PDF", "Annotate & sign", Icons.Default.Brush, Routes.EDIT),
    ToolItem("Merge PDFs", "Combine files", Icons.Default.CallMerge, Routes.MERGE),
    ToolItem("Split PDF", "By pages or ranges", Icons.Default.CallSplit, Routes.SPLIT),
    ToolItem("Organise Pages", "Reorder, rotate, delete", Icons.Default.ViewModule, Routes.ORGANIZE),
    ToolItem("Scan & OCR", "Camera to PDF/text", Icons.Default.DocumentScanner, Routes.SCAN),
    ToolItem("Recent Files", "Your documents", Icons.Default.History, Routes.FILES),
)

@Composable
fun HomeScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val history by app.history.all.collectAsStateWithLifecycle(emptyList())
    var query by rememberSaveable { mutableStateOf("") }
    var chosenPdf by remember { mutableStateOf<Uri?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        runCatching { context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        when (app.files.describe(uri).type) {
            DocType.PDF -> chosenPdf = uri
            DocType.WORD -> nav.to(Routes.WORD_PDF, uri)
            DocType.EXCEL -> nav.to(Routes.EXCEL_PDF, uri)
            DocType.LEGACY_WORD, DocType.LEGACY_EXCEL -> message = "Older .doc and .xls files are not supported yet. Open the file in Word, Excel or Google Docs/Sheets and save it as .docx or .xlsx first."
            DocType.IMAGE -> message = "To turn photos into a PDF, use Scan & OCR and choose \"Import images\"."
            else -> message = "This file type is not supported. Choose a PDF, Word (.docx) or Excel (.xlsx) file."
        }
    }

    val files = remember(query, history) { if (query.isBlank()) emptyList() else app.files.listMyFiles().filter { it.name.contains(query, true) }.sortedByDescending { it.modified }.take(8) }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 150.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("DocDesk", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }.padding(top = 16.dp))
                Text("Convert, edit and organise PDFs on your phone. Files are processed on this device.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                PrimaryAction("Select a file", icon = Icons.Default.FileOpen) { picker.launch(arrayOf("application/pdf", DocType.WORD.mime, DocType.EXCEL.mime, DocType.LEGACY_WORD.mime, DocType.LEGACY_EXCEL.mime, "image/*")) }
                message?.let { Notice(it, NoteKind.WARNING) { message = null } }
                job?.let { JobProgressCard(it) { app.jobs.cancel() } }
                OutlinedTextField(
                    value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(), singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Search, null) }, label = { Text("Search recent files") },
                )
                files.forEach { f ->
                    ListItem(
                        headlineContent = { Text(f.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Text(f.type.label) },
                        leadingContent = { Icon(Icons.AutoMirrored.Filled.InsertDriveFile, null) },
                        modifier = Modifier.heightIn(min = 56.dp).clickable {
                            if (f.type == DocType.PDF) nav.to(Routes.VIEWER, Uri.fromFile(f.file))
                            else runCatching { context.startActivity(app.files.openWithIntent(f.file)) }.onFailure { message = "No app on this phone can open ${f.type.label} files." }
                        },
                    )
                }
                if (query.isNotBlank() && files.isEmpty()) Text("No files in My Files match \"$query\".", style = MaterialTheme.typography.bodyMedium)
                Text("Tools", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
            }
        }
        items(tools, key = { it.route + it.label }) { t -> ToolCard(t) { nav.to(t.route) } }
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Spacer(Modifier.size(8.dp))
                Text("Recent activity", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                if (history.isEmpty()) Text("Nothing yet. Your conversions and edits will appear here.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                history.take(5).forEach { h ->
                    ListItem(
                        headlineContent = { Text(h.operation + if (h.inputNames.isNotBlank()) " · ${h.inputNames}" else "", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Text("${statusLabel(h.status)} · ${DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(h.timestamp))}") },
                        leadingContent = { Icon(Icons.Default.TextSnippet, null) },
                    )
                }
            }
        }
    }

    chosenPdf?.let { uri ->
        ModalBottomSheet(onDismissRequest = { chosenPdf = null }) {
            Text("What would you like to do?", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            listOf(
                Triple("View", Icons.Default.PictureAsPdf, Routes.VIEWER), Triple("Edit / annotate", Icons.Default.Brush, Routes.EDIT),
                Triple("Organise pages", Icons.Default.ViewModule, Routes.ORGANIZE), Triple("Split", Icons.Default.CallSplit, Routes.SPLIT),
                Triple("Convert to Excel", Icons.Default.TableChart, Routes.PDF_EXCEL), Triple("Convert to Word", Icons.Default.Description, Routes.PDF_WORD),
                Triple("Extract text (OCR)", Icons.Default.DocumentScanner, Routes.OCR),
            ).forEach { (label, icon, route) ->
                ListItem(
                    headlineContent = { Text(label) }, leadingContent = { Icon(icon, null) },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable { chosenPdf = null; nav.to(route, uri) },
                )
            }
            Spacer(Modifier.size(24.dp))
        }
    }
}

@Composable
private fun ToolCard(t: ToolItem, onClick: () -> Unit) {
    Surface(onClick = onClick, shape = RoundedCornerShape(16.dp), color = MaterialTheme.colorScheme.surfaceContainer, modifier = Modifier.fillMaxWidth().heightIn(min = 104.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(shape = RoundedCornerShape(10.dp), color = MaterialTheme.colorScheme.primaryContainer) {
                    Icon(t.icon, contentDescription = null, tint = MaterialTheme.colorScheme.onPrimaryContainer, modifier = Modifier.padding(8.dp).size(24.dp))
                }
            }
            Text(t.label, style = MaterialTheme.typography.titleMedium, maxLines = 2)
            Text(t.hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
        }
    }
}
