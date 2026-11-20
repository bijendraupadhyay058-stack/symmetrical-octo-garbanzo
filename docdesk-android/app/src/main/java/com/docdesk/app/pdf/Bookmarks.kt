package com.docdesk.app.pdf

import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.outline.PDOutlineNode

data class Bookmark(val title: String, val level: Int, val page: Int?)

/** Reads the PDF's table of contents (outline / bookmarks). */
object Bookmarks {
    fun read(doc: PDDocument, max: Int = 1000): List<Bookmark> {
        val out = mutableListOf<Bookmark>()
        fun walk(node: PDOutlineNode, level: Int) {
            for (item in node.children()) {
                if (out.size >= max || level > 8) return
                val page = runCatching { item.findDestinationPage(doc)?.let { p -> doc.pages.indexOf(p).takeIf { it >= 0 } } }.getOrNull()
                out.add(Bookmark(item.title?.trim().orEmpty().ifEmpty { "(untitled)" }, level, page))
                walk(item, level + 1)
            }
        }
        doc.documentCatalog.documentOutline?.let { walk(it, 0) }
        return out
    }
}
