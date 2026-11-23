package com.cashbook.app.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import java.io.File
import java.util.UUID

/**
 * Stores bill/receipt files in the app's private storage (`files/attachments`). Files are copied
 * in through the Storage Access Framework / photo picker, so no storage permission is needed.
 */
class AttachmentStore(private val context: Context) {
    val dir: File get() = File(context.filesDir, "attachments").apply { mkdirs() }

    data class Imported(val storedName: String, val fileName: String, val mimeType: String, val sizeBytes: Long)

    sealed class ImportError(message: String) : Exception(message) {
        class TooLarge : ImportError("too large")
        class Unsupported : ImportError("unsupported")
        class Failed : ImportError("failed")
    }

    fun file(storedName: String) = File(dir, storedName)

    /** Copies [uri] into private storage. Large photos are downscaled to save space. */
    fun import(uri: Uri, fallbackName: String = "attachment"): Imported {
        val cr = context.contentResolver
        var name = fallbackName
        var size = -1L
        cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 }?.let { c.getString(it)?.let { n -> name = n } }
                c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !c.isNull(it) }?.let { size = c.getLong(it) }
            }
        }
        val ext = name.substringAfterLast('.', "").lowercase()
        val mime = (cr.getType(uri) ?: MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "").lowercase()
        val kind = when {
            mime == "application/pdf" || ext == "pdf" -> "pdf"
            mime == "image/png" || ext == "png" -> "png"
            mime == "image/jpeg" || mime == "image/jpg" || ext == "jpg" || ext == "jpeg" -> "jpg"
            else -> throw ImportError.Unsupported()
        }
        if (size > MAX_BYTES && kind == "pdf") throw ImportError.TooLarge()
        val stored = UUID.randomUUID().toString() + "." + kind
        val target = file(stored)
        try {
            cr.openInputStream(uri)?.use { input ->
                target.outputStream().use { out ->
                    val buf = ByteArray(16 * 1024); var total = 0L
                    while (true) {
                        val n = input.read(buf); if (n < 0) break
                        total += n
                        if (total > MAX_SOURCE_BYTES) throw ImportError.TooLarge()
                        out.write(buf, 0, n)
                    }
                }
            } ?: throw ImportError.Failed()
            if (kind != "pdf") shrinkImage(target)
            if (target.length() > MAX_BYTES) throw ImportError.TooLarge()
        } catch (e: ImportError) {
            target.delete(); throw e
        } catch (e: Exception) {
            target.delete(); throw ImportError.Failed()
        }
        val mimeOut = when (kind) { "pdf" -> "application/pdf"; "png" -> "image/png"; else -> "image/jpeg" }
        return Imported(stored, name, mimeOut, target.length())
    }

    /** Downscales photos larger than ~2 MB / 2400 px to keep the database and backups small. */
    private fun shrinkImage(f: File) {
        if (f.length() < 2L * 1024 * 1024) return
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(f.path, bounds)
        var sample = 1
        while (bounds.outWidth / sample > 2400 || bounds.outHeight / sample > 2400) sample *= 2
        val bmp = BitmapFactory.decodeFile(f.path, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return
        val tmp = File(f.parentFile, f.name + ".tmp")
        tmp.outputStream().use { bmp.compress(if (f.name.endsWith(".png")) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, 85, it) }
        bmp.recycle()
        if (tmp.length() in 1 until f.length()) tmp.renameTo(f) else tmp.delete()
    }

    fun delete(storedName: String) { file(storedName).delete() }

    // ---- branding images for invoices (kept here so backups carry them) ----
    enum class Brand(val fileName: String) { LOGO("branding-logo.png"), SIGNATURE("branding-signature.png") }

    fun brandFile(b: Brand) = file(b.fileName)
    fun brandBitmap(b: Brand): Bitmap? = brandFile(b).takeIf { it.exists() }?.let { BitmapFactory.decodeFile(it.path) }

    /** Imports a JPG/PNG as the logo or signature, scaled to at most 800 px and saved as PNG (keeps transparency). */
    fun importBrand(b: Brand, uri: Uri) {
        val cr = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        // (decodeStream returns null in bounds-only mode by design, so check that the stream opened instead)
        val input = cr.openInputStream(uri) ?: throw ImportError.Failed()
        input.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0) throw ImportError.Unsupported()
        var sample = 1
        while (bounds.outWidth / sample > 1600 || bounds.outHeight / sample > 1600) sample *= 2
        val src = cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample }) }
            ?: throw ImportError.Unsupported()
        val scale = minOf(1f, 800f / maxOf(src.width, src.height))
        val bmp = if (scale < 1f) Bitmap.createScaledBitmap(src, (src.width * scale).toInt().coerceAtLeast(1), (src.height * scale).toInt().coerceAtLeast(1), true) else src
        val tmp = File(dir, b.fileName + ".tmp")
        tmp.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        if (!tmp.renameTo(brandFile(b))) { brandFile(b).delete(); tmp.renameTo(brandFile(b)) }
    }

    fun removeBrand(b: Brand) { brandFile(b).delete() }

    companion object {
        /** Maximum stored size of one attachment: 10 MB. */
        const val MAX_BYTES = 10L * 1024 * 1024
        /** Photos up to 25 MB are accepted and then downscaled. */
        const val MAX_SOURCE_BYTES = 25L * 1024 * 1024
    }
}
