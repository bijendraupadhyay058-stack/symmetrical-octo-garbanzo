package com.docdesk.app.convert

import android.content.Context
import android.net.Uri
import com.docdesk.app.jobs.Progress
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.core.ExcelExport
import com.docdesk.core.ExcelExportOptions
import com.docdesk.core.ExtractedTable
import com.docdesk.core.FinancialCheckResult
import com.docdesk.core.FinancialChecks
import com.docdesk.core.NumberStyle
import com.docdesk.core.TableExtractor
import com.docdesk.core.TableOptions
import com.docdesk.core.TextSource
import com.docdesk.core.XlsxWriter
import java.io.File

data class ExtractionResult(
    val tables: List<ExtractedTable>,
    val pagesSelected: Int,
    val pagesDone: List<Int>,
    val failed: List<PageIssue>,
    val pagesWithoutTables: List<Int>,
    val sources: Map<Int, TextSource>,
    val statementLines: List<String>,
    val lowConfidenceWords: Int,
    val ocrWords: Int,
    val cancelled: Boolean,
)

/** Stage 1: find tables (user reviews them next). Stage 2: [export] to .xlsx. */
object PdfToExcelEngine {

    suspend fun extract(
        context: Context, uri: Uri, password: String?, pages: List<Int>, ocrMode: OcrMode, language: OcrLanguage,
        options: TableOptions, workDir: File, progress: Progress,
    ): ExtractionResult {
        progress.allowPartialResults()
        val tables = mutableListOf<ExtractedTable>()
        val done = mutableListOf<Int>()
        val failed = mutableListOf<PageIssue>()
        val empty = mutableListOf<Int>()
        val sources = LinkedHashMap<Int, TextSource>()
        val statementLines = mutableListOf<String>()
        var cancelled = false
        PdfDocs.open(context, uri, password).use { doc ->
            PdfDocs.require(doc, PdfAction.EXTRACT)
            PageTextSource(context, uri, password, doc, workDir, ocrMode, language).use { src ->
                for ((i, p) in pages.withIndex()) {
                    if (progress.cancelRequested) { cancelled = true; break }
                    progress.step("Reading page ${p + 1} (${i + 1} of ${pages.size})", i.toFloat() / pages.size)
                    try {
                        val text = src.get(p)
                        sources[p] = text.source
                        if (text.source == TextSource.NONE) {
                            failed.add(PageIssue(p + 1, if (ocrMode == OcrMode.NEVER) "No text layer (scanned page). Turn on OCR to read it." else "No readable text found, even with OCR."))
                            continue
                        }
                        val found = TableExtractor.extract(text, options)
                        if (found.isEmpty()) empty.add(p + 1)
                        tables.addAll(found)
                        // Lines for statement-total checks (only when printed on the page).
                        if (text.source == TextSource.PDF_TEXT) statementLines.addAll(PdfTextExtractor.plainText(doc, p).lines().filter { l -> l.contains("balance", true) || l.contains("total", true) })
                        else statementLines.addAll(com.docdesk.core.LineGrouper.group(text.words).map { it.text }.filter { l -> l.contains("balance", true) || l.contains("total", true) })
                        done.add(p)
                    } catch (e: OutOfMemoryError) {
                        failed.add(PageIssue(p + 1, "Not enough memory to process this page."))
                    } catch (e: Exception) {
                        if (e is com.docdesk.app.jobs.OperationCancelled) throw e
                        failed.add(PageIssue(p + 1, "Could not read this page (${e.javaClass.simpleName})."))
                    }
                }
                return ExtractionResult(tables, pages.size, done, failed, empty, sources, statementLines, src.lowConfidenceWords, src.ocrWords, cancelled)
            }
        }
    }

    fun checks(tables: List<ExtractedTable>, style: NumberStyle, statementLines: List<String>): List<Pair<Int, FinancialCheckResult>> =
        TableExtractor.combine(tables).mapIndexedNotNull { i, t ->
            val r = FinancialChecks.run(t, style, statementLines)
            if (r.debitColumn == null && r.creditColumn == null && r.balanceColumn == null) null else i to r
        }

    fun describe(r: FinancialCheckResult): List<String> = buildList {
        add("Transaction rows detected: ${r.transactionRows}")
        r.totalDebit?.let { add("Total of \"${r.debitColumn}\": ${com.docdesk.core.AmountParser.formatIndian(it)}") }
        r.totalCredit?.let { add("Total of \"${r.creditColumn}\": ${com.docdesk.core.AmountParser.formatIndian(it)}") }
        if (r.balanceRowsChecked > 0) {
            add(if (r.balanceMismatches.isEmpty()) "Running balance reconciles on all ${r.balanceRowsChecked} checked rows."
            else "Running balance does NOT reconcile on ${r.balanceMismatches.size} row(s): ${r.balanceMismatches.take(15).joinToString(", ")}${if (r.balanceMismatches.size > 15) "…" else ""}. Check these rows against the PDF.")
        }
        r.statementTotalsFound.take(4).forEach { add("Found on statement: $it") }
        addAll(r.notes)
    }

    fun export(tables: List<ExtractedTable>, options: ExcelExportOptions, report: List<Pair<String, String>>, out: File): ExcelExport.Built {
        val built = ExcelExport.build(tables, options, report)
        val tmp = File(out.parentFile, out.name + ".part")
        tmp.outputStream().buffered().use { XlsxWriter.write(built.sheets, it) }
        if (!tmp.renameTo(out)) throw java.io.IOException("Could not save the spreadsheet")
        return built
    }
}
