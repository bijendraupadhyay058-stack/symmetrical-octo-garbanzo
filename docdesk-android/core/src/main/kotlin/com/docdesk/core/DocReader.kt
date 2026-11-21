package com.docdesk.core

import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Reads the text of Word 97–2003 (.doc) files: paragraphs, tables (cell and row marks), line and
 * page breaks, and field results. Character/paragraph formatting is not read, so headings,
 * fonts and images are not reproduced – the user is told.
 */
object DocReader {
    fun read(input: InputStream): DocDocument {
        val bytes = input.readBytes()
        if (!CompoundFile.isCompound(bytes)) throw UnsupportedDocumentException("This is not a Word 97–2003 (.doc) file. If it opens in Word, save it again as .docx.")
        val cf = CompoundFile(bytes)
        val wd = cf.stream("WordDocument") ?: throw UnsupportedDocumentException("This file does not contain a Word document.")
        val b = ByteBuffer.wrap(wd).order(ByteOrder.LITTLE_ENDIAN)
        if ((b.getShort(0).toInt() and 0xFFFF) != 0xA5EC) throw UnsupportedDocumentException("Unsupported Word file (older than Word 97).")
        val flags = b.getShort(0x0A).toInt()
        if (flags and 0x0100 != 0) throw UnsupportedDocumentException("This Word file is password-protected. Remove the password in Word first.")
        val table = cf.stream(if (flags and 0x0200 != 0) "1Table" else "0Table") ?: throw UnsupportedDocumentException("The Word file is damaged (table stream missing).")
        val ccpText = b.getInt(0x004C)
        val fcClx = b.getInt(0x01A2); val lcbClx = b.getInt(0x01A6)
        if (fcClx <= 0 || lcbClx <= 0 || fcClx + lcbClx > table.size) throw UnsupportedDocumentException("The Word file is damaged (text index missing).")
        val text = pieceText(wd, ByteBuffer.wrap(table, fcClx, lcbClx).order(ByteOrder.LITTLE_ENDIAN).slice().order(ByteOrder.LITTLE_ENDIAN), lcbClx, ccpText)
        return toModel(text)
    }

    private fun pieceText(wd: ByteArray, clx: ByteBuffer, len: Int, ccp: Int): String {
        var p = 0
        while (p < len && clx.get(p).toInt() == 1) p += 3 + (clx.getShort(p + 1).toInt() and 0xFFFF) // skip Prc
        if (p >= len || clx.get(p).toInt() != 2) throw UnsupportedDocumentException("The Word file's text index could not be read.")
        val lcb = clx.getInt(p + 1); val plc = p + 5
        val n = (lcb - 4) / 12
        val sb = StringBuilder()
        for (k in 0 until n) {
            val cpStart = clx.getInt(plc + k * 4); val cpEnd = clx.getInt(plc + (k + 1) * 4)
            val pcd = plc + (n + 1) * 4 + k * 8
            val fcRaw = clx.getInt(pcd + 2)
            val compressed = fcRaw and 0x40000000 != 0
            val count = (minOf(cpEnd, ccp) - cpStart).coerceAtLeast(0)
            if (count == 0) continue
            if (compressed) {
                val fc = (fcRaw and 0x3FFFFFFF) / 2
                for (i in 0 until count) { val idx = fc + i; if (idx < wd.size) sb.append(cp1252(wd[idx].toInt() and 0xFF)) }
            } else {
                val fc = fcRaw
                if (fc + count * 2 <= wd.size) sb.append(String(wd, fc, count * 2, Charsets.UTF_16LE))
            }
            if (cpEnd >= ccp) break
        }
        return sb.toString()
    }

    private fun cp1252(b: Int): Char = when (b) {
        0x80 -> '€'; 0x91 -> '‘'; 0x92 -> '’'; 0x93 -> '“'; 0x94 -> '”'; 0x95 -> '•'; 0x96 -> '–'; 0x97 -> '—'; 0x85 -> '…'; 0x99 -> '™'
        else -> b.toChar()
    }

    /** Converts Word's control characters into paragraphs, tables and page breaks. */
    fun toModel(raw: String): DocDocument {
        // Fields: \u0013 code \u0014 result \u0015 → keep result only.
        val clean = StringBuilder(); val inCode = ArrayList<Boolean>()
        for (ch in raw) {
            when (ch) {
                '\u0013' -> inCode.add(true)
                '\u0014' -> if (inCode.isNotEmpty()) inCode[inCode.lastIndex] = false
                '\u0015' -> if (inCode.isNotEmpty()) inCode.removeAt(inCode.lastIndex)
                else -> if (inCode.none { it }) clean.append(ch)
            }
        }
        val blocks = mutableListOf<DocBlock>()
        var rows = mutableListOf<List<DocBlock.Table.Cell>>()
        var row = mutableListOf<DocBlock.Table.Cell>()
        val buf = StringBuilder()
        var lastWasCell = false
        fun para(t: String) = DocBlock.Paragraph(listOf(DocRun(t)))
        fun flushTable() { if (rows.isNotEmpty()) { blocks.add(DocBlock.Table(rows.toList())); rows = mutableListOf() } }
        for (ch in clean) {
            when (ch) {
                // Paragraph mark: inside a table row it separates paragraphs of the next cell.
                '\r' -> {
                    if (row.isNotEmpty()) buf.append('\n')
                    else { flushTable(); blocks.add(para(buf.toString())); buf.clear() }
                    lastWasCell = false
                }
                // Cell mark; two in a row (empty second) = end of table row.
                '\u0007' -> {
                    if (lastWasCell && buf.isEmpty()) { rows.add(row.toList()); row = mutableListOf(); lastWasCell = false }
                    else { row.add(DocBlock.Table.Cell(buf.toString().trimEnd('\n').split('\n').map { para(it) })); buf.clear(); lastWasCell = true }
                }
                '\u000C' -> { flushTable(); if (buf.isNotEmpty()) { blocks.add(para(buf.toString())); buf.clear() }; blocks.add(DocBlock.PageBreak); lastWasCell = false }
                '\u000B' -> buf.append('\n')
                '\u001E' -> buf.append('-')
                '\u0001', '\u0008', '\u001F', '\u0000' -> Unit // pictures, drawings, optional hyphens
                else -> { buf.append(ch); lastWasCell = false }
            }
        }
        if (row.isNotEmpty()) rows.add(row)
        flushTable()
        if (buf.isNotEmpty()) blocks.add(para(buf.toString()))
        // Collapse runs of empty paragraphs left by pictures
        val compact = mutableListOf<DocBlock>()
        for (b in blocks) if (!(b is DocBlock.Paragraph && b.text.isBlank() && (compact.lastOrNull() as? DocBlock.Paragraph)?.text?.isBlank() == true)) compact.add(b)
        blocks.clear(); blocks.addAll(compact)
        // Drop trailing empty paragraphs
        while (blocks.lastOrNull().let { it is DocBlock.Paragraph && it.text.isBlank() }) blocks.removeAt(blocks.lastIndex)
        return DocDocument(blocks, unsupported = mapOf("Formatting of old .doc files (fonts, bold, headings, lists, images, page breaks set as paragraph options) – text only" to 1))
    }
}
