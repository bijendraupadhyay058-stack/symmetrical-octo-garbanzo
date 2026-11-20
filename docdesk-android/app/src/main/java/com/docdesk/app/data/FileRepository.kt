package com.docdesk.app.data

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import androidx.core.content.FileProvider
import java.io.File
import java.io.IOException

enum class DocType(val label: String, val mime: String, val extensions: Set<String>) {
    PDF("PDF", "application/pdf", setOf("pdf")),
    WORD("Word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", setOf("docx")),
    EXCEL("Excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", setOf("xlsx")),
    TEXT("Text", "text/plain", setOf("txt")),
    ZIP("ZIP archive", "application/zip", setOf("zip")),
    CERT("Certificate", "application/x-pkcs12", setOf("p12", "pfx")),
    IMAGE("Image", "image/*", setOf("jpg", "jpeg", "png")),
    LEGACY_WORD("Word 97-2003", "application/msword", setOf("doc")),
    LEGACY_EXCEL("Excel 97-2003", "application/vnd.ms-excel", setOf("xls")),
    OTHER("File", "application/octet-stream", emptySet());

    companion object {
        fun of(name: String, mime: String? = null): DocType {
            val ext = name.substringAfterLast('.', "").lowercase()
            entries.firstOrNull { ext in it.extensions }?.let { return it }
            return when {
                mime == null -> OTHER
                mime == PDF.mime -> PDF
                mime == WORD.mime -> WORD
                mime == EXCEL.mime -> EXCEL
                mime == LEGACY_WORD.mime -> LEGACY_WORD
                mime == LEGACY_EXCEL.mime -> LEGACY_EXCEL
                mime.startsWith("image/") -> IMAGE
                mime.startsWith("text/") -> TEXT
                else -> OTHER
            }
        }
    }
}

data class StoredFile(val file: File, val name: String, val size: Long, val modified: Long, val type: DocType)

/** A document chosen by the user (through the system picker) or stored in My Files. */
data class InputDoc(val uri: Uri, val name: String, val size: Long, val type: DocType)

/**
 * All file handling. Documents created by the app live in app-private storage ("My Files");
 * work in progress lives in the cache and is deleted after use. No broad storage permission
 * is used: external files are read and written only through the Storage Access Framework.
 */
class FileRepository(private val context: Context) {
    val myFilesDir: File = File(context.filesDir, "MyFiles").apply { mkdirs() }
    private val outputDir: File get() = File(context.cacheDir, "output").apply { mkdirs() }
    val workDir: File get() = File(context.cacheDir, "work").apply { mkdirs() }
    val signaturesDir: File get() = File(context.filesDir, "signatures").apply { mkdirs() }

