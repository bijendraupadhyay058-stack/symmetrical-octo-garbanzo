package com.docdesk.app.convert

import android.content.Context
import com.docdesk.app.data.InputDoc
import com.docdesk.app.edit.Annot
import com.docdesk.app.edit.AnnotationWriter
import com.docdesk.app.edit.NPoint
import com.docdesk.app.edit.NRect
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.Progress
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.pdf.PdfTextExtractor
import com.docdesk.core.Change
import com.docdesk.core.DiffLine
import com.docdesk.core.LineGrouper
import com.docdesk.core.PageText
import com.docdesk.core.TextDiff
import com.docdesk.core.TextLine
import java.io.File

/** Compares the text of two PDFs and produces highlighted copies plus a change report. */
object CompareEngine {
    private const val GREEN = 0xFF66BB6A.toInt()
    private const val ORANGE = 0xFFFFA726.toInt()
    private const val RED = 0xFFE53935.toInt()
    private const val MAX_MARKS = 3000

    private class Side(val pages: List<PageText>, val lines: List<List<TextLine>>) {
        val diffLines = lines.flatMapIndexed { p, ls -> ls.mapIndexed { i, l -> DiffLine(p, i, l.text) } }
        val emptyPages = pages.filter { it.words.isEmpty() }.map { it.pageIndex + 1 }
    }

    private fun read(context: Context, d: InputDoc, pw: String?, progress: Progress, label: String, from: Float): Side = PdfDocs.open(context, d.uri, pw).use { doc ->
        PdfDocs.require(doc, PdfAction.EXTRACT)
        val pages = (0 until doc.numberOfPages).map { i ->
            progress.step("Reading $label, page ${i + 1} of ${doc.numberOfPages}", from + 0.3f * i / doc.numberOfPages)
            PdfTextExtractor.extract(doc, i)
        }
        Side(pages, pages.map { LineGrouper.group(it.words) })
    }

    private fun rectOf(line: TextLine, words: Set<Int>?, page: PageText): List<NRect> {
        val ws = line.words
        val groups = mutableListOf<MutableList<Int>>()
        for (i in ws.indices) if (words == null || i in words) { if (groups.isNotEmpty() && groups.last().last() == i - 1) groups.last().add(i) else groups.add(mutableListOf(i)) }
        return groups.map { g ->
            val sel = g.map { ws[it] }
            NRect(sel.minOf { it.x } / page.width, sel.minOf { it.y } / page.height, sel.maxOf { it.right } / page.width, sel.maxOf { it.bottom } / page.height)
        }
    }

