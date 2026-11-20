package com.docdesk.app.pdf

import android.content.Context
import android.net.Uri
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.core.TextSource
import com.tom_roush.pdfbox.io.MemoryUsageSetting
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.encryption.InvalidPasswordException
import com.tom_roush.pdfbox.text.PDFTextStripper
import java.io.File

class PasswordRequiredException(val wrongPassword: Boolean) : Exception(if (wrongPassword) "Incorrect password" else "Password required")

enum class PdfAction(val label: String) { VIEW("view"), EXTRACT("copy or convert content from"), ASSEMBLE("rearrange, merge or split"), MODIFY("edit or annotate") }

enum class PdfKind(val label: String) { TEXT("Text-based PDF"), SCANNED("Scanned PDF (images only)"), MIXED("Mixed PDF (text and scanned pages)"), EMPTY("No readable content") }

data class PdfInfo(val pageCount: Int, val encrypted: Boolean, val kind: PdfKind?, val textPages: Set<Int>)

/**
 * Opening PDFs with PdfBox. Passwords are only held in memory by the caller and passed here;
 * they are never stored or logged. Document permissions set by the author are respected:
 * an operation the permissions forbid is refused rather than bypassed.
 */
object PdfDocs {
    private val memory: MemoryUsageSetting get() = MemoryUsageSetting.setupMixed(48L * 1024 * 1024)

    fun open(context: Context, uri: Uri, password: String?): PDDocument {
        val input = context.contentResolver.openInputStream(uri) ?: throw OperationFailed("The file could not be opened.")
        return input.use {
            try {
                PDDocument.load(it, password ?: "", memory)
            } catch (e: InvalidPasswordException) {
                throw PasswordRequiredException(wrongPassword = !password.isNullOrEmpty())
            }
        }
    }

    fun open(file: File, password: String? = null): PDDocument = try {
        PDDocument.load(file, password ?: "", memory)
    } catch (e: InvalidPasswordException) {
        throw PasswordRequiredException(!password.isNullOrEmpty())
    }

    fun require(doc: PDDocument, action: PdfAction) {
        if (!doc.isEncrypted) return
        val p = doc.currentAccessPermission
        if (p.isOwnerPermission) return
        val allowed = when (action) {
            PdfAction.VIEW -> true
            PdfAction.EXTRACT -> p.canExtractContent()
            PdfAction.ASSEMBLE -> p.canAssembleDocument() || p.canModify()
            PdfAction.MODIFY -> p.canModify() || p.canModifyAnnotations()
        }
        if (!allowed) throw OperationFailed("The author of this PDF does not allow you to ${action.label} it. DocDesk respects these restrictions; ask the owner for an unrestricted copy.")
    }

    /** Page count, encryption, and whether pages carry real text (vs. scanned images). */
    fun inspect(doc: PDDocument, sampleLimit: Int = 30): PdfInfo {
        val n = doc.numberOfPages
        val textPages = mutableSetOf<Int>()
        val canExtract = !doc.isEncrypted || doc.currentAccessPermission.canExtractContent() || doc.currentAccessPermission.isOwnerPermission
        if (!canExtract) return PdfInfo(n, doc.isEncrypted, null, emptySet())
        val stripper = PDFTextStripper()
        val sample = if (n <= sampleLimit) 0 until n else (0 until n step (n / sampleLimit).coerceAtLeast(1))
        for (i in sample) {
            stripper.startPage = i + 1; stripper.endPage = i + 1
            val t = runCatching { stripper.getText(doc) }.getOrDefault("")
            if (t.count { !it.isWhitespace() } >= 20) textPages.add(i)
        }
        val sampled = sample.count()
        val kind = when {
            sampled == 0 -> PdfKind.EMPTY
            textPages.size == sampled -> PdfKind.TEXT
            textPages.isEmpty() -> PdfKind.SCANNED
            else -> PdfKind.MIXED
        }
        return PdfInfo(n, doc.isEncrypted, kind, textPages)
    }

    fun pageHasText(doc: PDDocument, index: Int): Boolean {
        val stripper = PDFTextStripper().apply { startPage = index + 1; endPage = index + 1 }
        return runCatching { stripper.getText(doc) }.getOrDefault("").count { !it.isWhitespace() } >= 20
    }

    fun kindLabel(sources: Collection<TextSource>): String = when {
        sources.isEmpty() -> PdfKind.EMPTY.label
        sources.all { it == TextSource.PDF_TEXT } -> PdfKind.TEXT.label
        sources.all { it == TextSource.OCR } -> PdfKind.SCANNED.label + " – read with OCR"
        sources.all { it == TextSource.NONE } -> PdfKind.EMPTY.label
        else -> PdfKind.MIXED.label
    }
}
