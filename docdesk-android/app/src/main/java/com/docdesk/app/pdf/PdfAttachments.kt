package com.docdesk.app.pdf

import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDDocumentNameDictionary
import com.tom_roush.pdfbox.pdmodel.PDEmbeddedFilesNameTreeNode
import com.tom_roush.pdfbox.pdmodel.common.filespecification.PDComplexFileSpecification
import com.tom_roush.pdfbox.pdmodel.common.filespecification.PDEmbeddedFile
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationFileAttachment
import java.io.InputStream
import java.util.Calendar

/** A file stored inside a PDF. [key] identifies it: "n:<name-tree key>" or "a:<page>:<index>" for page annotations. */
data class Attachment(val key: String, val name: String, val size: Long?, val description: String?, val modified: Calendar?, val onPage: Int?)

/** Lists, adds, extracts and removes files attached to a PDF (document attachments and paperclip annotations). */
object PdfAttachments {
    private fun tree(doc: PDDocument, create: Boolean): PDEmbeddedFilesNameTreeNode? {
        val cat = doc.documentCatalog
        var names = cat.names
        if (names == null) { if (!create) return null; names = PDDocumentNameDictionary(cat); cat.names = names }
        var ef = names.embeddedFiles
        if (ef == null) { if (!create) return null; ef = PDEmbeddedFilesNameTreeNode(); names.embeddedFiles = ef }
        return ef
    }

    /** Flattens the name tree (it may be split into kids) into one map. */
    private fun all(node: com.tom_roush.pdfbox.pdmodel.common.PDNameTreeNode<PDComplexFileSpecification>?, depth: Int = 0): Map<String, PDComplexFileSpecification> {
        if (node == null || depth > 20) return emptyMap() // guards against looping trees in damaged files
        val out = LinkedHashMap<String, PDComplexFileSpecification>()
        runCatching { node.names }.getOrNull()?.let { out.putAll(it) }
        runCatching { node.kids }.getOrNull()?.forEach { out.putAll(all(it, depth + 1)) }
        return out
    }

    private fun PDComplexFileSpecification.embedded(): PDEmbeddedFile? = embeddedFileUnicode ?: embeddedFile ?: embeddedFileUnix ?: embeddedFileMac ?: embeddedFileDos
    private fun PDComplexFileSpecification.displayName(fallback: String) = (fileUnicode ?: filename ?: fallback).substringAfterLast('/').substringAfterLast('\\').ifBlank { fallback }

    fun list(doc: PDDocument): List<Attachment> {
        val out = mutableListOf<Attachment>()
        for ((k, spec) in all(tree(doc, false))) {
            val ef = spec.embedded()
            out.add(Attachment("n:$k", spec.displayName(k), ef?.let { (it.size.takeIf { s -> s > 0 } ?: it.length).toLong() }, spec.fileDescription, ef?.modDate, null))
        }
        doc.pages.forEachIndexed { p, page ->
            runCatching { page.annotations }.getOrDefault(emptyList()).forEachIndexed { i, a ->
                if (a is PDAnnotationFileAttachment) {
                    val spec = a.file as? PDComplexFileSpecification ?: return@forEachIndexed
                    val ef = spec.embedded() ?: return@forEachIndexed
                    out.add(Attachment("a:$p:$i", spec.displayName("attachment-${p + 1}-$i"), (ef.size.takeIf { it > 0 } ?: ef.length).toLong(), a.contents ?: spec.fileDescription, ef.modDate, p))
                }
            }
        }
        return out
    }

    /** Opens the attached file's bytes. The stream belongs to [doc]; read it before closing the document. */
    fun open(doc: PDDocument, key: String): InputStream {
        val spec = spec(doc, key) ?: throw IllegalArgumentException("Attachment not found")
        return spec.embedded()?.createInputStream() ?: throw IllegalStateException("This attachment has no content")
    }

    private fun spec(doc: PDDocument, key: String): PDComplexFileSpecification? = when {
        key.startsWith("n:") -> all(tree(doc, false))[key.removePrefix("n:")]
        key.startsWith("a:") -> key.removePrefix("a:").split(':').let { (p, i) -> (doc.getPage(p.toInt()).annotations[i.toInt()] as? PDAnnotationFileAttachment)?.file as? PDComplexFileSpecification }
        else -> null
    }

    /** Attaches a file at document level. A name that is already used gets " (2)" etc. Returns the name used. */
    fun add(doc: PDDocument, name: String, mime: String?, data: InputStream, description: String? = null): String {
        val node = tree(doc, true)!!
        val existing = all(node).toMutableMap()
        val clean = name.replace(Regex("""[\\/:*?"<>|\x00-\x1f]"""), "_").ifBlank { "attachment" }
        var unique = clean; var n = 2
        val existingNames = existing.values.map { it.displayName("") }.toSet() + existing.keys
        while (unique in existingNames) { unique = clean.substringBeforeLast('.') + " ($n)" + (if (clean.contains('.')) "." + clean.substringAfterLast('.') else ""); n++ }
        val ef = PDEmbeddedFile(doc, data)
        ef.subtype = mime ?: "application/octet-stream"
        ef.size = ef.length
        ef.creationDate = Calendar.getInstance(); ef.modDate = Calendar.getInstance()
        val spec = PDComplexFileSpecification()
        spec.file = unique; spec.fileUnicode = unique
        spec.embeddedFile = ef; spec.embeddedFileUnicode = ef
        if (!description.isNullOrBlank()) spec.fileDescription = description
        existing[unique] = spec
        // Rewrite as one flat, sorted leaf (name trees must be sorted).
        node.kids = null
        node.names = existing.toSortedMap()
        return unique
    }

    /** Removes the given attachments. Returns how many were removed. */
    fun remove(doc: PDDocument, keys: Set<String>): Int {
        var n = 0
        val nameKeys = keys.filter { it.startsWith("n:") }.map { it.removePrefix("n:") }.toSet()
        if (nameKeys.isNotEmpty()) tree(doc, false)?.let { node ->
            val m = all(node).toMutableMap()
            nameKeys.forEach { if (m.remove(it) != null) n++ }
            node.kids = null
            if (m.isEmpty()) doc.documentCatalog.names?.embeddedFiles = null else node.names = m.toSortedMap()
        }
        keys.filter { it.startsWith("a:") }.map { it.removePrefix("a:").split(':').let { (p, i) -> p.toInt() to i.toInt() } }
            .groupBy({ it.first }, { it.second }).forEach { (p, idx) ->
                val page = doc.getPage(p)
                val list = page.annotations
                idx.sortedDescending().forEach { i -> if (i < list.size && list[i] is PDAnnotationFileAttachment) { list.removeAt(i); n++ } }
                page.annotations = list
            }
        return n
    }
}
