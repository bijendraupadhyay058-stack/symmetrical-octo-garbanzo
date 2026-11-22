package com.cashbook.app.export

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File
import java.io.OutputStream

/** Writes export files and hands them to Android's share sheet — only when the user asks. */
object Exporter {
    const val MIME_PDF = "application/pdf"
    const val MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    fun authority(context: Context) = context.packageName + ".files"

    /** Writes to a cache file and returns a shareable content:// Uri. */
    fun writeShareable(context: Context, fileName: String, write: (OutputStream) -> Unit): Uri {
        val dir = File(context.cacheDir, "exports").apply { mkdirs() }
        dir.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 86_400_000L }?.forEach { it.delete() }
        val f = File(dir, fileName)
        f.outputStream().use(write)
        return FileProvider.getUriForFile(context, authority(context), f)
    }

    fun writeTo(context: Context, uri: Uri, write: (OutputStream) -> Unit) {
        (context.contentResolver.openOutputStream(uri, "wt") ?: error("cannot open")).use(write)
    }

    fun share(context: Context, uri: Uri, mime: String, title: String) {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = mime
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, title)
            clipData = ClipData.newRawUri(title, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(send, title))
    }

    fun shareText(context: Context, text: String, title: String) {
        val send = Intent(Intent.ACTION_SEND).apply { type = "text/plain"; putExtra(Intent.EXTRA_TEXT, text) }
        context.startActivity(Intent.createChooser(send, title))
    }

    /** Opens a private file in an installed viewer. Returns false when no app can open it. */
    fun view(context: Context, file: File, mime: String): Boolean {
        val uri = FileProvider.getUriForFile(context, authority(context), file)
        return try {
            context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
            true
        } catch (e: ActivityNotFoundException) { false }
    }

    fun safeFileName(s: String) = s.replace(Regex("[^\\p{L}\\p{N}._-]+"), "_").trim('_').take(80).ifEmpty { "Cashbook" }
}
