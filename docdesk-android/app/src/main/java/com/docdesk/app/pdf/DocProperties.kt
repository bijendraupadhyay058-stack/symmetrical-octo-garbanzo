package com.docdesk.app.pdf

import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDDocumentInformation
import java.util.Calendar

/** The document's descriptive information (title, author …) shown by PDF readers and search engines. */
data class DocProps(
    val title: String = "", val author: String = "", val subject: String = "", val keywords: String = "",
    val creator: String = "", val producer: String = "",
    val created: Calendar? = null, val modified: Calendar? = null,
    val hasXmp: Boolean = false, val customKeys: List<String> = emptyList(),
)

object DocProperties {
    private val standard = setOf("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate", "Trapped")

    fun read(doc: PDDocument): DocProps {
        val i = doc.documentInformation
        return DocProps(
            i.title.orEmpty(), i.author.orEmpty(), i.subject.orEmpty(), i.keywords.orEmpty(), i.creator.orEmpty(), i.producer.orEmpty(),
            runCatching { i.creationDate }.getOrNull(), runCatching { i.modificationDate }.getOrNull(),
            doc.documentCatalog.metadata != null,
            i.metadataKeys.filter { it !in standard }.sorted(),
        )
    }

    /** Writes the editable fields. Blank fields are removed. Stale XMP is dropped so readers don't show old values. */
    fun write(doc: PDDocument, p: DocProps) {
        val i = doc.documentInformation
        fun set(k: String, v: String) = if (v.isBlank()) i.cosObject.removeItem(COSName.getPDFName(k)) else i.setCustomMetadataValue(k, v.trim())
        set("Title", p.title); set("Author", p.author); set("Subject", p.subject); set("Keywords", p.keywords); set("Creator", p.creator)
        i.modificationDate = Calendar.getInstance()
        doc.documentInformation = i
        // XMP usually repeats the old title/author; keeping it would contradict the new values.
        doc.documentCatalog.cosObject.removeItem(COSName.METADATA)
        if (p.title.isNotBlank()) doc.documentCatalog.viewerPreferences?.setDisplayDocTitle(true)
    }

    /**
     * Removes all document-level hidden information: the info dictionary, XMP metadata, per-page
     * and per-image metadata streams, page piece info and embedded thumbnails.
     * Returns the number of items removed.
     */
    fun stripAll(doc: PDDocument): Int {
        var n = doc.documentInformation.metadataKeys.size
        doc.documentInformation = PDDocumentInformation()
        val cat = doc.documentCatalog.cosObject
        for (k in listOf(COSName.METADATA, COSName.getPDFName("PieceInfo"))) if (cat.containsKey(k)) { cat.removeItem(k); n++ }
        for (page in doc.pages) {
            val d = page.cosObject
            for (k in listOf(COSName.METADATA, COSName.getPDFName("PieceInfo"), COSName.getPDFName("Thumb"))) if (d.containsKey(k)) { d.removeItem(k); n++ }
            runCatching {
                val res = page.resources ?: return@runCatching
                for (name in res.xObjectNames) {
                    val xo = res.getXObject(name) ?: continue
                    val s = xo.cosObject
                    if (s.containsKey(COSName.METADATA)) { s.removeItem(COSName.METADATA); n++ }
                }
            }
        }
        // Remove the trailer's document ID too? It identifies the file revision; PDFBox regenerates it on save.
        return n
    }
}
