package com.docdesk.core

import com.docdesk.core.Xml.attr
import com.docdesk.core.Xml.child
import com.docdesk.core.Xml.children
import com.docdesk.core.Xml.descendants
import java.io.InputStream
import org.w3c.dom.Element

/**
 * Reads the parts of a .docx that can be reproduced faithfully on a phone: paragraphs, runs
 * (bold/italic/underline/strike/size/colour/font), headings, lists, tables, inline images,
 * page breaks, headers/footers and page size. Anything else is counted in [DocDocument.unsupported]
 * so the user can be warned.
 */
object DocxReader {

    private class Ctx(
        val pkg: OoxmlPackage,
        val rels: Map<String, String>,
        val styles: Map<String, StyleInfo>,
        val numbering: Map<String, Map<Int, String>>, // numId -> level -> numFmt
        val unsupported: MutableMap<String, Int> = LinkedHashMap(),
        val fonts: MutableSet<String> = LinkedHashSet(),
        val counters: MutableMap<String, IntArray> = HashMap(),
        var defaultSize: Float = 11f,
    ) {
        fun note(what: String) { unsupported[what] = (unsupported[what] ?: 0) + 1 }
    }

    private data class StyleInfo(val name: String, val basedOn: String?, val bold: Boolean?, val italic: Boolean?, val sizePt: Float?, val heading: Int, val align: Align?)

    fun read(input: InputStream): DocDocument {
        val pkg = OoxmlPackage.read(input)
        val docPath = "word/document.xml"
        val docBytes = pkg[docPath] ?: throw UnsupportedDocumentException("This file does not contain a Word document body.")
        val styles = readStyles(pkg)
        val ctx = Ctx(pkg, pkg.relationships(docPath), styles.first, readNumbering(pkg))
        ctx.defaultSize = styles.second
        val root = Xml.parse(docBytes).documentElement
        val body = root.child("body") ?: throw UnsupportedDocumentException("The Word document body is empty.")
        val blocks = readBlocks(body, ctx)

        var page = PageSetup.A4
        var header = emptyList<DocBlock>()
        var footer = emptyList<DocBlock>()
        body.child("sectPr")?.let { sect ->
            sect.child("pgSz")?.let { sz ->
                val w = sz.attr("w")?.toFloatOrNull()?.div(20f)
                val h = sz.attr("h")?.toFloatOrNull()?.div(20f)
                if (w != null && h != null) page = page.copy(widthPt = w, heightPt = h)
            }
            sect.child("pgMar")?.let { m ->
                fun v(n: String, d: Float) = m.attr(n)?.toFloatOrNull()?.div(20f) ?: d
                page = page.copy(marginTopPt = v("top", 72f), marginBottomPt = v("bottom", 72f), marginLeftPt = v("left", 72f), marginRightPt = v("right", 72f))
            }
            header = headerFooter(sect, "headerReference", ctx)
            footer = headerFooter(sect, "footerReference", ctx)
        }
        if (root.descendants("sectPr").size > 1) ctx.note("Multiple page sections (first section's page size used)")
        return DocDocument(blocks, page, header, footer, ctx.defaultSize, ctx.unsupported, ctx.fonts)
    }

    private fun headerFooter(sect: Element, tag: String, ctx: Ctx): List<DocBlock> {
        val ref = sect.children(tag).firstOrNull { (it.attr("type") ?: "default") == "default" } ?: return emptyList()
        val path = ctx.rels[ref.attr("id") ?: return emptyList()] ?: return emptyList()
        val bytes = ctx.pkg[path] ?: return emptyList()
        val sub = Ctx(ctx.pkg, ctx.pkg.relationships(path), ctx.styles, ctx.numbering, ctx.unsupported, ctx.fonts, HashMap(), ctx.defaultSize)
        return readBlocks(Xml.parse(bytes).documentElement, sub)
    }

    private fun readBlocks(container: Element, ctx: Ctx): List<DocBlock> {
        val out = mutableListOf<DocBlock>()
        for (el in container.children()) {
            when (el.localName) {
                "p" -> readParagraph(el, ctx, out)
                "tbl" -> out.add(readTable(el, ctx))
                "sdt" -> el.child("sdtContent")?.let { out.addAll(readBlocks(it, ctx)) }
                "sectPr", "bookmarkStart", "bookmarkEnd", "proofErr" -> Unit
                else -> ctx.note("Other content (${el.localName})")
            }
        }
        return out
    }

