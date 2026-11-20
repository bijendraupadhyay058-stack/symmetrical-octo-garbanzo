package com.docdesk.core

import java.io.OutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.math.roundToInt

/** Writes a [DocDocument] as a .docx file that opens in Word, Google Docs and LibreOffice. */
object DocxWriter {
    private const val EMU_PER_PT = 12700
    private const val W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    fun write(doc: DocDocument, out: OutputStream) {
        val media = mutableListOf<Pair<String, ByteArray>>() // filename -> bytes
        val rels = mutableListOf<Triple<String, String, String>>() // id, type, target
        rels.add(Triple("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml"))
        rels.add(Triple("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering", "numbering.xml"))
        rels.add(Triple("rId3", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings", "settings.xml"))
        val ctx = Ctx(media, rels)

        val body = StringBuilder()
        for (b in doc.blocks) block(b, body, ctx, doc.page.contentWidth)
        val headerXml = if (doc.header.isNotEmpty()) part("hdr", doc.header, ctx, doc.page.contentWidth) else null
        val footerXml = if (doc.footer.isNotEmpty()) part("ftr", doc.footer, ctx, doc.page.contentWidth) else null
        var headerRel: String? = null
        var footerRel: String? = null
        if (headerXml != null) { headerRel = ctx.newRel("http://schemas.openxmlformats.org/officeDocument/2006/relationships/header", "header1.xml") }
        if (footerXml != null) { footerRel = ctx.newRel("http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer", "footer1.xml") }

        val p = doc.page
        val sect = buildString {
            append("<w:sectPr>")
            headerRel?.let { append("""<w:headerReference w:type="default" r:id="$it"/>""") }
            footerRel?.let { append("""<w:footerReference w:type="default" r:id="$it"/>""") }
            append("""<w:pgSz w:w="${tw(p.widthPt)}" w:h="${tw(p.heightPt)}"${if (p.widthPt > p.heightPt) " w:orient=\"landscape\"" else ""}/>""")
            append("""<w:pgMar w:top="${tw(p.marginTopPt)}" w:right="${tw(p.marginRightPt)}" w:bottom="${tw(p.marginBottomPt)}" w:left="${tw(p.marginLeftPt)}" w:header="360" w:footer="360" w:gutter="0"/>""")
            append("</w:sectPr>")
        }
        val documentXml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document ${NS}><w:body>$body$sect</w:body></w:document>"""

        ZipOutputStream(out).use { zip ->
            fun put(path: String, content: ByteArray) { zip.putNextEntry(ZipEntry(path)); zip.write(content); zip.closeEntry() }
            fun put(path: String, content: String) = put(path, content.toByteArray(Charsets.UTF_8))
            put("[Content_Types].xml", buildString {
                append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">""")
                append("""<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>""")
                append("""<Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/>""")
                append("""<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>""")
                append("""<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>""")
                append("""<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>""")
                append("""<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>""")
                if (headerXml != null) append("""<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>""")
                if (footerXml != null) append("""<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>""")
                append("</Types>")
            })
            put("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""")
            put("word/document.xml", documentXml)
            put("word/styles.xml", stylesXml(doc.defaultFontSizePt))
            put("word/numbering.xml", NUMBERING)
            put("word/settings.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="$W_NS"><w:defaultTabStop w:val="720"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>""")
            headerXml?.let { put("word/header1.xml", it) }
            footerXml?.let { put("word/footer1.xml", it) }
            put("word/_rels/document.xml.rels", buildString {
                append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">""")
                for ((id, type, target) in rels) append("""<Relationship Id="$id" Type="$type" Target="$target"/>""")
                append("</Relationships>")
            })
            for ((name, bytes) in media) put("word/media/$name", bytes)
        }
    }

    private const val NS = """xmlns:w="$W_NS" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture""""

    private class Ctx(val media: MutableList<Pair<String, ByteArray>>, val rels: MutableList<Triple<String, String, String>>) {
        var drawingId = 1
        fun newRel(type: String, target: String): String {
            val id = "rId${rels.size + 1}"
            rels.add(Triple(id, type, target)); return id
        }
    }

    private fun part(tag: String, blocks: List<DocBlock>, ctx: Ctx, width: Float): String {
        val sb = StringBuilder()
        blocks.forEach { block(it, sb, ctx, width) }
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:$tag $NS>$sb</w:$tag>"""
    }

    private fun tw(pt: Float) = (pt * 20).roundToInt()

    private fun block(b: DocBlock, sb: StringBuilder, ctx: Ctx, width: Float) {
        when (b) {
            is DocBlock.Paragraph -> paragraph(b, sb)
            is DocBlock.PageBreak -> sb.append("""<w:p><w:r><w:br w:type="page"/></w:r></w:p>""")
            is DocBlock.Image -> image(b, sb, ctx, width)
            is DocBlock.Table -> table(b, sb, ctx, width)
        }
    }

    private fun paragraph(p: DocBlock.Paragraph, sb: StringBuilder) {
        sb.append("<w:p><w:pPr>")
        when {
            p.headingLevel == -1 -> sb.append("""<w:pStyle w:val="Title"/>""")
            p.headingLevel in 1..6 -> sb.append("""<w:pStyle w:val="Heading${p.headingLevel}"/>""")
            p.listLabel != null -> sb.append("""<w:pStyle w:val="ListParagraph"/>""")
        }
        if (p.pageBreakBefore) sb.append("<w:pageBreakBefore/>")
        val bullet = p.listLabel != null && p.listLabel.length <= 2 && !p.listLabel.any(Char::isLetterOrDigit)
        if (bullet) sb.append("""<w:numPr><w:ilvl w:val="${p.listLevel.coerceIn(0, 2)}"/><w:numId w:val="1"/></w:numPr>""")
        sb.append("""<w:spacing w:before="${tw(p.spaceBeforePt)}" w:after="${tw(p.spaceAfterPt)}"/>""")
        if (!bullet && (p.indentLeftPt > 0 || p.firstLineIndentPt != 0f)) {
            sb.append("<w:ind w:left=\"${tw(p.indentLeftPt)}\"")
            if (p.firstLineIndentPt > 0) sb.append(" w:firstLine=\"${tw(p.firstLineIndentPt)}\"")
            if (p.firstLineIndentPt < 0) sb.append(" w:hanging=\"${tw(-p.firstLineIndentPt)}\"")
            sb.append("/>")
        }
        when (p.align) {
            Align.CENTER -> sb.append("""<w:jc w:val="center"/>""")
            Align.RIGHT -> sb.append("""<w:jc w:val="right"/>""")
            Align.JUSTIFY -> sb.append("""<w:jc w:val="both"/>""")
            Align.LEFT -> Unit
        }
        sb.append("</w:pPr>")
        // Numbered labels ("1.", "a)") are kept as literal text so numbering never drifts from the source.
        if (p.listLabel != null && !bullet) run(DocRun(p.listLabel + "\t"), sb)
        p.runs.forEach { run(it, sb) }
        sb.append("</w:p>")
    }

    private fun run(r: DocRun, sb: StringBuilder) {
        if (r.text.isEmpty()) return
        sb.append("<w:r>")
        val props = buildString {
            r.fontName?.let { append("""<w:rFonts w:ascii="${Xml.esc(it)}" w:hAnsi="${Xml.esc(it)}" w:cs="${Xml.esc(it)}"/>""") }
            if (r.bold) append("<w:b/><w:bCs/>")
            if (r.italic) append("<w:i/><w:iCs/>")
            if (r.strike) append("<w:strike/>")
            r.color?.let { append("""<w:color w:val="$it"/>""") }
            r.sizePt?.let { val hp = (it * 2).roundToInt().coerceIn(2, 3276); append("""<w:sz w:val="$hp"/><w:szCs w:val="$hp"/>""") }
            if (r.underline) append("""<w:u w:val="single"/>""")
        }
        if (props.isNotEmpty()) sb.append("<w:rPr>").append(props).append("</w:rPr>")
        // Tabs and line breaks become their WordprocessingML elements.
        val parts = r.text.split('\n')
        parts.forEachIndexed { i, line ->
            if (i > 0) sb.append("<w:br/>")
            val tabs = line.split('\t')
            tabs.forEachIndexed { j, t ->
                if (j > 0) sb.append("<w:tab/>")
                if (t.isNotEmpty()) sb.append("""<w:t xml:space="preserve">""").append(Xml.esc(t)).append("</w:t>")
            }
        }
        sb.append("</w:r>")
    }

    private fun image(img: DocBlock.Image, sb: StringBuilder, ctx: Ctx, maxWidth: Float) {
        val ext = if (img.format == "png") "png" else "jpeg"
        val name = "image${ctx.media.size + 1}.$ext"
        ctx.media.add(name to img.bytes)
        val rid = ctx.newRel("http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "media/$name")
        val scale = if (img.widthPt > maxWidth) maxWidth / img.widthPt else 1f
        val cx = (img.widthPt * scale * EMU_PER_PT).roundToInt().coerceAtLeast(1)
        val cy = (img.heightPt * scale * EMU_PER_PT).roundToInt().coerceAtLeast(1)
        val id = ctx.drawingId++
        sb.append("<w:p>")
        if (img.align != Align.LEFT) sb.append("""<w:pPr><w:jc w:val="${if (img.align == Align.CENTER) "center" else "right"}"/></w:pPr>""")
        sb.append("""<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="$cx" cy="$cy"/><wp:docPr id="$id" name="Picture $id"/>""")
        sb.append("""<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="$id" name="$name"/><pic:cNvPicPr/></pic:nvPicPr>""")
        sb.append("""<pic:blipFill><a:blip r:embed="$rid"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>""")
        sb.append("""<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="$cx" cy="$cy"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>""")
    }

    private fun table(t: DocBlock.Table, sb: StringBuilder, ctx: Ctx, width: Float) {
        val cols = t.rows.maxOfOrNull { r -> r.sumOf { it.colSpan } } ?: return
        if (cols == 0) return
        val rel = if (t.columnWidths.size == cols && t.columnWidths.sum() > 0) t.columnWidths else List(cols) { 1f }
        val total = rel.sum()
        val widthsTw = rel.map { (it / total * width * 20).roundToInt().coerceAtLeast(200) }
        sb.append("<w:tbl><w:tblPr>")
        if (t.bordered) sb.append("""<w:tblStyle w:val="TableGrid"/>""")
        sb.append("""<w:tblW w:w="${widthsTw.sum()}" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>""")
        widthsTw.forEach { sb.append("""<w:gridCol w:w="$it"/>""") }
        sb.append("</w:tblGrid>")
        for (row in t.rows) {
            sb.append("<w:tr>")
            var col = 0
            for (cell in row) {
                val span = cell.colSpan.coerceAtLeast(1)
                val w = widthsTw.subList(col.coerceAtMost(cols - 1), (col + span).coerceAtMost(cols)).sum()
                col += span
                sb.append("""<w:tc><w:tcPr><w:tcW w:w="$w" w:type="dxa"/>""")
                if (span > 1) sb.append("""<w:gridSpan w:val="$span"/>""")
                cell.shadeHex?.let { sb.append("""<w:shd w:val="clear" w:color="auto" w:fill="$it"/>""") }
                sb.append("</w:tcPr>")
                if (cell.blocks.isEmpty()) sb.append("<w:p/>")
                cell.blocks.forEach { block(it, sb, ctx, w / 20f) }
                // A table cell must end with a paragraph.
                if (cell.blocks.lastOrNull() is DocBlock.Table) sb.append("<w:p/>")
                sb.append("</w:tc>")
            }
            // Pad short rows so Word does not complain about a ragged grid.
            while (col < cols) { sb.append("""<w:tc><w:tcPr><w:tcW w:w="${widthsTw[col]}" w:type="dxa"/></w:tcPr><w:p/></w:tc>"""); col++ }
            sb.append("</w:tr>")
        }
        sb.append("</w:tbl><w:p/>")
    }

    private fun stylesXml(defaultSize: Float): String {
        val hp = (defaultSize * 2).roundToInt()
        fun heading(n: Int, size: Int) = """<w:style w:type="paragraph" w:styleId="Heading$n"><w:name w:val="heading $n"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="${n - 1}"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val="$size"/><w:szCs w:val="$size"/></w:rPr></w:style>"""
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="$W_NS">""" +
            """<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Mangal"/><w:sz w:val="$hp"/><w:szCs w:val="$hp"/><w:lang w:val="en-IN" w:bidi="hi-IN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>""" +
            """<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>""" +
            """<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>""" +
            heading(1, 32) + heading(2, 28) + heading(3, 26) + heading(4, 24) + heading(5, 22) + heading(6, 22) +
            """<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:ind w:left="720"/></w:pPr></w:style>""" +
            """<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>""" +
            """<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:tblBorders></w:tblPr></w:style>""" +
            "</w:styles>"
    }

    private const val NUMBERING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="$W_NS"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl><w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="◦"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr></w:lvl><w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="▪"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="2160" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>"""
}
