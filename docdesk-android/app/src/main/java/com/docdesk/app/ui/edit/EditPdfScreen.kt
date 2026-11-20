package com.docdesk.app.ui.edit

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Redo
import androidx.compose.material.icons.automirrored.filled.Undo
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.edit.Annot
import com.docdesk.app.edit.AnnotationWriter
import com.docdesk.app.edit.NPoint
import com.docdesk.app.edit.NRect
import com.docdesk.app.edit.Tool
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.scan.ImageLoader
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.TextInputDialog
import com.docdesk.app.ui.components.ToolScaffold
import java.io.File
import kotlin.math.hypot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val palette = listOf(0xFFFFEB3B, 0xFF4CAF50, 0xFF03A9F4, 0xFFE91E63, 0xFFF44336, 0xFF1E4FA3, 0xFF000000).map { it.toInt() }

@Composable
fun EditPdfScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()

    var page by remember { mutableIntStateOf(0) }
    var tool by remember { mutableStateOf(Tool.HIGHLIGHT) }
    var color by remember { mutableIntStateOf(palette[0]) }
    var stroke by remember { mutableFloatStateOf(2f) }
    var textSize by remember { mutableFloatStateOf(14f) }
    val annots = remember { mutableStateListOf<Annot>() }
    val undo = remember { mutableStateListOf<List<Annot>>() }
    val redo = remember { mutableStateListOf<List<Annot>>() }
    var selectedId by remember { mutableStateOf<Long?>(null) }
    var nextId by remember { mutableStateOf(1L) }
    var pendingText by remember { mutableStateOf<Pair<NPoint, Tool>?>(null) }
    var pendingPicture by remember { mutableStateOf<Pair<NPoint, Boolean>?>(null) }
    var signatureAt by remember { mutableStateOf<NPoint?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var showEditInfo by remember { mutableStateOf(false) }
    var outName by remember { mutableStateOf("") }
    var currentPageSize by remember { mutableStateOf<Pair<Int, Int>?>(null) }
    LaunchedEffect(holder.doc) { holder.doc?.let { outName = FileRepository.baseName(it.name) + " (edited)" } }

    fun commit(change: () -> Unit) { undo.add(annots.toList()); if (undo.size > 60) undo.removeAt(0); redo.clear(); change() }

    fun placePicture(uri: Uri, at: NPoint, signature: Boolean) = scope.launch {
        val file = withContext(Dispatchers.IO) {
            runCatching {
                val bmp = ImageLoader.load(app, uri, 1600) ?: return@runCatching null
                val f = File(app.files.workDir, "img_${System.nanoTime()}.png")
                f.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
                Triple(f, bmp.width, bmp.height).also { bmp.recycle() }
            }.getOrNull()
        }
        if (file == null) { error = "The image could not be opened."; return@launch }
        addPicture(file.first, file.second, file.third, at, signature, page, nextId++, currentPageSize) { a -> commit { annots.add(a) } }
    }
    val imagePicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        val p = pendingPicture; pendingPicture = null
        if (uri != null && p != null) placePicture(uri, p.first, p.second)
    }

    val r = holder.renderer
    val info = holder.info
    ToolScaffold("Edit PDF", nav::back, actions = {
        IconButton(onClick = { redo.add(annots.toList()); val prev = undo.removeAt(undo.lastIndex); annots.clear(); annots.addAll(prev) }, enabled = undo.isNotEmpty()) { Icon(Icons.AutoMirrored.Filled.Undo, "Undo") }
        IconButton(onClick = { undo.add(annots.toList()); val n = redo.removeAt(redo.lastIndex); annots.clear(); annots.addAll(n) }, enabled = redo.isNotEmpty()) { Icon(Icons.AutoMirrored.Filled.Redo, "Redo") }
    }) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        if (r == null || info == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF to annotate", "Highlight, draw, add text, notes, images and signatures", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
            return@ToolScaffold
        }
        // Tool chips
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Tool.entries.forEach { t -> FilterChip(selected = tool == t, onClick = { tool = t; selectedId = null }, label = { Text(t.label) }) }
        }
        if (tool != Tool.WHITEOUT && tool != Tool.IMAGE && tool != Tool.SIGNATURE && tool != Tool.SELECT) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            palette.forEach { c ->
                Surface(shape = CircleShape, color = Color(c), border = BorderStroke(if (c == color) 3.dp else 1.dp, if (c == color) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.outline),
                    onClick = { color = c }, modifier = Modifier.size(36.dp).semantics { contentDescription = "Colour ${colorName(c)}" + if (c == color) ", selected" else "" }) {}
            }
        }
        when (tool) {
            Tool.PEN, Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.UNDERLINE, Tool.STRIKE -> Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Thickness ${"%.1f".format(stroke)} pt", Modifier.padding(end = 8.dp)); Slider(stroke, { stroke = it }, valueRange = 0.5f..8f, modifier = Modifier.weight(1f))
            }
            Tool.TEXT -> Row(verticalAlignment = Alignment.CenterVertically) { Text("Text size ${textSize.toInt()} pt", Modifier.padding(end = 8.dp)); Slider(textSize, { textSize = it }, valueRange = 6f..48f, modifier = Modifier.weight(1f)) }
            else -> Unit
        }
        Text(hintFor(tool), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

        // Page with drawing overlay
        val pageSize by produceState<Pair<Int, Int>?>(null, r, page) { value = runCatching { r.pageSize(page) }.getOrNull() }
        LaunchedEffect(pageSize) { currentPageSize = pageSize }
        var canvasSize by remember { mutableStateOf(IntSize.Zero) }
        var draft by remember { mutableStateOf<Annot?>(null) }
        Box(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerHigh).padding(4.dp)) {
            PageImage(r, page, 1400, description = "Page ${page + 1} of ${r.pageCount}")
            val ptToPx = pageSize?.let { canvasSize.width.toFloat() / it.first } ?: 1f
            val pictureCache = remember { HashMap<String, androidx.compose.ui.graphics.ImageBitmap?>() }
            Canvas(Modifier.matchParentSize()
                .pointerInput(tool, page, color, stroke, textSize, selectedId) {
                    canvasSize = size
                    awaitEachGesture {
                        val down = awaitFirstDown()
                        val w = size.width.toFloat(); val h = size.height.toFloat()
                        fun n(o: Offset) = NPoint((o.x / w).coerceIn(0f, 1f), (o.y / h).coerceIn(0f, 1f))
                        val start = n(down.position)
                        val pts = mutableListOf(start)
                        var moved = false
                        val selected = annots.firstOrNull { it.id == selectedId }
                        val resizing = tool == Tool.SELECT && selected != null && (selected is Annot.Picture || selected is Annot.Box) &&
                            hypot((start.x - selected.bounds().right) * w, (start.y - selected.bounds().bottom) * h) < 48f
                        var moveBase: Annot? = null
                        if (tool == Tool.SELECT && selected != null && selected.bounds().contains(start, 0.02f)) moveBase = selected
                        do {
                            val ev = awaitPointerEvent()
                            val c = ev.changes.firstOrNull() ?: break
                            val p = n(c.position)
                            if (hypot((p.x - start.x) * w, (p.y - start.y) * h) > 12f) moved = true
                            if (moved) {
                                c.consume()
                                when (tool) {
                                    Tool.PEN -> { pts.add(p); draft = Annot.Ink(0, page, pts.toList(), color, stroke) }
                                    Tool.LINE, Tool.ARROW -> draft = Annot.Line(0, page, start, p, tool == Tool.ARROW, color, stroke)
                                    Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKE, Tool.RECT, Tool.ELLIPSE, Tool.WHITEOUT -> draft = Annot.Box(0, page, boxKind(tool), NRect.of(start, p), if (tool == Tool.WHITEOUT) android.graphics.Color.WHITE else color, stroke)
                                    Tool.SELECT -> moveBase?.let { base ->
                                        val idx = annots.indexOfFirst { it.id == base.id }
                                        if (idx >= 0) annots[idx] = if (resizing) resize(base, p) else base.moved(p.x - start.x, p.y - start.y)
                                    }
                                    else -> Unit
                                }
                            }
                        } while (ev.changes.any { it.pressed })
                        val d = draft; draft = null
                        if (moved) {
                            when (tool) {
                                Tool.SELECT -> moveBase?.let { base ->
                                    // Record the move for undo: previous state = list with the original item.
                                    undo.add(annots.map { if (it.id == base.id) base else it }); redo.clear()
                                }
                                else -> if (d != null) {
                                    val fixed = when (d) { is Annot.Ink -> d.copy(id = nextId++); is Annot.Line -> d.copy(id = nextId++); is Annot.Box -> d.copy(id = nextId++); else -> d }
                                    val tooSmall = (d is Annot.Box && (d.rect.width * w < 6 || d.rect.height * h < 4 && d.kind != Annot.BoxKind.UNDERLINE && d.kind != Annot.BoxKind.STRIKE))
                                    if (!tooSmall) commit { annots.add(fixed) }
                                }
                            }
                        } else {
                            // Tap
                            when (tool) {
                                Tool.TEXT, Tool.NOTE -> pendingText = start to tool
                                Tool.IMAGE -> { pendingPicture = start to false; imagePicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                                Tool.SIGNATURE -> signatureAt = start
                                Tool.SELECT -> selectedId = annots.lastOrNull { it.page == page && it.bounds().contains(start, 0.015f) }?.id
                                else -> Unit
                            }
                        }
                    }
                }) {
                annots.filter { it.page == page }.forEach { drawAnnot(it, ptToPx, it.id == selectedId, pictureCache) }
                draft?.let { drawAnnot(it, ptToPx, false, pictureCache) }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { page--; selectedId = null }, enabled = page > 0) { Icon(Icons.Default.ChevronLeft, "Previous page") }
            Text("Page ${page + 1} of ${r.pageCount}", Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
            if (selectedId != null) IconButton(onClick = { val id = selectedId; commit { annots.removeAll { it.id == id } }; selectedId = null }) { Icon(Icons.Default.Delete, "Delete selected item") }
            IconButton(onClick = { page++; selectedId = null }, enabled = page < r.pageCount - 1) { Icon(Icons.Default.ChevronRight, "Next page") }
        }
        Text("${annots.size} change(s) on ${annots.map { it.page }.distinct().size} page(s)", style = MaterialTheme.typography.bodySmall)
        SectionCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Edit, null)
                Text("Editing existing text", Modifier.weight(1f).padding(start = 8.dp), style = MaterialTheme.typography.titleSmall)
                androidx.compose.material3.TextButton(onClick = { showEditInfo = !showEditInfo }) { Text(if (showEditInfo) "Hide" else "Learn more") }
            }
            if (showEditInfo) Text(EDIT_EXISTING, style = MaterialTheme.typography.bodySmall)
        }
        OutlinedTextField(outName, { outName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Save as new file") }, suffix = { Text(".pdf") })
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Save as new PDF", enabled = annots.isNotEmpty() && job == null, icon = Icons.Default.Save) {
            val d = holder.doc!!; val pw = holder.password; val list = annots.toList(); val name = outName.ifBlank { "Edited" } + ".pdf"
            Operations.run("Edit PDF", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                val out = app.files.newOutputFile(name)
                var protectionNote: String? = null
                val stats = PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    protectionNote = com.docdesk.app.pdf.PdfOps.keepProtectionForSave(doc, pw)
                    AnnotationWriter.write(doc, list, out, p)
                }
                val notes = mutableListOf("Saved as a new file; the original was not changed.",
                    "Drawings, shapes, highlights, text boxes, images and signatures are now part of the page. Sticky notes are PDF comments that other PDF apps can show and edit.")
                protectionNote?.let { notes.add(it) }
                if (stats.textAsImage > 0) notes.add("${stats.textAsImage} text box(es) contain characters outside the basic Latin set (e.g. Hindi) and were added as images, so they are not searchable.")
                OperationResult(OperationReport("Edit PDF", listOf(d.name), Outcome.SUCCESS, pagesSelected = list.map { it.page }.distinct().size, pagesProcessed = list.map { it.page }.distinct().size, notes = notes),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
    pendingText?.let { (at, t) ->
        TextInputDialog(if (t == Tool.NOTE) "Sticky note" else "Add text", "", if (t == Tool.NOTE) "Comment" else "Text", confirm = "Add", multiline = true, onConfirm = { text ->
            commit { annots.add(if (t == Tool.NOTE) Annot.Note(nextId++, page, at, text, color) else Annot.TextBox(nextId++, page, at, text, textSize, color)) }
            pendingText = null
        }, onDismiss = { pendingText = null })
    }
    signatureAt?.let { at ->
        SignatureDialog(onPicked = { f ->
            signatureAt = null
            val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }; BitmapFactory.decodeFile(f.path, o)
            addPicture(f, o.outWidth, o.outHeight, at, true, page, nextId++, currentPageSize) { a -> commit { annots.add(a) } }
        }, onImport = {
            signatureAt = null; pendingPicture = at to true
            imagePicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
        }, onDismiss = { signatureAt = null })
    }
}

private fun addPicture(f: File, w: Int, h: Int, at: NPoint, signature: Boolean, page: Int, id: Long, pageSize: Pair<Int, Int>?, add: (Annot) -> Unit) {
    // Width as a fraction of the page; height keeps the image's aspect ratio relative to the page's.
    val ps = pageSize ?: (595 to 842)
    val nw = if (signature) 0.3f else 0.4f
    val nh = nw * (h.toFloat() / w.coerceAtLeast(1)) * (ps.first.toFloat() / ps.second)
    val left = at.x.coerceAtMost(1f - nw).coerceAtLeast(0f); val top = at.y.coerceAtMost(1f - nh).coerceAtLeast(0f)
    add(Annot.Picture(id, page, NRect(left, top, left + nw, top + nh), f.path, signature))
}

private fun boxKind(t: Tool) = when (t) {
    Tool.HIGHLIGHT -> Annot.BoxKind.HIGHLIGHT; Tool.UNDERLINE -> Annot.BoxKind.UNDERLINE; Tool.STRIKE -> Annot.BoxKind.STRIKE
    Tool.ELLIPSE -> Annot.BoxKind.ELLIPSE; Tool.WHITEOUT -> Annot.BoxKind.WHITEOUT; else -> Annot.BoxKind.RECT
}

private fun resize(a: Annot, p: NPoint): Annot = when (a) {
    is Annot.Picture -> {
        // Keep aspect ratio while resizing from the bottom-right corner.
        val ratio = a.rect.height / a.rect.width
        val nw = (p.x - a.rect.left).coerceAtLeast(0.03f)
        a.copy(rect = NRect(a.rect.left, a.rect.top, a.rect.left + nw, a.rect.top + nw * ratio))
    }
    is Annot.Box -> a.copy(rect = NRect(a.rect.left, a.rect.top, p.x.coerceAtLeast(a.rect.left + 0.01f), p.y.coerceAtLeast(a.rect.top + 0.005f)))
    else -> a
}

private fun DrawScope.drawAnnot(a: Annot, ptToPx: Float, selected: Boolean, cache: HashMap<String, androidx.compose.ui.graphics.ImageBitmap?>) {
    val w = size.width; val h = size.height
    fun o(p: NPoint) = Offset(p.x * w, p.y * h)
    val col = Color(a.color)
    when (a) {
        is Annot.Box -> {
            val tl = Offset(a.rect.left * w, a.rect.top * h); val sz = Size(a.rect.width * w, a.rect.height * h)
            val sw = a.strokePt * ptToPx
            when (a.kind) {
                Annot.BoxKind.HIGHLIGHT -> drawRect(col.copy(alpha = 0.35f), tl, sz)
                Annot.BoxKind.WHITEOUT -> { drawRect(Color.White, tl, sz); drawRect(Color.Gray, tl, sz, style = Stroke(1f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 6f)))) }
                Annot.BoxKind.UNDERLINE -> drawLine(col, Offset(tl.x, tl.y + sz.height), Offset(tl.x + sz.width, tl.y + sz.height), sw)
                Annot.BoxKind.STRIKE -> drawLine(col, Offset(tl.x, tl.y + sz.height / 2), Offset(tl.x + sz.width, tl.y + sz.height / 2), sw)
                Annot.BoxKind.RECT -> drawRect(col, tl, sz, style = Stroke(sw))
                Annot.BoxKind.ELLIPSE -> drawOval(col, tl, sz, style = Stroke(sw))
            }
        }
        is Annot.Line -> {
            val s = o(a.a); val e = o(a.b); val sw = a.strokePt * ptToPx
            drawLine(col, s, e, sw, cap = StrokeCap.Round)
            if (a.arrow) {
                val ang = Math.atan2((e.y - s.y).toDouble(), (e.x - s.x).toDouble())
                val len = (6f + a.strokePt * 3f) * ptToPx
                val path = Path().apply {
                    moveTo(e.x, e.y)
                    lineTo(e.x - len * Math.cos(ang - 0.45).toFloat(), e.y - len * Math.sin(ang - 0.45).toFloat())
                    lineTo(e.x - len * Math.cos(ang + 0.45).toFloat(), e.y - len * Math.sin(ang + 0.45).toFloat())
                    close()
                }
                drawPath(path, col)
            }
        }
        is Annot.Ink -> if (a.points.size > 1) {
            val path = Path().apply { moveTo(a.points[0].x * w, a.points[0].y * h); a.points.drop(1).forEach { lineTo(it.x * w, it.y * h) } }
            drawPath(path, col, style = Stroke(a.strokePt * ptToPx, cap = StrokeCap.Round))
        }
        is Annot.TextBox -> {
            val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply { color = a.color; textSize = a.sizePt * ptToPx }
            a.text.lines().forEachIndexed { i, line -> drawContext.canvas.nativeCanvas.drawText(line, a.origin.x * w, a.origin.y * h + paint.textSize * (i + 1) * 1.0f + paint.textSize * 0.2f * i, paint) }
        }
        is Annot.Note -> {
            val tl = o(a.at); val s = 20f * ptToPx
            drawRect(Color(0xFFFFE082), tl, Size(s, s)); drawRect(Color(0xFF8D6E00), tl, Size(s, s), style = Stroke(2f))
            drawLine(Color(0xFF8D6E00), Offset(tl.x + s * 0.2f, tl.y + s * 0.4f), Offset(tl.x + s * 0.8f, tl.y + s * 0.4f), 2f)
            drawLine(Color(0xFF8D6E00), Offset(tl.x + s * 0.2f, tl.y + s * 0.65f), Offset(tl.x + s * 0.7f, tl.y + s * 0.65f), 2f)
        }
        is Annot.Picture -> {
            val img = cache.getOrPut(a.path) { BitmapFactory.decodeFile(a.path)?.asImageBitmap() }
            val tl = Offset(a.rect.left * w, a.rect.top * h)
            if (img != null) drawImage(img, dstOffset = IntOffset(tl.x.toInt(), tl.y.toInt()), dstSize = IntSize((a.rect.width * w).toInt().coerceAtLeast(1), (a.rect.height * h).toInt().coerceAtLeast(1)))
        }
    }
    if (selected) {
        val b = a.bounds()
        val tl = Offset(b.left * w - 6, b.top * h - 6); val sz = Size(b.width * w + 12, b.height * h + 12)
        drawRect(Color(0xFF1E4FA3), tl, sz, style = Stroke(3f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 8f))))
        if (a is Annot.Picture || a is Annot.Box) drawCircle(Color(0xFF1E4FA3), 14f, Offset(b.right * w, b.bottom * h))
    }
}