    private fun readParagraph(p: Element, ctx: Ctx, out: MutableList<DocBlock>) {
        val ppr = p.child("pPr")
        val styleId = ppr?.child("pStyle")?.attr("val")
        val style = styleId?.let { resolveStyle(it, ctx) }
        val heading = style?.heading ?: 0
        val align = when (ppr?.child("jc")?.attr("val")) {
            "center" -> Align.CENTER; "right", "end" -> Align.RIGHT; "both", "distribute" -> Align.JUSTIFY
            else -> style?.align ?: Align.LEFT
        }
        val ind = ppr?.child("ind")
        val indLeft = (ind?.attr("left") ?: ind?.attr("start"))?.toFloatOrNull()?.div(20f) ?: 0f
        val firstLine = ind?.attr("firstLine")?.toFloatOrNull()?.div(20f) ?: -(ind?.attr("hanging")?.toFloatOrNull()?.div(20f) ?: 0f)
        val spacing = ppr?.child("spacing")
        val before = spacing?.attr("before")?.toFloatOrNull()?.div(20f) ?: 0f
        val after = spacing?.attr("after")?.toFloatOrNull()?.div(20f) ?: 6f
        var pageBreakBefore = ppr?.child("pageBreakBefore") != null

        var listLabel: String? = null
        var listLevel = 0
        ppr?.child("numPr")?.let { np ->
            val numId = np.child("numId")?.attr("val")
            listLevel = np.child("ilvl")?.attr("val")?.toIntOrNull() ?: 0
            if (numId != null && numId != "0") listLabel = listLabel(numId, listLevel, ctx)
        }

        val runs = mutableListOf<DocRun>()
        val images = mutableListOf<DocBlock.Image>()
        fun collect(parent: Element) {
            for (child in parent.children()) {
                when (child.localName) {
                    "r" -> readRun(child, style, ctx, runs, images, onPageBreak = {
                        if (runs.isEmpty() && images.isEmpty()) pageBreakBefore = true
                        else { flush(out, runs, images, heading, align, listLabel, listLevel, indLeft, firstLine, before, after, pageBreakBefore); pageBreakBefore = true }
                    })
                    "hyperlink", "smartTag", "ins", "fldSimple" -> collect(child)
                    "sdt" -> child.child("sdtContent")?.let { collect(it) }
                    "oMath", "oMathPara" -> { ctx.note("Equations"); runs.add(DocRun("[equation]", italic = true)) }
                    "del" -> Unit // deleted tracked changes are not shown
                }
            }
        }
        collect(p)
        flush(out, runs, images, heading, align, listLabel, listLevel, indLeft, firstLine, before, after, pageBreakBefore)
    }

    private fun flush(
        out: MutableList<DocBlock>, runs: MutableList<DocRun>, images: MutableList<DocBlock.Image>, heading: Int, align: Align,
        listLabel: String?, listLevel: Int, indLeft: Float, firstLine: Float, before: Float, after: Float, pageBreakBefore: Boolean,
    ) {
        if (pageBreakBefore && runs.isEmpty() && images.isEmpty()) { out.add(DocBlock.PageBreak); return }
        if (pageBreakBefore) out.add(DocBlock.PageBreak)
        if (runs.isNotEmpty() || images.isEmpty()) {
            out.add(DocBlock.Paragraph(runs.toList(), heading, align, listLabel, listLevel, indLeft, firstLine, before, after))
        }
        images.forEach { out.add(it.copy(align = align)) }
        runs.clear(); images.clear()
    }

