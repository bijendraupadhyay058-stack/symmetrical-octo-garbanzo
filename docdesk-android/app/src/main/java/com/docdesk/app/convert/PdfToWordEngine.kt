package com.docdesk.app.convert

import android.content.Context
import android.net.Uri
import com.docdesk.app.jobs.Progress
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.core.DocxWriter
import com.docdesk.core.PageContent
import com.docdesk.core.PdfToDocBuilder
import com.docdesk.core.TextSource
import com.docdesk.core.WordMode
import java.io.File

object PdfToWordEngine {

    suspend fun convert(
        context: Context, uri: Uri, inputName: String, password: String?, pages: List<Int>, mode: WordMode,
        ocrMode: OcrMode, language: OcrLanguage, includeImages: Boolean, workDir: File, out: File, progress: Progress,
    ): OperationResult {
        progress.allowPartialResults()
        val contents = mutableListOf<PageContent>()
        val failed = mutableListOf<PageIssue>()
        val sources = mutableListOf<TextSource>()
        var cancelled = false
        var lowConf = 0; var ocrWords = 0
        val warnings = mutableListOf<String>()
        PdfDocs.open(context, uri, password).use { doc ->
            PdfDocs.require(doc, PdfAction.EXTRACT)
            PageTextSource(context, uri, password, doc, workDir, ocrMode, language).use { src ->
                for ((i, p) in pages.withIndex()) {
                    if (progress.cancelRequested) { cancelled = true; break }
                    progress.step("Converting page ${p + 1} (${i + 1} of ${pages.size})", i.toFloat() / pages.size * 0.9f)
                    try {
                        val text = src.get(p)
                        sources.add(text.source)
                        if (text.source == TextSource.NONE) {
                            failed.add(PageIssue(p + 1, if (ocrMode == OcrMode.NEVER) "Scanned page without text – enable OCR to convert it." else "No readable text found."))
                            // Keep the page's images so the page is not silently dropped.
                        }
                        val images = if (includeImages && text.source != TextSource.OCR) PdfTextExtractor.images(doc, p) else emptyList()
                        if (includeImages && doc.getPage(p).rotation % 360 != 0) warnings.add("Page ${p + 1} is rotated; its images were not copied.")
                        contents.add(PageContent(text, images))
                    } catch (e: OutOfMemoryError) {
                        failed.add(PageIssue(p + 1, "Not enough memory to process this page."))
                    } catch (e: Exception) {
                        if (e is com.docdesk.app.jobs.OperationCancelled) throw e
                        failed.add(PageIssue(p + 1, "Could not convert this page (${e.javaClass.simpleName})."))
                    }
                }
                lowConf = src.lowConfidenceWords; ocrWords = src.ocrWords
            }
        }
        progress.step("Building Word document…", 0.93f)
        val docModel = PdfToDocBuilder.build(contents, mode)
        val tmp = File(out.parentFile, out.name + ".part")
        tmp.outputStream().buffered().use { DocxWriter.write(docModel, it) }
        if (!tmp.renameTo(out)) throw java.io.IOException("Could not save the Word file")

        if (ocrWords > 0) {
            warnings.add("$ocrWords word(s) were read with OCR; $lowConf had low confidence and should be checked.")
            warnings.add(Limitations.OCR)
        }
        if (mode == WordMode.LAYOUT) warnings.add("Layout-focused mode keeps line breaks and indents; paragraphs may need joining when you edit.")
        warnings.add("Fonts are mapped to standard fonts; exact typefaces and character spacing are not preserved.")
        val processed = contents.size - failed.count { f -> contents.any { it.text.pageIndex == f.page - 1 } }
        val outcome = when {
            cancelled -> Outcome.CANCELLED
            contents.isEmpty() -> Outcome.FAILED
            failed.isNotEmpty() -> Outcome.PARTIAL
            else -> Outcome.SUCCESS
        }
        val report = OperationReport(
            "PDF to Word", listOf(inputName), outcome, PdfDocs.kindLabel(sources), pages.size, processed.coerceAtLeast(0), failed, warnings.distinct(),
            notes = listOf(Limitations.GENERAL),
        )
        return OperationResult(report, if (contents.isEmpty()) emptyList() else listOf(OutputFile(out)), Preview.Word(docModel))
    }
}
