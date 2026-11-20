package com.docdesk.app.ui.convert

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.core.NormRect
import com.docdesk.core.PageRanges

/** Validates "all pages" or a typed range against the page count. */
fun selectedPages(pageCount: Int, allPages: Boolean, range: String): Result<List<Int>> =
    if (allPages) Result.success((0 until pageCount).toList())
    else runCatching { PageRanges.parse(range.ifBlank { throw PageRanges.ParseException("Enter pages, for example 1-3, 5.") }, pageCount) }

/** "All pages" or a typed range. */
@Composable
fun PageSelection(pageCount: Int, allPages: Boolean, onAll: (Boolean) -> Unit, range: String, onRange: (String) -> Unit) {
    RadioOptions(listOf(true, false), allPages, { if (it) "All $pageCount pages" else "Specific pages or ranges" }) { onAll(it) }
    val r = selectedPages(pageCount, allPages, range)
    if (!allPages) OutlinedTextField(range, onRange, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Pages (e.g. 1-3, 5, 8-10)") },
        isError = r.isFailure, supportingText = { Text(r.exceptionOrNull()?.message ?: "${r.getOrNull()?.size} page(s) selected") })
}

/** Lets the user drag a rectangle on a page preview to limit table detection to that area. */
@Composable
fun AreaSelector(renderer: PageRenderer, page: Int, area: NormRect?, onArea: (NormRect?) -> Unit) {
    var start by remember { mutableStateOf<Offset?>(null) }
    var current by remember { mutableStateOf<Offset?>(null) }
    Column {
        Text("Drag across the table on this page. The same area is used on every selected page.", style = MaterialTheme.typography.bodySmall)
        Box(Modifier.fillMaxWidth()) {
            PageImage(renderer, page, 1000, description = "Page ${page + 1} preview for choosing the table area")
            Canvas(Modifier.matchParentSize().semantics { contentDescription = if (area == null) "No area selected" else "Table area selected" }.pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { start = it; current = it },
                    onDrag = { change, _ -> current = change.position },
                    onDragEnd = {
                        val s = start; val c = current
                        if (s != null && c != null) {
                            val r = NormRect.of(s.x / size.width, s.y / size.height, c.x / size.width, c.y / size.height)
                            onArea(if (r.right - r.left > 0.02f && r.bottom - r.top > 0.02f) r else null)
                        }
                        start = null; current = null
                    },
                )
            }) {
                val s = start; val c = current
                val rect = if (s != null && c != null) NormRect.of(s.x / size.width, s.y / size.height, c.x / size.width, c.y / size.height) else area
                if (rect != null) {
                    val tl = Offset(rect.left * size.width, rect.top * size.height)
                    val sz = Size((rect.right - rect.left) * size.width, (rect.bottom - rect.top) * size.height)
                    drawRect(Color(0x332196F3), tl, sz)
                    drawRect(Color(0xFF1E4FA3), tl, sz, style = Stroke(width = 4f))
                }
            }
        }
    }
}