    private fun readRun(r: Element, style: StyleInfo?, ctx: Ctx, runs: MutableList<DocRun>, images: MutableList<DocBlock.Image>, onPageBreak: () -> Unit) {
        val rpr = r.child("rPr")
        fun flag(tag: String, fallback: Boolean?): Boolean {
            val e = rpr?.child(tag) ?: return fallback ?: false
            val v = e.attr("val")
            return v == null || (v != "0" && v != "false" && v != "none")
        }
        val runStyle = rpr?.child("rStyle")?.attr("val")?.let { resolveStyle(it, ctx) }
        val bold = flag("b", runStyle?.bold ?: style?.bold)
        val italic = flag("i", runStyle?.italic ?: style?.italic)
        val underline = rpr?.child("u")?.attr("val")?.let { it != "none" } ?: false
        val strike = flag("strike", false) || flag("dstrike", false)
        val size = rpr?.child("sz")?.attr("val")?.toFloatOrNull()?.div(2f) ?: runStyle?.sizePt ?: style?.sizePt
        val color = rpr?.child("color")?.attr("val")?.takeIf { it.length == 6 && it != "auto" }
        val font = rpr?.child("rFonts")?.let { it.attr("ascii") ?: it.attr("hAnsi") ?: it.attr("cs") }
        font?.let { ctx.fonts.add(it) }
        val vanish = rpr?.child("vanish") != null
        if (vanish) return

        val text = StringBuilder()
        fun emit() {
            if (text.isNotEmpty()) { runs.add(DocRun(text.toString(), bold, italic, underline, strike, size, color, font)); text.clear() }
        }
        for (c in r.children()) {
            when (c.localName) {
                "t" -> text.append(c.textContent)
                "tab", "ptab" -> text.append('\t')
                "br", "cr" -> if (c.attr("type") == "page") { emit(); onPageBreak() } else text.append('\n')
                "noBreakHyphen" -> text.append('-')
                "sym" -> text.append(c.attr("char")?.toIntOrNull(16)?.let { String(Character.toChars(if (it >= 0xF000) it - 0xF000 else it)) } ?: "")
                "drawing" -> { emit(); readDrawing(c, ctx)?.let { images.add(it) } }
                "pict", "object" -> { emit(); ctx.note("Legacy drawings or embedded objects") }
                "AlternateContent" -> { emit(); ctx.note("Text boxes, shapes or charts") }
                "footnoteReference", "endnoteReference" -> ctx.note("Footnotes/endnotes")
                "fldChar", "instrText" -> if (c.localName == "instrText" && c.textContent.contains("TOC")) ctx.note("Table of contents field (shown as last saved)")
            }
        }
        emit()
    }

    private fun readDrawing(d: Element, ctx: Ctx): DocBlock.Image? {
        if (d.descendants("chart").isNotEmpty()) { ctx.note("Charts"); return null }
        val blip = d.descendants("blip").firstOrNull()
        if (blip == null) { ctx.note("Text boxes, shapes or charts"); return null }
        if (d.child("anchor") != null) ctx.note("Floating images (placed inline instead)")
        val rid = blip.attr("embed") ?: return null
        val path = ctx.rels[rid] ?: return null
        val bytes = ctx.pkg[path] ?: return null
        val ext = d.descendants("extent").firstOrNull()
        val w = ext?.attr("cx")?.toFloatOrNull()?.div(12700f) ?: 200f
        val h = ext?.attr("cy")?.toFloatOrNull()?.div(12700f) ?: 150f
        val lower = path.lowercase()
        val format = when {
            lower.endsWith(".png") -> "png"
            lower.endsWith(".jpg") || lower.endsWith(".jpeg") -> "jpeg"
            else -> { ctx.note("Images in unsupported formats (EMF/WMF/SVG)"); return null }
        }
        return DocBlock.Image(bytes, format, w, h)
    }

    private fun readTable(tbl: Element, ctx: Ctx): DocBlock.Table {
        val grid = tbl.child("tblGrid")?.children("gridCol")?.map { it.attr("w")?.toFloatOrNull() ?: 1f } ?: emptyList()
        val borders = tbl.child("tblPr")?.let { pr ->
            val styleId = pr.child("tblStyle")?.attr("val")
            val b = pr.child("tblBorders")
            when {
                b != null -> b.children().any { it.attr("val") != "nil" && it.attr("val") != "none" }
                styleId != null -> styleId.contains("Grid", true) || styleId.contains("Table", true)
                else -> false
            }
        } ?: false
        val rows = tbl.children("tr").map { tr ->
            tr.children("tc").mapNotNull { tc ->
                val tcPr = tc.child("tcPr")
                val span = tcPr?.child("gridSpan")?.attr("val")?.toIntOrNull() ?: 1
                val vMerge = tcPr?.child("vMerge")
                val continued = vMerge != null && (vMerge.attr("val") ?: "continue") == "continue"
                val shade = tcPr?.child("shd")?.attr("fill")?.takeIf { it.length == 6 && it != "auto" }
                val blocks = if (continued) emptyList() else readBlocks(tc, ctx)
                DocBlock.Table.Cell(blocks, span, shade)
            }
        }
        if (tbl.descendants("vMerge").isNotEmpty()) ctx.note("Vertically merged table cells (shown as empty cells)")
        return DocBlock.Table(rows, grid, borders)
    }