    suspend fun compare(context: Context, old: InputDoc, oldPw: String?, new: InputDoc, newPw: String?, ignoreCase: Boolean, outDir: (String) -> File, progress: Progress): OperationResult {
        val a = read(context, old, oldPw, progress, "original", 0f)
        val b = read(context, new, newPw, progress, "new version", 0.3f)
        if (a.diffLines.isEmpty() || b.diffLines.isEmpty()) throw OperationFailed("One of the PDFs has no text to compare (it may be scanned). Make it searchable first with Scan & OCR › Extract text › Create searchable PDF.")
        progress.step("Comparing…", 0.65f)
        val changes = TextDiff.diff(a.diffLines, b.diffLines, ignoreCase)

        val newMarks = mutableListOf<Annot>(); val oldMarks = mutableListOf<Annot>()
        var id = 1L
        val report = StringBuilder()
        var added = 0; var removed = 0; var modified = 0
        for (c in changes) {
            when (c) {
                is Change.Added -> {
                    added++
                    val pg = b.pages[c.new.page]; val line = b.lines[c.new.page][c.new.index]
                    rectOf(line, null, pg).forEach { newMarks.add(Annot.Box(id++, c.new.page, Annot.BoxKind.HIGHLIGHT, it, GREEN, 1f)) }
                    report.append("+ New p${c.new.page + 1}: ${c.new.text}\n")
                }
                is Change.Removed -> {
                    removed++
                    val pg = a.pages[c.old.page]; val line = a.lines[c.old.page][c.old.index]
                    rectOf(line, null, pg).forEach { oldMarks.add(Annot.Box(id++, c.old.page, Annot.BoxKind.STRIKE, it, RED, 1.2f)) }
                    report.append("− Removed (original p${c.old.page + 1}): ${c.old.text}\n")
                }
                is Change.Modified -> {
                    modified++
                    val pgN = b.pages[c.new.page]; val lineN = b.lines[c.new.page][c.new.index]
                    val pgO = a.pages[c.old.page]; val lineO = a.lines[c.old.page][c.old.index]
                    rectOf(lineN, c.newWords.ifEmpty { null }, pgN).forEach { newMarks.add(Annot.Box(id++, c.new.page, Annot.BoxKind.HIGHLIGHT, it, ORANGE, 1f)) }
                    rectOf(lineO, c.oldWords.ifEmpty { null }, pgO).forEach { oldMarks.add(Annot.Box(id++, c.old.page, Annot.BoxKind.HIGHLIGHT, it, ORANGE, 1f)) }
                    newMarks.add(Annot.Note(id++, c.new.page, NPoint((lineN.right / pgN.width + 0.01f).coerceAtMost(0.95f), lineN.top / pgN.height), "Changed. Original: ${c.old.text}", ORANGE))
                    report.append("~ Changed p${c.new.page + 1}: \"${c.old.text}\" → \"${c.new.text}\"\n")
                }
            }
        }
        val warnings = mutableListOf<String>()
        if (a.emptyPages.isNotEmpty()) warnings.add("Original: page(s) ${a.emptyPages.joinToString()} have no text (scanned?) and were not compared.")
        if (b.emptyPages.isNotEmpty()) warnings.add("New version: page(s) ${b.emptyPages.joinToString()} have no text (scanned?) and were not compared.")
        warnings.add("Only text is compared. Changes in images, signatures, stamps, colours or layout are not detected.")
        val summary = if (changes.isEmpty()) "No text differences found." else "$modified changed, $added added and $removed removed line(s)."

        val outputs = mutableListOf<OutputFile>()
        if (changes.isNotEmpty()) {
            if (newMarks.size + oldMarks.size > MAX_MARKS) warnings.add("Very many differences: only the first $MAX_MARKS are highlighted; the report lists all.")
            progress.step("Marking the new version…", 0.75f)
            val outNew = outDir("${com.docdesk.app.data.FileRepository.baseName(new.name)} (changes highlighted).pdf")
            PdfDocs.open(context, new.uri, newPw).use { doc -> PdfOps.keepProtectionForSave(doc, newPw); AnnotationWriter.write(doc, newMarks.take(MAX_MARKS), outNew, null, editable = true) }
            outputs.add(OutputFile(outNew))
            if (oldMarks.isNotEmpty()) {
                progress.step("Marking the original…", 0.87f)
                val outOld = outDir("${com.docdesk.app.data.FileRepository.baseName(old.name)} (original, removals marked).pdf")
                PdfDocs.open(context, old.uri, oldPw).use { doc -> PdfOps.keepProtectionForSave(doc, oldPw); AnnotationWriter.write(doc, oldMarks.take(MAX_MARKS), outOld, null, editable = true) }
                outputs.add(OutputFile(outOld))
            }
        }
        val reportText = "Comparison of\n  Original: ${old.name}\n  New: ${new.name}\n\n$summary\n\nLegend: green = new text, orange = changed words, red strike-through = removed (in the original).\n\n$report"
        val txt = outDir("Comparison report.txt"); txt.writeText(reportText)
        outputs.add(OutputFile(txt))
        return OperationResult(
            OperationReport("Compare PDFs", listOf(old.name, new.name), Outcome.SUCCESS, pagesSelected = a.pages.size + b.pages.size, pagesProcessed = a.pages.size + b.pages.size, warnings = warnings,
                checks = listOf(summary), notes = listOf("Highlights are editable PDF annotations; changed lines also have a comment with the original wording.")),
            outputs, Preview.Text(reportText),
        )
    }
}
