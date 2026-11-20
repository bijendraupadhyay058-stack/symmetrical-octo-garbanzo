package com.docdesk.app.ui.edit

import android.graphics.Bitmap
import android.graphics.Paint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.layout.onSizeChanged
import com.docdesk.app.DocDeskApp
import java.io.File

/**
 * Lets the user pick a saved signature, draw a new one, or import an image. Saved signatures
 * are stored privately in the app (never uploaded) and can be deleted here.
 */
@Composable
fun SignatureDialog(onPicked: (File) -> Unit, onImport: () -> Unit, onDismiss: () -> Unit) {
    val dir = DocDeskApp.instance.files.signaturesDir
    var saved by remember { mutableStateOf(dir.listFiles()?.filter { it.extension == "png" }?.sortedByDescending { it.lastModified() } ?: emptyList()) }
    var drawing by remember { mutableStateOf(saved.isEmpty()) }
    val strokes = remember { mutableStateListOf<List<Offset>>() }
    var current by remember { mutableStateOf<List<Offset>>(emptyList()) }
    var padSize by remember { mutableStateOf(IntSize.Zero) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (drawing) "Draw your signature" else "Choose a signature") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!drawing) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(saved, key = { it.path }) { f ->
                            val bmp = remember(f) { android.graphics.BitmapFactory.decodeFile(f.path) }
                            Column {
                                if (bmp != null) Image(bmp.asImageBitmap(), "Saved signature", Modifier.width(140.dp).height(70.dp).background(Color.White).border(1.dp, MaterialTheme.colorScheme.outline).clickable { onPicked(f) })
                                TextButton(onClick = { f.delete(); saved = saved - f }) { Text("Delete") }
                            }
                        }
                    }
                    TextButton(onClick = { drawing = true }) { Text("Draw a new signature") }
                } else {
                    Canvas(
                        Modifier.fillMaxWidth().height(180.dp).background(Color.White).border(1.dp, MaterialTheme.colorScheme.outline)
                            .onSizeChanged { padSize = it }
                            .semantics { contentDescription = "Signature drawing area" }
                            .pointerInput(Unit) {
                                detectDragGestures(
                                    onDragStart = { current = listOf(it) },
                                    onDrag = { c, _ -> current = current + c.position },
                                    onDragEnd = { if (current.size > 1) strokes.add(current); current = emptyList() },
                                )
                            },
                    ) {
                        (strokes + listOf(current)).forEach { pts ->
                            if (pts.size > 1) {
                                val p = Path().apply { moveTo(pts[0].x, pts[0].y); pts.drop(1).forEach { lineTo(it.x, it.y) } }
                                drawPath(p, Color(0xFF0D2A6B), style = Stroke(width = 6f, cap = StrokeCap.Round, join = StrokeJoin.Round))
                            }
                        }
                        drawLine(Color.LightGray, Offset(20f, size.height * 0.78f), Offset(size.width - 20f, size.height * 0.78f), 2f)
                    }
                    Row {
                        TextButton(onClick = { strokes.clear() }) { Text("Clear") }
                        if (saved.isNotEmpty()) TextButton(onClick = { drawing = false }) { Text("Use a saved one") }
                    }
                    Text("Your signature is saved only on this phone so you can reuse it.", style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = onImport) { Text("Import a signature image") }
            }
        },
        confirmButton = {
            if (drawing) TextButton(enabled = strokes.isNotEmpty(), onClick = {
                val f = File(dir, "sig_${System.currentTimeMillis()}.png")
                renderSignature(strokes, padSize)?.let { bmp -> f.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }; bmp.recycle(); onPicked(f) }
            }) { Text("Use signature") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Renders strokes to a transparent bitmap cropped to the signature. */
private fun renderSignature(strokes: List<List<Offset>>, size: IntSize): Bitmap? {
    val pts = strokes.flatten()
    if (pts.isEmpty() || size.width == 0) return null
    val pad = 10f
    val minX = pts.minOf { it.x } - pad; val minY = pts.minOf { it.y } - pad
    val w = (pts.maxOf { it.x } + pad - minX).toInt().coerceAtLeast(10); val h = (pts.maxOf { it.y } + pad - minY).toInt().coerceAtLeast(10)
    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    val c = android.graphics.Canvas(bmp)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF0D2A6B.toInt(); style = Paint.Style.STROKE; strokeWidth = 6f; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND }
    for (s in strokes) {
        val p = android.graphics.Path(); p.moveTo(s[0].x - minX, s[0].y - minY); s.drop(1).forEach { p.lineTo(it.x - minX, it.y - minY) }
        c.drawPath(p, paint)
    }
    return bmp
}
