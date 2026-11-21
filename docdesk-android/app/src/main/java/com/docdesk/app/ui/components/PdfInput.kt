package com.docdesk.app.ui.components

import android.graphics.Bitmap
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.InputDoc
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PasswordRequiredException
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfInfo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * State for "the PDF this tool works on": selection, password prompt, inspection and a
 * renderer for thumbnails. The password lives only in this object (memory) and is cleared
 * when the screen is closed.
 */
class PdfInputHolder(private val scope: CoroutineScope, private val wantRenderer: Boolean = true) {
    private val app get() = DocDeskApp.instance
    var doc by mutableStateOf<InputDoc?>(null); private set
    var info by mutableStateOf<PdfInfo?>(null); private set
    var renderer by mutableStateOf<PageRenderer?>(null); private set
    var passwordPrompt by mutableStateOf<Boolean?>(null); private set // null: none, false: needed, true: wrong
    var error by mutableStateOf<String?>(null)
    var loading by mutableStateOf(false); private set
    var password: String? = null; private set
    private var onReady: (() -> Unit)? = null

    val ready get() = info != null && doc != null

    fun select(uri: Uri, then: (() -> Unit)? = null) {
        close()
        error = null
        onReady = then
        val d = app.files.describe(uri)
        if (d.type != com.docdesk.app.data.DocType.PDF && !d.name.endsWith(".pdf", true)) {
            error = "\"${d.name}\" is not a PDF file."; return
        }
        doc = d
        load()
    }

    fun submitPassword(pw: String) { password = pw; passwordPrompt = null; load() }

    fun dismissPassword() { passwordPrompt = null; doc = null; password = null }

    private fun load() {
        val d = doc ?: return
        loading = true
        scope.launch {
            try {
                val i = withContext(Dispatchers.IO) { PdfDocs.open(app, d.uri, password).use { PdfDocs.inspect(it) } }
                val r = if (wantRenderer) withContext(Dispatchers.IO) {
                    if (i.encrypted) PageRenderer.openDecryptedCopy(app, d.uri, password ?: "", app.files.workDir) else PageRenderer.open(app, d.uri, app.files.workDir)
                } else null
                info = i; renderer = r
                onReady?.invoke(); onReady = null
            } catch (e: PasswordRequiredException) {
                passwordPrompt = e.wrongPassword
            } catch (e: Throwable) {
                error = e.userMessage(); doc = null
            } finally { loading = false }
        }
    }

    /** Gives up ownership of the renderer (the caller will close it). */
    fun detachRenderer() { renderer = null }

    fun close() {
        val r = renderer
        renderer = null; info = null; password = null
        if (r != null) scope.launch(Dispatchers.IO) { r.close() }
    }
}

@Composable
fun PasswordPromptFor(holder: PdfInputHolder) {
    val p = holder.passwordPrompt ?: return
    PasswordDialog(holder.doc?.name ?: "PDF", wrong = p, onSubmit = holder::submitPassword, onDismiss = holder::dismissPassword)
}

/** Renders one PDF page bitmap asynchronously. */
@Composable
fun PageImage(renderer: PageRenderer, index: Int, widthPx: Int, modifier: Modifier = Modifier, rotation: Int = 0, description: String? = null) {
    val bmp by produceState<Bitmap?>(null, renderer, index, widthPx) { value = runCatching { renderer.render(index, widthPx) }.getOrNull() }
    val size by produceState<Pair<Int, Int>?>(null, renderer, index) { value = runCatching { renderer.pageSize(index) }.getOrNull() }
    val ratio = size?.let { (w, h) -> if (rotation % 180 == 0) w.toFloat() / h else h.toFloat() / w } ?: 0.707f
    Box(modifier.fillMaxWidth().aspectRatio(ratio.coerceIn(0.2f, 5f)).background(Color.White), contentAlignment = Alignment.Center) {
        val b = bmp
        if (b == null) CircularProgressIndicator(Modifier.size(24.dp), color = MaterialTheme.colorScheme.primary)
        else Image(
            b.asImageBitmap(), contentDescription = description ?: "Page ${index + 1}",
            modifier = Modifier.fillMaxWidth().aspectRatio(b.width.toFloat() / b.height).rotate(rotation.toFloat()),
            contentScale = ContentScale.Fit,
        )
    }
}
