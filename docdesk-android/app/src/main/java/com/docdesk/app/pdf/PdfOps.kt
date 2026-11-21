package com.docdesk.app.pdf

import com.docdesk.app.jobs.Progress
import com.tom_roush.pdfbox.cos.COSDictionary
import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPage
import com.tom_roush.pdfbox.pdmodel.encryption.AccessPermission
import com.tom_roush.pdfbox.pdmodel.encryption.StandardProtectionPolicy
import java.io.File

/** A page reference: page [pageIndex] of source document [source], with extra rotation. */
data class PageRef(val source: Int, val pageIndex: Int, val extraRotation: Int = 0)

/** Page-level operations. Outputs are always new files; sources are never modified. */
object PdfOps {

    /**
     * Copies a page into [target] as a new page object (so the same source page can appear
     * several times, e.g. "duplicate"). Inherited attributes are made explicit.
     */
    fun copyPage(target: PDDocument, page: PDPage, extraRotation: Int): PDPage {
        val dict = COSDictionary()
        for ((k, v) in page.cosObject.entrySet()) if (k != COSName.PARENT) dict.setItem(k, v)
        val copy = PDPage(dict)
        copy.mediaBox = page.mediaBox
        copy.cropBox = page.cropBox
        copy.resources = page.resources
        copy.rotation = ((page.rotation + extraRotation) % 360 + 360) % 360
        target.addPage(copy)
        return copy
    }

    /** Builds one PDF from [pages] taken from [sources] (all must stay open until saved). */
    suspend fun assemble(sources: List<PDDocument>, pages: List<PageRef>, out: File, progress: Progress? = null) {
        PDDocument().use { target ->
            pages.forEachIndexed { i, ref ->
                progress?.step("Adding page ${i + 1} of ${pages.size}", i.toFloat() / pages.size)
                copyPage(target, sources[ref.source].getPage(ref.pageIndex), ref.extraRotation)
            }
            progress?.step("Saving…", 0.98f)
            target.documentInformation.producer = "DocDesk"
            saveAtomically(target, out)
        }
    }

    /** Writes to a temporary file first so an interrupted save never leaves a half-written PDF. */
    fun saveAtomically(doc: PDDocument, out: File) {
        val tmp = File(out.parentFile, out.name + ".part")
        try {
            doc.save(tmp)
            if (out.exists()) out.delete()
            if (!tmp.renameTo(out)) throw java.io.IOException("Could not finish writing ${out.name}")
        } finally {
            tmp.delete()
        }
    }

    /**
     * Prepares a modified, originally encrypted document for saving (PdfBox refuses to save an
     * encrypted document without a decision). Opened with the user password: the output keeps
     * the same password and permissions (re-encrypted with AES-256). Opened with owner rights:
     * protection is removed and the caller tells the user. Returns a note for the report.
     */
    fun keepProtectionForSave(doc: PDDocument, enteredPassword: String?): String? {
        if (!doc.isEncrypted) return null
        val perm = doc.currentAccessPermission
        return if (perm.isOwnerPermission) {
            doc.isAllSecurityToBeRemoved = true
            "The original was password-protected and you opened it with full (owner) rights, so the new file is not protected. Use Files › Add password if needed."
        } else {
            val keep = AccessPermission(perm.permissionBytes)
            val policy = StandardProtectionPolicy(java.util.UUID.randomUUID().toString(), enteredPassword ?: "", keep).apply { encryptionKeyLength = 256; isPreferAES = true }
            doc.protect(policy)
            "The new file keeps the original's password and permissions (now encrypted with AES-256)."
        }
    }

    /**
     * Same policy as [keepProtectionForSave] for a document rebuilt from an unencrypted
     * intermediate copy: [original] is the source's access permission (null if it was not encrypted).
     */
    fun reapplyProtection(original: AccessPermission?, target: PDDocument, enteredPassword: String?): String? {
        if (original == null) return null
        if (original.isOwnerPermission) return "The original was password-protected and you opened it with full (owner) rights, so the new file is not protected. Use Files › Add password if needed."
        val policy = StandardProtectionPolicy(java.util.UUID.randomUUID().toString(), enteredPassword ?: "", AccessPermission(original.permissionBytes)).apply { encryptionKeyLength = 256; isPreferAES = true }
        target.protect(policy)
        return "The new file keeps the original's password and permissions (now encrypted with AES-256)."
    }

}
