package com.docdesk.app.ui.components

import android.net.Uri
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.DocType
import com.docdesk.app.data.InputDoc
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.PasswordRequiredException
import com.docdesk.app.pdf.PdfDocs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class PdfItem(val id: Long, val doc: InputDoc) {
    var password by mutableStateOf<String?>(null)
    var pages by mutableStateOf<Int?>(null)
    var needsPassword by mutableStateOf<Boolean?>(null)
    var error by mutableStateOf<String?>(null)
    val ready get() = pages != null && error == null && needsPassword == null
}

/** A list of PDFs chosen for a multi-file tool, each checked (page count, password) in the background. */
class MultiPdfState(private val scope: CoroutineScope) {
    val items = mutableStateListOf<PdfItem>()
    private var next = 1L
    var skipped by mutableStateOf<String?>(null)

    fun add(uris: List<Uri>) {
        val app = DocDeskApp.instance
        val bad = mutableListOf<String>()
        for (u in uris) {
            val d = app.files.describe(u)
            if (d.type != DocType.PDF && !d.name.endsWith(".pdf", true)) { bad.add(d.name); continue }
            val it = PdfItem(next++, d); items.add(it); check(it)
        }
        skipped = if (bad.isEmpty()) null else "Not PDFs, skipped: " + bad.joinToString()
    }

    fun check(item: PdfItem) = scope.launch {
        try {
            item.pages = withContext(Dispatchers.IO) { PdfDocs.open(DocDeskApp.instance, item.doc.uri, item.password).use { it.numberOfPages } }
            item.needsPassword = null; item.error = null
        } catch (e: PasswordRequiredException) { item.needsPassword = e.wrongPassword } catch (e: Throwable) { item.error = e.userMessage() }
    }

    val allReady get() = items.isNotEmpty() && items.all { it.ready }
}

@Composable
fun MultiPdfList(state: MultiPdfState) {
    state.items.forEachIndexed { i, item ->
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.PictureAsPdf, null)
            Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                Text("${i + 1}. ${item.doc.name}", style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(when { item.error != null -> item.error!!; item.needsPassword != null -> "Password required"; item.pages == null -> "Checking…"; else -> "${item.pages} pages" },
                    style = MaterialTheme.typography.bodySmall, color = if (item.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = { state.items.add(i - 1, state.items.removeAt(i)) }, enabled = i > 0) { Icon(Icons.Default.KeyboardArrowUp, "Move ${item.doc.name} up") }
            IconButton(onClick = { state.items.add(i + 1, state.items.removeAt(i)) }, enabled = i < state.items.lastIndex) { Icon(Icons.Default.KeyboardArrowDown, "Move ${item.doc.name} down") }
            IconButton(onClick = { state.items.removeAt(i) }) { Icon(Icons.Default.Delete, "Remove ${item.doc.name}") }
        }
    }
    state.items.firstOrNull { it.needsPassword != null }?.let { item ->
        PasswordDialog(item.doc.name, wrong = item.needsPassword == true, onSubmit = { pw -> item.password = pw; item.needsPassword = null; state.check(item) }, onDismiss = { state.items.remove(item) })
    }
}
