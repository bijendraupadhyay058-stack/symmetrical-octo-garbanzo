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
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Bookmarks
import androidx.compose.material.icons.filled.Brush
import androidx.compose.material.icons.automirrored.filled.BrandingWatermark
import androidx.compose.material.icons.filled.Compress
import androidx.compose.material.icons.filled.Crop
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material.icons.filled.ContentCut
import androidx.compose.material.icons.filled.AspectRatio
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.automirrored.filled.ManageSearch
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.DynamicFeed
import androidx.compose.material.icons.filled.Compare
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.FormatListNumbered
import androidx.compose.material.icons.automirrored.filled.NoteAdd
import androidx.compose.material.icons.automirrored.filled.CallMerge
import androidx.compose.material.icons.automirrored.filled.CallSplit
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.FileOpen
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.TableChart
import androidx.compose.material.icons.automirrored.filled.TextSnippet
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
import kotlinx.coroutines.launch
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

private enum class Category(val title: String) { ACCOUNTING("Accounting"), CONVERT("Convert"), EDIT("Edit & sign"), ORGANISE("Organise"), PRIVACY("Privacy & files") }

private data class ToolItem(val label: String, val hint: String, val icon: ImageVector, val route: String, val category: Category = Category.CONVERT)

private val tools = listOf(
    ToolItem("Create PDF", "Word, Excel (.doc/.xls too), photos → PDF", Icons.AutoMirrored.Filled.NoteAdd, Routes.CREATE, Category.CONVERT),
    ToolItem("Bank Statements", "Many statements → one Excel/CSV", Icons.Default.AccountBalance, Routes.STATEMENTS, Category.ACCOUNTING),
    ToolItem("GST Invoices", "Invoices → Excel register", Icons.AutoMirrored.Filled.ReceiptLong, Routes.INVOICES, Category.ACCOUNTING),
    ToolItem("PDF to Excel", "Tables to .xlsx", Icons.Default.TableChart, Routes.PDF_EXCEL, Category.CONVERT),
    ToolItem("PDF to Word", "Editable .docx", Icons.Default.Description, Routes.PDF_WORD, Category.CONVERT),
    ToolItem("Excel to PDF", "Sheets to PDF", Icons.Default.GridOn, Routes.EXCEL_PDF, Category.CONVERT),
    ToolItem("Word to PDF", ".docx to PDF", Icons.Default.PictureAsPdf, Routes.WORD_PDF, Category.CONVERT),
    ToolItem("Edit PDF", "Annotate & sign", Icons.Default.Brush, Routes.EDIT, Category.EDIT),
    ToolItem("Merge PDFs", "Combine files", Icons.AutoMirrored.Filled.CallMerge, Routes.MERGE, Category.ORGANISE),
    ToolItem("Split PDF", "By pages or ranges", Icons.AutoMirrored.Filled.CallSplit, Routes.SPLIT, Category.ORGANISE),
    ToolItem("Organise Pages", "Reorder, rotate, delete", Icons.Default.ViewModule, Routes.ORGANIZE, Category.ORGANISE),
    ToolItem("Scan & OCR", "Camera to PDF/text", Icons.Default.DocumentScanner, Routes.SCAN, Category.CONVERT),
    ToolItem("Fill Form", "Fill & flatten PDF forms", Icons.Default.EditNote, Routes.FORM, Category.EDIT),
    ToolItem("Protect PDF", "Encrypt with password", Icons.Default.Lock, Routes.PROTECT, Category.PRIVACY),
    ToolItem("Remove Password", "Unlock a PDF you can open", Icons.Default.LockOpen, Routes.UNLOCK, Category.PRIVACY),
    ToolItem("Find & Redact", "Remove PAN, Aadhaar, A/c nos.", Icons.Default.Shield, Routes.REDACT, Category.PRIVACY),
    ToolItem("Batch Process", "Many PDFs at once", Icons.Default.DynamicFeed, Routes.BATCH, Category.ORGANISE),
    ToolItem("Digital Signature", "Sign & verify with certificate", Icons.Default.VerifiedUser, Routes.SIGN, Category.EDIT),
    ToolItem("Compare PDFs", "Find changes between versions", Icons.Default.Compare, Routes.COMPARE, Category.ORGANISE),
    ToolItem("PDF to JPG/PNG", "Pages or pictures as images", Icons.Default.Image, Routes.IMAGES, Category.CONVERT),
    ToolItem("Watermark", "CONFIDENTIAL, DRAFT…", Icons.AutoMirrored.Filled.BrandingWatermark, Routes.WATERMARK, Category.EDIT),
    ToolItem("Page Numbers", "Header, footer, Bates", Icons.Default.FormatListNumbered, Routes.NUMBERS, Category.EDIT),
    ToolItem("Compress PDF", "Make files smaller", Icons.Default.Compress, Routes.COMPRESS, Category.ORGANISE),
    ToolItem("Compress to Size", "Fit portal limits: 500 KB, 2 MB…", Icons.Default.UploadFile, Routes.TO_SIZE, Category.ORGANISE),
    ToolItem("Split by Size", "Parts under 10 MB etc.", Icons.Default.ContentCut, Routes.SPLIT_SIZE, Category.ORGANISE),
    ToolItem("Resize Pages", "Make all pages A4/Letter", Icons.Default.AspectRatio, Routes.FIT, Category.ORGANISE),
    ToolItem("Crop Pages", "Trim white borders & margins", Icons.Default.Crop, Routes.CROP, Category.ORGANISE),
    ToolItem("Flatten PDF", "Make comments & forms permanent", Icons.Default.Layers, Routes.FLATTEN, Category.EDIT),
    ToolItem("Repair PDF", "Fix files that won't open", Icons.Default.Build, Routes.REPAIR, Category.PRIVACY),
    ToolItem("Bookmarks", "Add or auto-create a table of contents", Icons.Default.Bookmarks, Routes.BOOKMARKS, Category.EDIT),
    ToolItem("Document properties", "Title, author, hidden info", Icons.Default.Info, Routes.PROPERTIES, Category.PRIVACY),
    ToolItem("Attachments", "Files inside a PDF: add, save, remove", Icons.Default.AttachFile, Routes.ATTACHMENTS, Category.EDIT),
    ToolItem("Make Links Clickable", "Web, e-mail and phone links", Icons.Default.Link, Routes.AUTOLINK, Category.EDIT),
    ToolItem("Search in Files", "Find text inside documents", Icons.AutoMirrored.Filled.ManageSearch, Routes.SEARCH, Category.PRIVACY),
    ToolItem("Recent Files", "Your documents", Icons.Default.History, Routes.FILES, Category.PRIVACY),
)

