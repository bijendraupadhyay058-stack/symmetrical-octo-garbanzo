package com.docdesk.app.pdf

import com.docdesk.core.Outline
import com.docdesk.core.OutlineEntry
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.destination.PDPageFitWidthDestination
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.outline.PDDocumentOutline
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.outline.PDOutlineItem
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.outline.PDOutlineNode
import com.tom_roush.pdfbox.pdmodel.PageMode

data class Bookmark(val title: String, val level: Int, val page: Int?)

/** Reads and writes the PDF's table of contents (outline / bookmarks). */
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

    /** Editable copy: bookmarks without a page point at the first page. */
    fun readEntries(doc: PDDocument): List<OutlineEntry> = Outline.normalize(read(doc).map { OutlineEntry(it.title, it.level, it.page ?: 0) })

    /** Replaces the whole outline. An empty list removes it. Pages outside the document are clamped. */
    fun write(doc: PDDocument, entries: List<OutlineEntry>, openPanel: Boolean = true) {
        val list = Outline.normalize(entries.filter { it.title.isNotBlank() })
        val catalog = doc.documentCatalog
        if (list.isEmpty()) {
            catalog.documentOutline = null
            if (catalog.pageMode == PageMode.USE_OUTLINES) catalog.pageMode = PageMode.USE_NONE
            return
        }
        val root = PDDocumentOutline()
        val stack = ArrayList<PDOutlineNode>().apply { add(root) }
        val last = doc.numberOfPages - 1
        for (e in list) {
            val item = PDOutlineItem()
            item.title = e.title
            item.destination = PDPageFitWidthDestination().apply { page = doc.getPage(e.page.coerceIn(0, last)); top = doc.getPage(e.page.coerceIn(0, last)).cropBox.upperRightY.toInt() }
            while (stack.size > e.level + 1) stack.removeAt(stack.size - 1)
            stack.last().addLast(item)
            stack.add(item)
        }
        // Show top level expanded, deeper levels collapsed.
        root.openNode()
        root.children().forEach { it.closeNode() }
        catalog.documentOutline = root
        if (openPanel) catalog.pageMode = PageMode.USE_OUTLINES
    }
}
