package com.docdesk.app.convert

import com.docdesk.core.DocDocument
import com.docdesk.core.XSheet
import java.io.File

enum class Outcome(val label: String) { SUCCESS("Completed"), PARTIAL("Completed with problems"), CANCELLED("Cancelled – partial result"), FAILED("Failed") }

data class PageIssue(val page: Int, val message: String)

/** What the user sees after every operation: never claims success for work that failed. */
data class OperationReport(
    val operation: String,
    val inputNames: List<String>,
    val outcome: Outcome,
    val documentKind: String? = null,
    val pagesSelected: Int? = null,
    val pagesProcessed: Int? = null,
    val failedPages: List<PageIssue> = emptyList(),
    val warnings: List<String> = emptyList(),
    val checks: List<String> = emptyList(),
    val notes: List<String> = emptyList(),
) {
    val summary: String
        get() = buildString {
            append(outcome.label)
            if (pagesSelected != null) append(" · ${pagesProcessed ?: 0} of $pagesSelected pages")
            if (failedPages.isNotEmpty()) append(" · ${failedPages.size} failed")
            if (warnings.isNotEmpty()) append(" · ${warnings.size} warning(s)")
        }
}

data class OutputFile(val file: File, val displayName: String = file.name)

sealed class Preview {
    data class Pdf(val file: File) : Preview()
    data class Word(val doc: DocDocument) : Preview()
    data class Sheets(val sheets: List<XSheet>) : Preview()
    data class Text(val text: String) : Preview()
}

data class OperationResult(val report: OperationReport, val outputs: List<OutputFile>, val preview: Preview? = null)

/** Standard limitation notes shown with conversions (spec §16). */
object Limitations {
    const val GENERAL = "Conversion is never perfect. Complex tables, merged cells, unusual fonts, handwriting and image quality can affect the result. Please check the output against the original."
    const val OCR = "OCR accuracy drops with poor image quality, handwriting, complex layouts and faint text. Low-confidence words are flagged for review."
    const val FINANCIAL = "Totals and balance checks help find extraction errors but do not guarantee that every row was captured correctly."
}
