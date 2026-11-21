package com.docdesk.app.pdf

import android.content.Context
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.print.PageRange
import android.print.PrintAttributes
import android.print.PrintDocumentAdapter
import android.print.PrintDocumentInfo
import android.print.PrintManager
import java.io.File
import java.io.FileOutputStream

/** Sends a PDF file to Android's print system (any installed printer service, or "Save as PDF"). */
object Printing {
    class NotAllowed : Exception("The author of this PDF has not allowed printing.")

    /**
     * Makes a printable copy: password protection removed (only in this temporary file, which is
     * deleted after printing). Respects the "no printing" permission. Returns the file and page count.
     */
    fun prepare(context: Context, uri: android.net.Uri, password: String?, workDir: File): Pair<File, Int> {
        val f = File.createTempFile("print", ".pdf", workDir)
        try {
            PdfDocs.open(context, uri, password).use { doc ->
                if (doc.isEncrypted && !doc.currentAccessPermission.canPrint()) throw NotAllowed()
                doc.isAllSecurityToBeRemoved = true
                doc.save(f)
                return f to doc.numberOfPages
            }
        } catch (e: Exception) { f.delete(); throw e }
    }

    /** [file] must be an unencrypted PDF; it is deleted after printing when [deleteAfter] is set. */
    fun print(activityContext: Context, file: File, jobName: String, pageCount: Int, deleteAfter: Boolean = false) {
        val pm = activityContext.getSystemService(Context.PRINT_SERVICE) as PrintManager
        pm.print(jobName, object : PrintDocumentAdapter() {
            override fun onLayout(old: PrintAttributes?, new: PrintAttributes, cancel: CancellationSignal, cb: LayoutResultCallback, extras: Bundle?) {
                if (cancel.isCanceled) { cb.onLayoutCancelled(); return }
                cb.onLayoutFinished(PrintDocumentInfo.Builder(jobName).setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT).setPageCount(pageCount).build(), old != new)
            }
            override fun onWrite(pages: Array<out PageRange>, dest: ParcelFileDescriptor, cancel: CancellationSignal, cb: WriteResultCallback) {
                try {
                    file.inputStream().use { inp -> FileOutputStream(dest.fileDescriptor).use { inp.copyTo(it) } }
                    if (cancel.isCanceled) cb.onWriteCancelled() else cb.onWriteFinished(arrayOf(PageRange.ALL_PAGES))
                } catch (e: Exception) { cb.onWriteFailed(e.message) }
            }
            override fun onFinish() { if (deleteAfter) file.delete() }
        }, PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build())
    }
}
