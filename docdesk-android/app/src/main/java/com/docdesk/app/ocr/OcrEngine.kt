package com.docdesk.app.ocr

import android.graphics.Bitmap
import com.docdesk.core.PageText
import com.docdesk.core.TextSource
import com.docdesk.core.TextWord
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.devanagari.DevanagariTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.tasks.await

/**
 * On-device OCR with Google ML Kit Text Recognition v2. Both models are *bundled* in the APK
 * (com.google.mlkit:text-recognition and :text-recognition-devanagari), so OCR works offline
 * and no image leaves the phone.
 *  - LATIN: English and other Latin-script languages.
 *  - DEVANAGARI: Hindi (and Marathi/Nepali/Sanskrit); this model also reads Latin text,
 *    so it suits mixed Hindi + English documents.
 */
enum class OcrLanguage(val label: String) {
    LATIN("English (Latin script)"),
    DEVANAGARI("Hindi + English (Devanagari)"),
}

data class OcrResult(val page: PageText, val fullText: String, val lowConfidenceWords: Int, val totalWords: Int)

object OcrEngine {
    private var latin: TextRecognizer? = null
    private var devanagari: TextRecognizer? = null

    @Synchronized private fun client(lang: OcrLanguage): TextRecognizer = when (lang) {
        OcrLanguage.LATIN -> latin ?: TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS).also { latin = it }
        OcrLanguage.DEVANAGARI -> devanagari ?: TextRecognition.getClient(DevanagariTextRecognizerOptions.Builder().build()).also { devanagari = it }
    }

    /**
     * Recognises [bitmap] and maps word boxes into page units ([pageWidth] × [pageHeight]),
     * so OCR words can go through the same table/paragraph logic as PDF text.
     */
    suspend fun recognize(bitmap: Bitmap, lang: OcrLanguage, pageIndex: Int, pageWidth: Float, pageHeight: Float, lowConfidence: Float = 0.75f): OcrResult {
        val text: Text = client(lang).process(InputImage.fromBitmap(bitmap, 0)).await()
        val sx = pageWidth / bitmap.width
        val sy = pageHeight / bitmap.height
        val words = mutableListOf<TextWord>()
        var low = 0
        for (block in text.textBlocks) for (line in block.lines) for (el in line.elements) {
            val box = el.boundingBox ?: continue
            val conf = el.confidence.takeIf { it > 0f }
            if (conf != null && conf < lowConfidence) low++
            val h = box.height() * sy
            words.add(TextWord(el.text, box.left * sx, box.top * sy, box.width() * sx, h, h * 0.8f, confidence = conf ?: 0.5f))
        }
        return OcrResult(PageText(pageIndex, pageWidth, pageHeight, words, TextSource.OCR), text.text, low, words.size)
    }

    /** Render scale for OCR: aim for ~300 DPI equivalent, capped for memory. */
    fun ocrWidthPx(pageWidthPt: Float): Int = (pageWidthPt / 72f * 300f).toInt().coerceIn(1200, 2400)
}