@Composable
fun HomeScreen(nav: Nav) {
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val history by app.history.all.collectAsStateWithLifecycle(emptyList())
    var query by rememberSaveable { mutableStateOf("") }
    val settings by app.settings.settings.collectAsStateWithLifecycle(com.docdesk.app.data.AppSettings())
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val shown = remember(query) { if (query.isBlank()) tools else tools.filter { it.label.contains(query, true) || it.hint.contains(query, true) || it.category.title.contains(query, true) } }
    var chosenPdf by remember { mutableStateOf<Uri?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        runCatching { context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        when (app.files.describe(uri).type) {
            DocType.PDF -> chosenPdf = uri
            DocType.WORD, DocType.LEGACY_WORD -> nav.to(Routes.WORD_PDF, uri)
            DocType.EXCEL, DocType.LEGACY_EXCEL -> nav.to(Routes.EXCEL_PDF, uri)
            DocType.IMAGE -> nav.to(Routes.CREATE, uri)
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
                var crashed by remember { mutableStateOf(com.docdesk.app.data.ProblemReports.hasCrash()) }
                if (crashed) {
                    Notice("DocDesk closed unexpectedly last time. Sending a problem report helps fix it (it contains technical details only – no documents, file names or personal data).", NoteKind.WARNING) { com.docdesk.app.data.ProblemReports.dismissCrash(); crashed = false }
                    com.docdesk.app.ui.components.SecondaryAction("Send problem report") { runCatching { context.startActivity(com.docdesk.app.data.ProblemReports.shareIntent()) }; com.docdesk.app.data.ProblemReports.dismissCrash(); crashed = false }
                }
                job?.let { JobProgressCard(it) { app.jobs.cancel() } }
                OutlinedTextField(
                    value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(), singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Search, null) }, label = { Text("Search tools and files") },
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
                if (query.isNotBlank() && files.isEmpty() && shown.isEmpty()) Text("No tools or files match \"$query\".", style = MaterialTheme.typography.bodyMedium)
            }
        }
        val fav = tools.filter { it.route in settings.favourites }
        val sections: List<Pair<String, List<ToolItem>>> = if (query.isNotBlank()) listOf("Tools" to shown)
            else listOfNotNull(fav.takeIf { it.isNotEmpty() }?.let { "★ Favourites" to it }) + Category.entries.map { c -> c.title to tools.filter { it.category == c } }
        for ((title, list) in sections) {
            if (list.isEmpty()) continue
            item(span = { GridItemSpan(maxLineSpan) }, key = "h-$title") { Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }.padding(top = 8.dp)) }
            items(list, key = { "$title-${it.route}-${it.label}" }) { t ->
                ToolCard(t, favourite = t.route in settings.favourites, onFavourite = { scope.launch { app.settings.toggleFavourite(t.route) } }) { nav.to(t.route) }
            }
        }
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Spacer(Modifier.size(8.dp))
                Text("Recent activity", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                if (history.isEmpty()) Text("Nothing yet. Your conversions and edits will appear here.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                history.take(5).forEach { h ->
                    ListItem(
                        headlineContent = { Text(h.operation + if (h.inputNames.isNotBlank()) " · ${h.inputNames}" else "", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Text("${statusLabel(h.status)} · ${DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(h.timestamp))}") },
                        leadingContent = { Icon(Icons.AutoMirrored.Filled.TextSnippet, null) },
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
                Triple("Organise pages", Icons.Default.ViewModule, Routes.ORGANIZE), Triple("Split", Icons.AutoMirrored.Filled.CallSplit, Routes.SPLIT),
                Triple("Convert to Excel", Icons.Default.TableChart, Routes.PDF_EXCEL), Triple("Convert to Word", Icons.Default.Description, Routes.PDF_WORD),
                Triple("Extract text (OCR)", Icons.Default.DocumentScanner, Routes.OCR),
                Triple("Fill form", Icons.Default.EditNote, Routes.FORM),
                Triple("Add watermark", Icons.AutoMirrored.Filled.BrandingWatermark, Routes.WATERMARK),
                Triple("Add page numbers / header / footer", Icons.Default.FormatListNumbered, Routes.NUMBERS),
                Triple("Compress", Icons.Default.Compress, Routes.COMPRESS),
                Triple("Compress to a size limit", Icons.Default.UploadFile, Routes.TO_SIZE),
                Triple("Split by size", Icons.Default.ContentCut, Routes.SPLIT_SIZE),
                Triple("Resize pages to A4/Letter", Icons.Default.AspectRatio, Routes.FIT),
                Triple("Crop pages", Icons.Default.Crop, Routes.CROP),
                Triple("Flatten (make permanent)", Icons.Default.Layers, Routes.FLATTEN),
                Triple("Edit bookmarks", Icons.Default.Bookmarks, Routes.BOOKMARKS),
                Triple("Document properties", Icons.Default.Info, Routes.PROPERTIES),
                Triple("Attachments", Icons.Default.AttachFile, Routes.ATTACHMENTS),
                Triple("Make links clickable", Icons.Default.Link, Routes.AUTOLINK),
                Triple("Protect with password", Icons.Default.Lock, Routes.PROTECT),
                Triple("Remove password", Icons.Default.LockOpen, Routes.UNLOCK),
                Triple("Find & redact personal data", Icons.Default.Shield, Routes.REDACT),
                Triple("Bank statement to Excel/CSV", Icons.Default.AccountBalance, Routes.STATEMENTS),
                Triple("Sign digitally / check signatures", Icons.Default.VerifiedUser, Routes.SIGN),
                Triple("Compare with another version", Icons.Default.Compare, Routes.COMPARE),
                Triple("Save pages as JPG/PNG", Icons.Default.Image, Routes.IMAGES),
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
private fun ToolCard(t: ToolItem, favourite: Boolean, onFavourite: () -> Unit, onClick: () -> Unit) {
    Surface(onClick = onClick, shape = RoundedCornerShape(16.dp), color = MaterialTheme.colorScheme.surfaceContainer, modifier = Modifier.fillMaxWidth().heightIn(min = 104.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(shape = RoundedCornerShape(10.dp), color = MaterialTheme.colorScheme.primaryContainer) {
                    Icon(t.icon, contentDescription = null, tint = MaterialTheme.colorScheme.onPrimaryContainer, modifier = Modifier.padding(8.dp).size(24.dp))
                }
                Spacer(Modifier.weight(1f))
                androidx.compose.material3.IconButton(onClick = onFavourite) {
                    Icon(if (favourite) Icons.Default.Star else Icons.Default.StarBorder, contentDescription = if (favourite) "Remove ${t.label} from favourites" else "Add ${t.label} to favourites",
                        tint = if (favourite) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Text(t.label, style = MaterialTheme.typography.titleMedium, maxLines = 2)
            Text(t.hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
        }
    }
}
