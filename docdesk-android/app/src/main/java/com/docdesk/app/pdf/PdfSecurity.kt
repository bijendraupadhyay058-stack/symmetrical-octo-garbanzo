package com.docdesk.app.pdf

import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.encryption.AccessPermission
import com.tom_roush.pdfbox.pdmodel.encryption.StandardProtectionPolicy
import java.io.File

enum class Strength(val label: String, val bits: Int, val help: String) {
    AES256("AES-256 (recommended)", 256, "Strongest. Opens in Adobe Reader 9 and later and all current PDF apps."),
    AES128("AES-128 (older readers)", 128, "For very old PDF readers (Adobe Reader 7/8)."),
}

/** What the person may do with the protected PDF without the permissions password. */
data class Allowed(
    val print: Boolean = true,
    val copy: Boolean = false,
    val edit: Boolean = false,
    val comment: Boolean = false,
    val fillForms: Boolean = true,
    val assemble: Boolean = false,
) {
    val all get() = print && copy && edit && comment && fillForms && assemble
    fun toAccessPermission() = AccessPermission().apply {
        setCanPrint(print); setCanPrintFaithful(print)
        setCanExtractContent(copy); setCanExtractForAccessibility(true) // screen readers stay allowed
        setCanModify(edit); setCanModifyAnnotations(comment); setCanFillInForm(fillForms || comment); setCanAssembleDocument(assemble)
    }

    companion object { val EVERYTHING = Allowed(true, true, true, true, true, true) }
}

data class SecurityInfo(
    val encrypted: Boolean,
    val method: String,
    val ownerRights: Boolean,
    val restrictions: List<String>,
)

/** PDF password protection and removal. Never bypasses a password the user doesn't know. */
object PdfSecurity {
    fun describe(doc: PDDocument): SecurityInfo {
        if (!doc.isEncrypted) return SecurityInfo(false, "None", true, emptyList())
        val e = doc.encryption
        val method = when {
            e.version >= 5 || e.revision >= 5 -> "AES-256"
            e.version == 4 && e.length >= 128 && e.getStdCryptFilterDictionary()?.cryptFilterMethod?.name == "AESV2" -> "AES-128"
            e.version == 4 -> "128-bit"
            else -> "RC4 ${e.length}-bit (old, weak)"
        }
        val p = doc.currentAccessPermission
        val r = mutableListOf<String>()
        if (!p.isOwnerPermission) {
            if (!p.canPrint()) r.add("Printing not allowed")
            if (!p.canExtractContent()) r.add("Copying text and images not allowed")
            if (!p.canModify()) r.add("Editing not allowed")
            if (!p.canModifyAnnotations()) r.add("Comments/annotations not allowed")
            if (!p.canFillInForm()) r.add("Form filling not allowed")
            if (!p.canAssembleDocument()) r.add("Page changes (insert, delete, rotate) not allowed")
        }
        return SecurityInfo(true, method, p.isOwnerPermission, r)
    }

    /**
     * Encrypts [doc] into [out]. With no permissions password the open password also acts as the
     * permissions password, so the owner can always remove the protection again with it.
     */
    fun protect(doc: PDDocument, out: File, openPassword: String, permissionsPassword: String?, allowed: Allowed, strength: Strength) {
        require(openPassword.isNotEmpty() || !permissionsPassword.isNullOrEmpty()) { "Set an open password or a permissions password." }
        if (doc.isEncrypted) doc.isAllSecurityToBeRemoved = true
        val owner = permissionsPassword?.takeIf { it.isNotEmpty() } ?: openPassword
        val policy = StandardProtectionPolicy(owner, openPassword, if (permissionsPassword.isNullOrEmpty()) Allowed.EVERYTHING.toAccessPermission() else allowed.toAccessPermission())
        policy.encryptionKeyLength = strength.bits
        // Setting the policy replaces any previous encryption.
        doc.isAllSecurityToBeRemoved = false
        doc.protect(policy)
        PdfOps.saveAtomically(doc, out)
    }

    /** Removes all passwords and restrictions. [doc] must have been opened with owner rights. */
    fun removeAll(doc: PDDocument, out: File) {
        check(!doc.isEncrypted || doc.currentAccessPermission.isOwnerPermission) { "The permissions password is needed to remove this PDF's protection." }
        doc.isAllSecurityToBeRemoved = true
        PdfOps.saveAtomically(doc, out)
    }
}
