package com.cashbook.app.ui.components

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.cashbook.app.R
import com.cashbook.app.export.Exporter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

data class AttachmentUi(val key: String, val file: File, val fileName: String, val mimeType: String, val sizeBytes: Long)

fun formatSize(bytes: Long): String = when {
    bytes >= 1024 * 1024 -> String.format(java.util.Locale.US, "%.1f MB", bytes / 1048576.0)
    bytes >= 1024 -> "${bytes / 1024} KB"
    else -> "$bytes B"
}

/** Decodes a downscaled preview of an image or the first page of a PDF, off the main thread. */
@Composable
fun rememberPreview(file: File, mime: String, maxPx: Int): Bitmap? {
    val bmp by produceState<Bitmap?>(null, file.path, maxPx) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                if (mime == "application/pdf") {
                    ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).use { pfd ->
                        PdfRenderer(pfd).use { r ->
                            r.openPage(0).use { p ->
                                val scale = maxPx.toFloat() / maxOf(p.width, p.height)
                                val b = Bitmap.createBitmap((p.width * scale).toInt().coerceAtLeast(1), (p.height * scale).toInt().coerceAtLeast(1), Bitmap.Config.ARGB_8888)
                                b.eraseColor(android.graphics.Color.WHITE)
                                p.render(b, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                                b
                            }
                        }
                    }
                } else {
                    val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeFile(file.path, o)
                    var sample = 1
                    while (o.outWidth / sample > maxPx * 2 || o.outHeight / sample > maxPx * 2) sample *= 2
                    BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
                }
            }.getOrNull()
        }
    }
    return bmp
}

@Composable
fun AttachmentItem(a: AttachmentUi, onRemove: (() -> Unit)?, onReplace: (() -> Unit)?, onOpenFailed: () -> Unit, beforeExternal: () -> Unit = {}) {
    val ctx = LocalContext.current
    var preview by remember { mutableStateOf(false) }
    val thumb = rememberPreview(a.file, a.mimeType, 160)
    val isPdf = a.mimeType == "application/pdf"
    Row(Modifier.fillMaxWidth().clickable { preview = true }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(52.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
            if (thumb != null) Image(thumb.asImageBitmap(), null, contentScale = ContentScale.Crop, modifier = Modifier.size(52.dp))
            else Icon(if (isPdf) Icons.Filled.PictureAsPdf else Icons.Filled.Image, null)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(a.fileName, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
            Text((if (isPdf) "PDF" else "Image") + " · " + formatSize(a.sizeBytes), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (onReplace != null) IconButton(onClick = onReplace) { Icon(Icons.Filled.SwapHoriz, stringResource(R.string.replace)) }
        if (onRemove != null) IconButton(onClick = onRemove) { Icon(Icons.Filled.Close, stringResource(R.string.remove)) }
    }
    if (preview) {
        val big = rememberPreview(a.file, a.mimeType, 1400)
        AlertDialog(
            onDismissRequest = { preview = false },
            title = { Text(a.fileName, maxLines = 2, overflow = TextOverflow.Ellipsis) },
            text = {
                Column {
                    if (big != null) Image(big.asImageBitmap(), a.fileName, Modifier.fillMaxWidth().heightIn(max = 460.dp).background(Color.White), contentScale = ContentScale.Fit)
                    Text(formatSize(a.sizeBytes), style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    beforeExternal()
                    if (!Exporter.view(ctx, a.file, a.mimeType)) onOpenFailed()
                }) { Text(stringResource(if (isPdf) R.string.open_pdf else R.string.open_in_app)) }
            },
            dismissButton = { TextButton(onClick = { preview = false }) { Text(stringResource(R.string.close)) } },
        )
    }
}
