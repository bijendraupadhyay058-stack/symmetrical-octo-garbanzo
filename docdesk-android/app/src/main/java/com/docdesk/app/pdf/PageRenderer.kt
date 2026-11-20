package com.docdesk.app.pdf

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.util.LruCache
import com.docdesk.app.jobs.OperationFailed
import java.io.Closeable
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Renders pages with Android's built-in PdfRenderer (fast, good fidelity, offline).
 * PdfRenderer allows only one open page at a time, so access is serialised with a mutex.
 * Rendered bitmaps are cached by size to keep scrolling smooth without exhausting memory.
 *
 * Password-protected files: PdfRenderer cannot open them on most Android versions, so the
 * caller provides a decrypted temporary copy (see [openDecryptedCopy]) that lives in the app's
 * private cache and is deleted when the renderer is closed.
 */
class PageRenderer private constructor(private val pfd: ParcelFileDescriptor, private val tempCopy: File?) : Closeable {
    private val renderer = PdfRenderer(pfd)
    private val mutex = Mutex()
    val pageCount: Int = renderer.pageCount
    private val sizes = HashMap<Int, Pair<Int, Int>>()
    private val bitmapCache = object : LruCache<String, Bitmap>(cacheBytes()) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    @Volatile private var closed = false

    /** Page size in points as displayed (rotation applied). */
    suspend fun pageSize(index: Int): Pair<Int, Int> = sizes[index] ?: mutex.withLock {
        withContext(Dispatchers.IO) {
            renderer.openPage(index).use { p -> (p.width to p.height).also { sizes[index] = it } }
        }
    }

    /** Renders a page [widthPx] wide. Large one-off renders (OCR) should pass cache = false. */
    suspend fun render(index: Int, widthPx: Int, cache: Boolean = true): Bitmap? {
        if (closed) return null
        // Cap normal renders at 2200 px (≈31 MB for A4); OCR renders pass their own size with cache = false.
        val w = if (cache) widthPx.coerceIn(64, 2200) else widthPx.coerceIn(64, 2600)
        val key = "$index@$w"
        if (cache) bitmapCache.get(key)?.let { return it }
        return mutex.withLock {
            if (closed) return@withLock null
            withContext(Dispatchers.IO) {
                renderer.openPage(index).use { page ->
                    sizes[index] = page.width to page.height
                    val h = (w.toFloat() * page.height / page.width).toInt().coerceAtLeast(1)
                    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
                    bmp.eraseColor(Color.WHITE)
                    page.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                    if (cache) bitmapCache.put(key, bmp)
                    bmp
                }
            }
        }
    }

    override fun close() {
        closed = true
        // Wait for any in-flight render before closing the native renderer.
        kotlinx.coroutines.runBlocking { mutex.withLock { runCatching { renderer.close() }; runCatching { pfd.close() } } }
        bitmapCache.evictAll()
        tempCopy?.delete()
    }

    companion object {
        private fun cacheBytes(): Int = (Runtime.getRuntime().maxMemory() / 6).coerceAtMost(96L * 1024 * 1024).toInt()

        /** Opens a renderer for [uri]; falls back to a private copy when the source is not seekable. */
        fun open(context: Context, uri: Uri, workDir: File): PageRenderer {
            try {
                val pfd = context.contentResolver.openFileDescriptor(uri, "r") ?: throw OperationFailed("The file could not be opened.")
                return try { PageRenderer(pfd, null) } catch (e: Exception) { pfd.close(); throw e }
            } catch (e: SecurityException) {
                throw PasswordRequiredException(false)
            } catch (e: java.io.IOException) {
                // Some providers (cloud storage) give a non-seekable stream: render from a private copy.
                val copy = File.createTempFile("view", ".pdf", workDir)
                try {
                    context.contentResolver.openInputStream(uri)?.use { i -> copy.outputStream().use { i.copyTo(it) } }
                    val pfd = ParcelFileDescriptor.open(copy, ParcelFileDescriptor.MODE_READ_ONLY)
                    return try { PageRenderer(pfd, copy) } catch (ex: SecurityException) { pfd.close(); throw PasswordRequiredException(false) }
                } catch (ex: Exception) {
                    copy.delete()
                    if (ex is PasswordRequiredException) throw ex
                    throw OperationFailed("This PDF could not be displayed. It may be damaged.")
                }
            }
        }

        /** For encrypted PDFs: decrypt with the user's password into a private temp file, then render that. */
        fun openDecryptedCopy(context: Context, uri: Uri, password: String, workDir: File): PageRenderer {
            val copy = File.createTempFile("view", ".pdf", workDir)
            try {
                PdfDocs.open(context, uri, password).use { doc ->
                    doc.isAllSecurityToBeRemoved = true
                    doc.save(copy)
                }
                val pfd = ParcelFileDescriptor.open(copy, ParcelFileDescriptor.MODE_READ_ONLY)
                return PageRenderer(pfd, copy)
            } catch (e: Exception) {
                copy.delete(); throw e
            }
        }

        fun open(file: File): PageRenderer = PageRenderer(ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY), null)
    }
}