    fun describe(uri: Uri): InputDoc {
        if (uri.scheme == "file") {
            val f = File(uri.path!!)
            return InputDoc(uri, f.name, f.length(), DocType.of(f.name))
        }
        var name = "document"
        var size = -1L
        runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 }?.let { c.getString(it)?.let { n -> name = n } }
                    c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !c.isNull(it) }?.let { size = c.getLong(it) }
                }
            }
        }
        val mime = runCatching { context.contentResolver.getType(uri) }.getOrNull()
        return InputDoc(uri, name, size, DocType.of(name, mime))
    }

    fun inputOf(file: File) = InputDoc(Uri.fromFile(file), file.name, file.length(), DocType.of(file.name))

    fun listMyFiles(): List<StoredFile> = (myFilesDir.listFiles() ?: emptyArray()).filter { it.isFile }.map {
        StoredFile(it, it.name, it.length(), it.lastModified(), DocType.of(it.name))
    }

    /** A new empty file in the output cache; results are previewed from here before saving. */
    fun newOutputFile(name: String): File {
        val dir = File(outputDir, System.nanoTime().toString()).apply { mkdirs() }
        return File(dir, sanitize(name))
    }

    fun newWorkFile(suffix: String): File = File.createTempFile("w", suffix, workDir)

    /** Copies an output into My Files with a unique name and returns the stored file. */
    fun saveToMyFiles(source: File, desiredName: String = source.name): File {
        val target = unique(myFilesDir, sanitize(desiredName))
        source.copyTo(target, overwrite = false)
        return target
    }

    fun importToMyFiles(uri: Uri): File {
        val doc = describe(uri)
        val target = unique(myFilesDir, sanitize(doc.name))
        val tmp = File(target.parentFile, target.name + ".part")
        try {
            context.contentResolver.openInputStream(uri)?.use { input -> tmp.outputStream().use { input.copyTo(it) } }
                ?: throw IOException("The file could not be opened.")
            if (!tmp.renameTo(target)) throw IOException("The file could not be saved.")
        } finally { tmp.delete() }
        return target
    }

    /** Writes [source] to a location the user picked with ACTION_CREATE_DOCUMENT. */
    fun exportTo(source: File, target: Uri) {
        context.contentResolver.openOutputStream(target, "wt")?.use { out -> source.inputStream().use { it.copyTo(out) } }
            ?: throw IOException("Could not write to the selected location.")
    }

    fun rename(file: File, newName: String): File {
        val clean = sanitize(newName).let { if (!it.contains('.') && file.extension.isNotEmpty()) "$it.${file.extension}" else it }
        val target = File(file.parentFile, clean)
        if (target.exists()) throw IOException("A file named \"$clean\" already exists.")
        if (!file.renameTo(target)) throw IOException("The file could not be renamed.")
        return target
    }

    fun delete(file: File): Boolean = file.delete()

    fun uriFor(file: File): Uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)

    fun mimeOf(file: File): String = DocType.of(file.name).let {
        if (it == DocType.IMAGE) MimeTypeMap.getSingleton().getMimeTypeFromExtension(file.extension.lowercase()) ?: "image/*" else it.mime
    }

    fun shareIntent(files: List<File>): Intent {
        val uris = files.map { uriFor(it) }
        val intent = if (uris.size == 1) Intent(Intent.ACTION_SEND).apply {
            type = mimeOf(files[0]); putExtra(Intent.EXTRA_STREAM, uris[0])
        } else Intent(Intent.ACTION_SEND_MULTIPLE).apply {
            type = if (files.map { mimeOf(it) }.distinct().size == 1) mimeOf(files[0]) else "*/*"
            putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
        }
        intent.clipData = ClipData.newRawUri(files[0].name, uris[0]).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return Intent.createChooser(intent, "Share")
    }

    fun openWithIntent(file: File): Intent {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uriFor(file), mimeOf(file))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return Intent.createChooser(intent, "Open with")
    }

    fun temporaryBytes(): Long = listOf(File(context.cacheDir, "output"), File(context.cacheDir, "work")).sumOf { d -> d.walkBottomUp().filter { it.isFile }.sumOf { it.length() } } +
        (context.cacheDir.listFiles()?.filter { it.isFile }?.sumOf { it.length() } ?: 0L)

    /** Deletes cached outputs, decrypted temporary copies and PdfBox scratch files. */
    fun cleanTemporary(olderThanMillis: Long = 0) {
        val cutoff = System.currentTimeMillis() - olderThanMillis
        for (dir in listOf(File(context.cacheDir, "output"), File(context.cacheDir, "work"))) {
            dir.walkBottomUp().forEach { if (it != dir && it.lastModified() <= cutoff) it.delete() }
        }
        context.cacheDir.listFiles()?.filter { it.isFile && it.lastModified() <= cutoff }?.forEach { it.delete() }
    }

    companion object {
        fun sanitize(name: String): String {
            val cleaned = name.replace(Regex("""[\\/:*?"<>|\u0000-\u001F]"""), "_").trim().trim('.')
            return cleaned.ifEmpty { "document" }.take(120)
        }

        fun unique(dir: File, name: String): File {
            var f = File(dir, name)
            if (!f.exists()) return f
            val base = name.substringBeforeLast('.', name)
            val ext = name.substringAfterLast('.', "").let { if (it.isEmpty() || it == name) "" else ".$it" }
            var i = 2
            while (f.exists()) { f = File(dir, "$base ($i)$ext"); i++ }
            return f
        }

        fun baseName(name: String) = name.substringBeforeLast('.', name)
    }
}