private fun hintFor(t: Tool) = when (t) {
    Tool.SELECT -> "Tap an item to select it, drag to move it, drag the round handle to resize. Use the bin to delete."
    Tool.HIGHLIGHT -> "Drag across text to highlight an area."
    Tool.UNDERLINE, Tool.STRIKE -> "Drag along the text."
    Tool.PEN -> "Draw with your finger."
    Tool.RECT, Tool.ELLIPSE -> "Drag to draw the shape."
    Tool.LINE, Tool.ARROW -> "Drag from start to end."
    Tool.TEXT -> "Tap where the text should start."
    Tool.NOTE -> "Tap to place a comment (sticky note)."
    Tool.IMAGE -> "Tap where the image should go, then choose a picture."
    Tool.SIGNATURE -> "Tap where your signature should go."
    Tool.WHITEOUT -> "Drag over content to cover it with white, then add a text box on top to replace it."
}

private fun colorName(c: Int) = when (c) {
    palette[0] -> "yellow"; palette[1] -> "green"; palette[2] -> "light blue"; palette[3] -> "pink"; palette[4] -> "red"; palette[5] -> "dark blue"; else -> "black"
}

private const val EDIT_EXISTING = "DocDesk adds content on top of the page (annotations). It cannot reliably change the PDF's existing text or images in place: PDF text is stored as positioned glyphs with embedded font subsets, so rewriting it on a phone usually breaks the layout or the font. To correct text, use \"Cover (white-out)\" over the old text and add a Text box with the new wording. Note that covered text may still exist underneath and can be found by copying or searching – it is not a secure redaction. True in-place editing requires a commercial PDF SDK (for example Apryse/PDFTron, PSPDFKit/Nutrient or Foxit) and is planned for a later phase."

