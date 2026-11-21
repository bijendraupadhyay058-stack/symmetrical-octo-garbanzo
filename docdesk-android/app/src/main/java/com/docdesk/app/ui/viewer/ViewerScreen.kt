package com.docdesk.app.ui.viewer

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.runtime.mutableStateMapOf
import com.docdesk.app.pdf.Bookmark
import com.docdesk.app.pdf.Bookmarks
import com.docdesk.core.PageText
import com.docdesk.core.TextSelection
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Brush
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.GridView
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.ZoomIn
import androidx.compose.material.icons.filled.ZoomOut
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.docdesk.app.DocDeskApp
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.TextInputDialog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private data class Hit(val page: Int, val rects: List<FloatArray>, val snippet: String)

@Composable
fun ViewerScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }

    val listState = rememberLazyListState()
    var scale by remember { mutableFloatStateOf(1f) }
    var offsetX by remember { mutableFloatStateOf(0f) }
    var thumbs by remember { mutableStateOf(false) }
    var goTo by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    var searchOpen by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    var hits by remember { mutableStateOf<List<Hit>?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    val current by remember { derivedStateOf { listState.firstVisibleItemIndex } }
    var bookmarks by remember { mutableStateOf<List<Bookmark>>(emptyList()) }
    var speaking by remember { mutableStateOf(false) }
    val reader = remember { com.docdesk.app.pdf.ReadAloud(context) { on, msg -> speaking = on; if (msg != null) message = msg } }
    DisposableEffect(Unit) { onDispose { reader.release() } }
    var showBookmarks by remember { mutableStateOf(false) }
    val pageWords = remember { mutableStateMapOf<Int, PageText>() }
    var selPage by remember { mutableStateOf<Int?>(null) }
    var selA by remember { mutableStateOf(Offset.Zero) }
    var selB by remember { mutableStateOf(Offset.Zero) }
    val clipboard = androidx.compose.ui.platform.LocalClipboardManager.current
    LaunchedEffect(holder.info) {
        bookmarks = emptyList(); pageWords.clear(); selPage = null
        val d = holder.doc ?: return@LaunchedEffect
        if (holder.info == null) return@LaunchedEffect
        bookmarks = withContext(Dispatchers.IO) { runCatching { PdfDocs.open(app, d.uri, holder.password).use { Bookmarks.read(it) } }.getOrDefault(emptyList()) }
    }
    fun loadWords(page: Int) {
        if (pageWords.containsKey(page)) return
        val d = holder.doc ?: return
        scope.launch {
            val t = withContext(Dispatchers.IO) {
                runCatching { PdfDocs.open(app, d.uri, holder.password).use { PdfDocs.require(it, PdfAction.EXTRACT); PdfTextExtractor.extract(it, page) } }
            }
            t.onSuccess { pageWords[page] = it }.onFailure { message = it.userMessage(); selPage = null }
        }
    }
    fun selection(): List<TextSelection.LineRect> {
        val p = selPage ?: return emptyList(); val t = pageWords[p] ?: return emptyList()
        return TextSelection.select(t.words, selA.x * t.width, selA.y * t.height, selB.x * t.width, selB.y * t.height)
    }
    val r = holder.renderer

    fun search() {
        val d = holder.doc ?: return
        if (query.isBlank()) return
        searching = true; hits = null
        scope.launch {
            val q = query.trim().lowercase()
            val res = withContext(Dispatchers.IO) {
                runCatching {
                    PdfDocs.open(app, d.uri, holder.password).use { doc ->
                        PdfDocs.require(doc, PdfAction.EXTRACT)
                        (0 until doc.numberOfPages).mapNotNull { p ->
                            val t = PdfTextExtractor.extract(doc, p)
                            val words = t.words
                            val terms = q.split(Regex("\\s+"))
                            val rects = mutableListOf<FloatArray>()
                            var snippet = ""
                            for (i in words.indices) {
                                if (i + terms.size > words.size) break
                                val ok = terms.indices.all { k -> if (terms.size == 1) words[i].text.lowercase().contains(terms[0]) else words[i + k].text.lowercase().trim(',', '.', ':', ';') == terms[k] || (k == terms.lastIndex && words[i + k].text.lowercase().startsWith(terms[k])) || (k == 0 && words[i].text.lowercase().endsWith(terms[0])) }
                                if (ok) {
                                    for (k in terms.indices) { val w = words[i + k]; rects.add(floatArrayOf(w.x / t.width, w.y / t.height, w.right / t.width, w.bottom / t.height)) }
                                    if (snippet.isEmpty()) snippet = words.subList((i - 5).coerceAtLeast(0), (i + terms.size + 5).coerceAtMost(words.size)).joinToString(" ") { it.text }
                                }
                            }
                            if (rects.isEmpty()) null else Hit(p, rects, snippet)
                        }
                    }
                }
            }
            searching = false
            res.onSuccess { hits = it; if (it.isEmpty()) message = "No matches for \"$query\". Scanned pages have no searchable text – use Scan & OCR to make a searchable copy." }
                .onFailure { message = it.userMessage() }
        }
    }

    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text(holder.doc?.name ?: "View PDF", maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
                    if (r != null) Text("Page ${current + 1} of ${r.pageCount}", style = MaterialTheme.typography.bodySmall)
                }
            },
            navigationIcon = { IconButton(onClick = nav::back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            actions = {
                if (r != null) {
                    IconButton(onClick = { searchOpen = !searchOpen }) { Icon(Icons.Default.Search, "Search in document") }
                    if (bookmarks.isNotEmpty()) IconButton(onClick = { showBookmarks = true }) { Icon(Icons.AutoMirrored.Filled.List, "Contents (bookmarks)") }
                    IconButton(onClick = { thumbs = true }) { Icon(Icons.Default.GridView, "Page thumbnails") }
                    Box {
                        IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, "More actions") }
                        DropdownMenu(menu, { menu = false }) {
                            DropdownMenuItem(text = { Text("Go to page…") }, onClick = { menu = false; goTo = true })
                            DropdownMenuItem(text = { Text("Read this page aloud") }, onClick = {
                                menu = false
                                val d = holder.doc
                                if (d != null) scope.launch {
                                    val page = current
                                    withContext(Dispatchers.IO) {
                                        runCatching {
                                            PdfDocs.open(app, d.uri, holder.password).use { doc ->
                                                val perm = doc.currentAccessPermission
                                                if (doc.isEncrypted && !perm.isOwnerPermission && !perm.canExtractForAccessibility()) throw com.docdesk.app.jobs.OperationFailed("This PDF's permissions don't allow reading its text aloud.")
                                                PdfTextExtractor.plainText(doc, page)
                                            }
                                        }
                                    }.onSuccess { reader.speak(it) }.onFailure { message = it.userMessage() }
                                }
                            })
                            DropdownMenuItem(text = { Text("Edit / annotate") }, leadingIcon = { Icon(Icons.Default.Brush, null) }, onClick = { menu = false; nav.to(Routes.EDIT, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Organise pages") }, onClick = { menu = false; nav.to(Routes.ORGANIZE, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Convert to Word") }, onClick = { menu = false; nav.to(Routes.PDF_WORD, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Convert to Excel") }, onClick = { menu = false; nav.to(Routes.PDF_EXCEL, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Fill form") }, onClick = { menu = false; nav.to(Routes.FORM, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Add watermark") }, onClick = { menu = false; nav.to(Routes.WATERMARK, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Page numbers / header / footer") }, onClick = { menu = false; nav.to(Routes.NUMBERS, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Compress") }, onClick = { menu = false; nav.to(Routes.COMPRESS, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Protect with password") }, onClick = { menu = false; nav.to(Routes.PROTECT, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Remove password") }, onClick = { menu = false; nav.to(Routes.UNLOCK, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Find & redact personal data") }, onClick = { menu = false; nav.to(Routes.REDACT, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Sign digitally / check signatures") }, onClick = { menu = false; nav.to(Routes.SIGN, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Compare with another version") }, onClick = { menu = false; nav.to(Routes.COMPARE, holder.doc?.uri) })
                            DropdownMenuItem(text = { Text("Save pages as JPG/PNG") }, onClick = { menu = false; nav.to(Routes.IMAGES, holder.doc?.uri) })
                            if (holder.doc?.uri?.scheme != "file") DropdownMenuItem(text = { Text("Save a copy to My Files") }, onClick = {
                                menu = false
                                scope.launch {
                                    message = withContext(Dispatchers.IO) { runCatching { app.files.importToMyFiles(holder.doc!!.uri) } }.fold({ "Saved \"${it.name}\" to My Files." }, { it.userMessage() })
                                }
                            })
                            DropdownMenuItem(text = { Text("Open another PDF") }, leadingIcon = { Icon(Icons.Default.FolderOpen, null) }, onClick = { menu = false; picker.launch(arrayOf("application/pdf")) })
                        }
                    }
                }
            },
        )
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            holder.error?.let { Box(Modifier.padding(16.dp)) { Notice(it, NoteKind.ERROR) } }
            message?.let { Box(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) { Notice(it, NoteKind.INFO) { message = null } } }
            if (searchOpen && r != null) {
                Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(query, { query = it }, Modifier.weight(1f), singleLine = true, label = { Text("Find text") },
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { search() }))
                    IconButton(onClick = { search() }) { Icon(Icons.Default.Search, "Search") }
                    IconButton(onClick = { searchOpen = false; hits = null; query = "" }) { Icon(Icons.Default.Close, "Close search") }
                }
                if (searching) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
                hits?.takeIf { it.isNotEmpty() }?.let { h ->
                    Text("${h.sumOf { it.rects.size }} matches on ${h.size} page(s)", Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.bodySmall)
                    LazyColumn(Modifier.fillMaxWidth().heightIn(max = 160.dp)) {
                        itemsIndexed(h) { _, hit ->
                            ListItem(headlineContent = { Text("Page ${hit.page + 1}") }, supportingContent = { Text(hit.snippet, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                                modifier = Modifier.clickable { scope.launch { listState.scrollToItem(hit.page) } })
                        }
                    }
                }
            }
            when {
                holder.loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) { CircularProgressIndicator(); Text("Opening…", Modifier.padding(top = 8.dp)) }
                }
                r == null -> Box(Modifier.padding(16.dp)) { FilePickTarget("Choose a PDF to view", "Opens from your phone, SD card or cloud storage", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) } }
                else -> BoxWithConstraints(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceContainerHigh)) {
                    val density = LocalDensity.current
                    val widthPx = with(density) { maxWidth.toPx() }
                    val bucket = when { scale > 1.6f -> 2f; scale > 1.15f -> 1.5f; else -> 1f }
                    val renderW = (widthPx * bucket).toInt()
                    LazyColumn(
                        state = listState,
                        modifier = Modifier.fillMaxSize()
                            .pointerInput(Unit) {
                                awaitEachGesture {
                                    awaitFirstDown(requireUnconsumed = false)
                                    do {
                                        val event = awaitPointerEvent()
                                        if (event.changes.size >= 2) {
                                            scale = (scale * event.calculateZoom()).coerceIn(1f, 4f)
                                            val maxX = (widthPx * (scale - 1f)) / 2f
                                            offsetX = (offsetX + event.calculatePan().x).coerceIn(-maxX, maxX)
                                            event.changes.forEach { it.consume() }
                                        } else if (scale > 1f) {
                                            val maxX = (widthPx * (scale - 1f)) / 2f
                                            offsetX = (offsetX + event.calculatePan().x).coerceIn(-maxX, maxX)
                                        }
                                    } while (event.changes.any { it.pressed })
                                }
                            }
                            .graphicsLayer { scaleX = scale; scaleY = scale; translationX = offsetX },
                        contentPadding = PaddingValues(vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        itemsIndexed(List(r.pageCount) { it }, key = { _, i -> i }) { _, i ->
                            Box(Modifier.padding(horizontal = 8.dp).pointerInput(i) {
                                // Long-press and drag to select text, like in Acrobat.
                                detectDragGesturesAfterLongPress(
                                    onDragStart = { o -> selPage = i; selA = Offset(o.x / size.width, o.y / size.height); selB = selA; loadWords(i) },
                                    onDrag = { c, _ -> selB = Offset(c.position.x / size.width, c.position.y / size.height) },
                                )
                            }) {
                                PageImage(r, i, renderW, description = "Page ${i + 1} of ${r.pageCount}. Long-press and drag to select text.")
                                if (selPage == i) Canvas(Modifier.matchParentSize()) {
                                    val t = pageWords[i]
                                    if (t != null) selection().forEach { lr ->
                                        drawRect(Color(0x553D7BFF), topLeft = Offset(lr.x / t.width * size.width, lr.top / t.height * size.height), size = Size((lr.right - lr.x) / t.width * size.width, (lr.bottom - lr.top) / t.height * size.height))
                                    }
                                }
                                val pageHits = hits?.firstOrNull { it.page == i }
                                if (pageHits != null) Canvas(Modifier.matchParentSize()) {
                                    pageHits.rects.forEach { rc ->
                                        drawRect(Color(0x66FFC107), topLeft = Offset(rc[0] * size.width, rc[1] * size.height), size = Size((rc[2] - rc[0]) * size.width, (rc[3] - rc[1]) * size.height))
                                    }
                                }
                            }
                        }
                    }
                    if (speaking) Surface(Modifier.align(Alignment.TopEnd).padding(12.dp), shape = RoundedCornerShape(24.dp), tonalElevation = 4.dp, shadowElevation = 4.dp) {
                        TextButton(onClick = { reader.stop() }) { Text("■ Stop reading") }
                    }
                    if (selPage != null) Surface(Modifier.align(Alignment.BottomStart).padding(16.dp), shape = RoundedCornerShape(24.dp), tonalElevation = 4.dp, shadowElevation = 4.dp) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            val sel = selection()
                            TextButton(enabled = sel.isNotEmpty(), onClick = {
                                clipboard.setText(androidx.compose.ui.text.AnnotatedString(sel.joinToString("\n") { it.text }))
                                message = "Copied ${sel.sumOf { it.text.length }} characters."; selPage = null
                            }) { Icon(Icons.Default.ContentCopy, null); Text(" Copy") }
                            TextButton(onClick = { selPage = null }) { Text("Cancel") }
                        }
                    }
                    // Zoom buttons (accessible alternative to pinch).
                    Surface(Modifier.align(Alignment.BottomEnd).padding(16.dp), shape = RoundedCornerShape(24.dp), tonalElevation = 4.dp, shadowElevation = 4.dp) {
                        Row {
                            IconButton(onClick = { scale = (scale - 0.5f).coerceAtLeast(1f); if (scale == 1f) offsetX = 0f }) { Icon(Icons.Default.ZoomOut, "Zoom out") }
                            Text("${(scale * 100).toInt()}%", Modifier.align(Alignment.CenterVertically).semantics { contentDescription = "Zoom ${(scale * 100).toInt()} percent" })
                            IconButton(onClick = { scale = (scale + 0.5f).coerceAtMost(4f) }) { Icon(Icons.Default.ZoomIn, "Zoom in") }
                        }
                    }
                }
            }
        }
    }
    PasswordPromptFor(holder)
    if (thumbs && r != null) ModalBottomSheet(onDismissRequest = { thumbs = false }) {
        LazyVerticalGrid(GridCells.Adaptive(100.dp), contentPadding = PaddingValues(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(r.pageCount) { i ->
                Column(Modifier.clickable { thumbs = false; scope.launch { listState.scrollToItem(i) } }, horizontalAlignment = Alignment.CenterHorizontally) {
                    PageImage(r, i, 220, description = "Go to page ${i + 1}")
                    Text("${i + 1}", style = MaterialTheme.typography.labelMedium, color = if (i == current) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                }
            }
        }
    }
    if (showBookmarks && r != null) ModalBottomSheet(onDismissRequest = { showBookmarks = false }) {
        Text("Contents", Modifier.padding(horizontal = 24.dp, vertical = 8.dp), style = MaterialTheme.typography.titleMedium)
        LazyColumn {
            itemsIndexed(bookmarks) { _, b ->
                ListItem(
                    headlineContent = { Text(b.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                    supportingContent = b.page?.let { p -> { Text("Page ${p + 1}") } },
                    modifier = Modifier.padding(start = (b.level * 16).dp).clickable(enabled = b.page != null) { showBookmarks = false; b.page?.let { p -> scope.launch { listState.scrollToItem(p) } } },
                )
            }
        }
    }
    if (goTo && r != null) TextInputDialog("Go to page", "${current + 1}", "Page (1–${r.pageCount})", confirm = "Go", onConfirm = { v ->
        v.trim().toIntOrNull()?.takeIf { it in 1..r.pageCount }?.let { p -> scope.launch { listState.scrollToItem(p - 1) } } ?: run { message = "Enter a page number between 1 and ${r.pageCount}." }
        goTo = false
    }, onDismiss = { goTo = false })
}