    private fun listLabel(numId: String, level: Int, ctx: Ctx): String {
        val fmt = ctx.numbering[numId]?.get(level) ?: "bullet"
        if (fmt == "bullet" || fmt == "none") return "•"
        val counters = ctx.counters.getOrPut(numId) { IntArray(9) }
        counters[level]++
        for (l in level + 1 until 9) counters[l] = 0
        val n = counters[level]
        return when (fmt) {
            "lowerLetter" -> "${('a' + (n - 1) % 26)})"
            "upperLetter" -> "${('A' + (n - 1) % 26)}."
            "lowerRoman" -> roman(n).lowercase() + "."
            "upperRoman" -> roman(n) + "."
            else -> "$n."
        }
    }

    private fun roman(n: Int): String {
        val v = intArrayOf(1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1)
        val s = arrayOf("M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I")
        var x = n; val sb = StringBuilder()
        for (i in v.indices) while (x >= v[i]) { sb.append(s[i]); x -= v[i] }
        return sb.toString()
    }

    private fun resolveStyle(id: String, ctx: Ctx, depth: Int = 0): StyleInfo? {
        val s = ctx.styles[id] ?: return null
        if (s.basedOn == null || depth > 8) return s
        val parent = resolveStyle(s.basedOn, ctx, depth + 1) ?: return s
        return StyleInfo(s.name, null, s.bold ?: parent.bold, s.italic ?: parent.italic, s.sizePt ?: parent.sizePt, if (s.heading != 0) s.heading else parent.heading, s.align ?: parent.align)
    }

    private fun readStyles(pkg: OoxmlPackage): Pair<Map<String, StyleInfo>, Float> {
        val bytes = pkg["word/styles.xml"] ?: return emptyMap<String, StyleInfo>() to 11f
        val root = Xml.parse(bytes).documentElement
        val defaultSize = root.child("docDefaults")?.child("rPrDefault")?.child("rPr")?.child("sz")?.attr("val")?.toFloatOrNull()?.div(2f) ?: 11f
        val map = HashMap<String, StyleInfo>()
        for (s in root.children("style")) {
            val id = s.attr("styleId") ?: continue
            val name = s.child("name")?.attr("val") ?: id
            val rpr = s.child("rPr")
            fun flag(tag: String): Boolean? = rpr?.child(tag)?.let { val v = it.attr("val"); v == null || (v != "0" && v != "false") }
            val outline = s.child("pPr")?.child("outlineLvl")?.attr("val")?.toIntOrNull()
            val heading = when {
                name.equals("title", true) -> -1
                name.lowercase().startsWith("heading ") -> name.substringAfter(' ').toIntOrNull()?.coerceIn(1, 6) ?: 0
                outline != null && outline in 0..5 -> outline + 1
                else -> 0
            }
            val align = when (s.child("pPr")?.child("jc")?.attr("val")) { "center" -> Align.CENTER; "right" -> Align.RIGHT; "both" -> Align.JUSTIFY; else -> null }
            map[id] = StyleInfo(name, s.child("basedOn")?.attr("val"), flag("b"), flag("i"), rpr?.child("sz")?.attr("val")?.toFloatOrNull()?.div(2f), heading, align)
        }
        return map to defaultSize
    }

    private fun readNumbering(pkg: OoxmlPackage): Map<String, Map<Int, String>> {
        val bytes = pkg["word/numbering.xml"] ?: return emptyMap()
        val root = Xml.parse(bytes).documentElement
        val abstract = root.children("abstractNum").associate { a ->
            a.attr("abstractNumId") to a.children("lvl").associate { l -> (l.attr("ilvl")?.toIntOrNull() ?: 0) to (l.child("numFmt")?.attr("val") ?: "decimal") }
        }
        val out = HashMap<String, Map<Int, String>>()
        for (n in root.children("num")) {
            val id = n.attr("numId") ?: continue
            out[id] = abstract[n.child("abstractNumId")?.attr("val")] ?: emptyMap()
        }
        return out
    }
}
