package com.docdesk.app.convert

import android.content.Context
import android.net.Uri
import com.docdesk.app.ocr.OcrEngine
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.core.PageText
import com.docdesk.core.TextSource
import com.tom_roush.pdfbox.pdmodel.PDDocument
import java.io.Closeable
import java.io.File

enum class OcrMode(val label: String) {
    AUTO("Automatic – OCR only pages without text"),
    ALWAYS("Always use OCR (for PDFs with a poor text layer)"),
    NEVER("Never use OCR"),
}

/**
 * Supplies positioned text for a page from the PDF text layer, falling back to on-device OCR
 * for scanned pages. Rendering for OCR uses Android's PdfRenderer (it decodes JBIG2/JPX scans
 * that PdfBox-Android cannot).
 */
class PageTextSource(
    private val context: Context,
    private val uri: Uri,
    private val password: String?,
    private val doc: PDDocument,
    private val workDir: File,
    private val mode: OcrMode,
    private val language: OcrLanguage,
) : Closeable {
    private var renderer: PageRenderer? = null
    var lowConfidenceWords = 0; private set
    var ocrWords = 0; private set

    suspend fun get(pageIndex: Int): PageText {
        if (mode != OcrMode.ALWAYS) {
            val t = PdfTextExtractor.extract(doc, pageIndex)
            // Fewer than 20 characters (e.g. only a scanner's page stamp) means the page is effectively scanned.
            if (t.words.sumOf { it.text.length } >= 20 || mode == OcrMode.NEVER) return t
        }
        val r = renderer ?: (if (doc.isEncrypted) PageRenderer.openDecryptedCopy(context, uri, password ?: "", workDir) else PageRenderer.open(context, uri, workDir)).also { renderer = it }
        val (wPt, hPt) = r.pageSize(pageIndex)
        val bmp = r.render(pageIndex, OcrEngine.ocrWidthPx(wPt.toFloat()), cache = false) ?: return PageText(pageIndex, wPt.toFloat(), hPt.toFloat(), emptyList(), TextSource.NONE)
        val res = try { OcrEngine.recognize(bmp, language, pageIndex, wPt.toFloat(), hPt.toFloat()) } finally { bmp.recycle() }
        lowConfidenceWords += res.lowConfidenceWords
        ocrWords += res.totalWords
        return if (res.page.words.isEmpty()) res.page.copy(source = TextSource.NONE) else res.page
    }

    override fun close() { renderer?.close() }
}
