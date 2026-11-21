package com.docdesk.core

import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Reads Excel 97–2003 (.xls, BIFF8) workbooks – including files exported by Tally and older
 * accounting software – into the same [Workbook] model as [XlsxReader]. Values, cached formula
 * results, number formats, bold/italic, column widths, hidden rows/columns and merged cells are
 * read. Fills and borders are not (the PDF shows them plain).
 */
object XlsReader {
    private class Rec(val type: Int, val data: ByteArray)

    private data class Font(val bold: Boolean, val italic: Boolean, val size: Float)
    private data class Xf(val font: Int, val fmt: Int, val align: Align?, val wrap: Boolean)

    fun read(input: InputStream): Workbook {
        val bytes = input.readBytes()
        if (!CompoundFile.isCompound(bytes)) throw UnsupportedDocumentException("This is not an Excel 97–2003 (.xls) file. If it opens in Excel, save it again as .xlsx.")
        val cf = CompoundFile(bytes)
        val wb = cf.stream("Workbook") ?: run {
            if (cf.stream("Book") != null) throw UnsupportedDocumentException("This is a very old Excel 5/95 file. Open it in Excel or LibreOffice and save it as .xlsx.")
            throw UnsupportedDocumentException("This file does not contain an Excel workbook.")
        }
        return parse(wb)
    }

    private fun records(stream: ByteArray, from: Int): Sequence<Pair<Int, Rec>> = sequence {
        var p = from
        while (p + 4 <= stream.size) {
            val type = (stream[p].toInt() and 0xFF) or ((stream[p + 1].toInt() and 0xFF) shl 8)
            val len = (stream[p + 2].toInt() and 0xFF) or ((stream[p + 3].toInt() and 0xFF) shl 8)
            if (p + 4 + len > stream.size) break
            yield(p to Rec(type, stream.copyOfRange(p + 4, p + 4 + len)))
            p += 4 + len
        }
    }

    private fun ByteArray.u16(o: Int) = (this[o].toInt() and 0xFF) or ((this[o + 1].toInt() and 0xFF) shl 8)
    private fun ByteArray.i32(o: Int) = ByteBuffer.wrap(this, o, 4).order(ByteOrder.LITTLE_ENDIAN).int
    private fun ByteArray.f64(o: Int) = ByteBuffer.wrap(this, o, 8).order(ByteOrder.LITTLE_ENDIAN).double

    /** XLUnicodeString with 16-bit length (no continuation). */
    private fun str16(d: ByteArray, o: Int): String {
        val cch = d.u16(o); val flags = d[o + 2].toInt()
        return if (flags and 1 == 1) String(d, o + 3, (cch * 2).coerceAtMost(d.size - o - 3), Charsets.UTF_16LE)
        else String(d, o + 3, cch.coerceAtMost(d.size - o - 3), Charsets.ISO_8859_1)
    }

    private fun str8(d: ByteArray, o: Int): String {
        val cch = d[o].toInt() and 0xFF; val flags = d[o + 1].toInt()
        return if (flags and 1 == 1) String(d, o + 2, (cch * 2).coerceAtMost(d.size - o - 2), Charsets.UTF_16LE)
        else String(d, o + 2, cch.coerceAtMost(d.size - o - 2), Charsets.ISO_8859_1)
    }

    fun rk(v: Int): Double {
        val d = if (v and 2 != 0) (v shr 2).toDouble() else java.lang.Double.longBitsToDouble((v.toLong() and 0xFFFFFFFCL) shl 32)
        return if (v and 1 != 0) d / 100.0 else d
    }

    /** Shared strings may be split over CONTINUE records, even in the middle of a string. */
    private fun readSst(parts: List<ByteArray>): List<String> {
        val out = ArrayList<String>()
        var pi = 0; var pos = 8
        fun cur() = parts[pi]
        fun ensure(n: Int): Boolean { while (pi < parts.size && pos + n > cur().size) { if (pos < cur().size) return true; pi++; pos = 0 }; return pi < parts.size }
        val unique = parts[0].i32(4)
        repeat(unique.coerceAtMost(5_000_000)) {
            if (!ensure(3)) return out
            val cch = cur().u16(pos); var flags = cur()[pos + 2].toInt(); pos += 3
            var runs = 0; var ext = 0
            if (flags and 8 != 0) { ensure(2); runs = cur().u16(pos); pos += 2 }
            if (flags and 4 != 0) { ensure(4); ext = cur().i32(pos); pos += 4 }
            val sb = StringBuilder(cch)
            var remaining = cch
            while (remaining > 0) {
                if (pos >= cur().size) { pi++; if (pi >= parts.size) return out; pos = 0; flags = cur()[0].toInt(); pos = 1 } // continuation: new option byte
                val wide = flags and 1 == 1
                val avail = (cur().size - pos) / (if (wide) 2 else 1)
                val n = minOf(avail, remaining)
                sb.append(if (wide) String(cur(), pos, n * 2, Charsets.UTF_16LE) else String(cur(), pos, n, Charsets.ISO_8859_1))
                pos += n * (if (wide) 2 else 1); remaining -= n
            }
            var skip = runs * 4 + ext
            while (skip > 0 && pi < parts.size) { val n = minOf(skip, cur().size - pos); pos += n; skip -= n; if (skip > 0) { pi++; pos = 0 } }
            out.add(sb.toString())
        }
        return out
    }

    private fun parse(s: ByteArray): Workbook {
        val sheetsMeta = ArrayList<Triple<Int, String, Boolean>>() // offset, name, hidden
        val fonts = ArrayList<Font>(); val xfs = ArrayList<Xf>(); val formats = HashMap<Int, String>()
        var sst: List<String> = emptyList(); var date1904 = false
        val warnings = mutableListOf<String>()
        val globals = records(s, 0).toList()
        var i = 0
        while (i < globals.size) {
            val (_, r) = globals[i]
            when (r.type) {
                0x002F -> throw UnsupportedDocumentException("This .xls file is password-protected. Remove the password in Excel first.")
                0x0085 -> sheetsMeta.add(Triple(r.data.i32(0), str8(r.data, 6), (r.data[4].toInt() and 3) != 0 || (r.data[5].toInt() and 0xFF) != 0))
                0x0031 -> fonts.add(Font(r.data.u16(6) >= 700, r.data.u16(2) and 2 != 0, r.data.u16(0) / 20f))
                0x00E0 -> {
                    val al = r.data[6].toInt()
                    xfs.add(Xf(r.data.u16(0), r.data.u16(2), when (al and 7) { 1 -> Align.LEFT; 2 -> Align.CENTER; 3 -> Align.RIGHT; 5 -> Align.JUSTIFY; else -> null }, al and 8 != 0))
                }
                0x041E -> formats[r.data.u16(0)] = str16(r.data, 2)
                0x0022 -> date1904 = r.data.u16(0) == 1
                0x00FC -> {
                    val parts = mutableListOf(r.data)
                    while (i + 1 < globals.size && globals[i + 1].second.type == 0x003C) { i++; parts.add(globals[i].second.data) }
                    sst = readSst(parts)
                }
                0x000A -> break
            }
            i++
        }
        if (date1904) warnings.add("This workbook uses the 1904 date system; dates are converted accordingly.")
        fun font(idx: Int) = fonts.getOrNull(if (idx >= 4) idx - 1 else idx) // font index 4 does not exist in BIFF
        var formulasWithoutValue = 0
        val sheets = sheetsMeta.mapIndexed { si, (off, name, hidden) ->
            val cells = HashMap<Int, HashMap<Int, SheetCell>>()
            val colW = HashMap<Int, Double>(); val hiddenCols = HashSet<Int>(); val hiddenRows = HashSet<Int>(); val rowH = HashMap<Int, Float>()
            val merges = ArrayList<CellRange>()
            var defW = 8.43; var maxR = -1; var maxC = -1
            var pendingString: Pair<Int, Int>? = null
            var pendingXf = 0
            fun put(r: Int, c: Int, xfIdx: Int, display: String, numeric: Boolean) {
                val xf = xfs.getOrNull(xfIdx); val f = xf?.let { font(it.font) }
                if (display.isEmpty()) return
                cells.getOrPut(r) { HashMap() }[c] = SheetCell(display, numeric, f?.bold ?: false, f?.italic ?: false, f?.size ?: 10f, null, null, xf?.align, xf?.wrap ?: false)
                if (r > maxR) maxR = r; if (c > maxC) maxC = c
            }
            fun num(r: Int, c: Int, xfIdx: Int, v: Double) {
                val code = xfs.getOrNull(xfIdx)?.let { formats[it.fmt] ?: XlsxReader.BUILTIN[it.fmt] } ?: "General"
                put(r, c, xfIdx, NumberFormatter.format(v, code, date1904), true)
            }
            for ((_, r) in records(s, off)) {
                val d = r.data
                when (r.type) {
                    0x000A -> break
                    0x00FD -> put(d.u16(0), d.u16(2), d.u16(4), sst.getOrElse(d.i32(6)) { "" }, false)
                    0x0204 -> put(d.u16(0), d.u16(2), d.u16(4), str16(d, 6), false)
                    0x0203 -> num(d.u16(0), d.u16(2), d.u16(4), d.f64(6))
                    0x027E -> num(d.u16(0), d.u16(2), d.u16(4), rk(d.i32(6)))
                    0x00BD -> { val row = d.u16(0); val first = d.u16(2); val n = (d.size - 6) / 6; for (k in 0 until n) num(row, first + k, d.u16(4 + k * 6), rk(d.i32(6 + k * 6))) }
                    0x0205 -> put(d.u16(0), d.u16(2), d.u16(4), if (d[7].toInt() == 1) "#ERROR" else if (d[6].toInt() != 0) "TRUE" else "FALSE", false)
                    0x0006 -> {
                        val row = d.u16(0); val col = d.u16(2); val xf = d.u16(4)
                        if (d.u16(12) == 0xFFFF) when (d[6].toInt()) {
                            0 -> { pendingString = row to col; pendingXf = xf }
                            1 -> put(row, col, xf, if (d[8].toInt() != 0) "TRUE" else "FALSE", false)
                            2 -> put(row, col, xf, "#ERROR", false)
                            else -> Unit
                        } else num(row, col, xf, d.f64(6))
                    }
                    0x0207 -> pendingString?.let { (rr, cc) -> put(rr, cc, pendingXf, str16(d, 0), false); pendingString = null }
                    0x007D -> {
                        val first = d.u16(0); val last = d.u16(2).coerceAtMost(first + 512); val w = d.u16(4) / 256.0; val hid = d.u16(8) and 1 != 0
                        for (c in first..last) { colW[c] = w; if (hid) hiddenCols.add(c) }
                    }
                    0x0055 -> defW = d.u16(0).toDouble() + 0.71
                    0x0208 -> { val row = d.u16(0); val h = d.u16(6) and 0x7FFF; if (d.size >= 14 && (d.i32(12) and 0x20) != 0) hiddenRows.add(row); if (d.size >= 14 && (d.i32(12) and 0x40) != 0) rowH[row] = h / 20f }
                    0x00E5 -> { val n = d.u16(0); for (k in 0 until n) { val o = 2 + k * 8; if (o + 8 <= d.size) merges.add(CellRange(d.u16(o), d.u16(o + 4), d.u16(o + 2), d.u16(o + 6))) } }
                    0x00EC, 0x005D -> warnings.add("Not reproduced in the PDF: charts, pictures or shapes.")
                }
            }
            Sheet(name, cells, maxR, maxC, colW, defW, rowH, hiddenCols, hiddenRows, merges, null, hidden).also { @Suppress("UNUSED_EXPRESSION") si }
        }
        if (formulasWithoutValue > 0) warnings.add("$formulasWithoutValue formula cell(s) have no saved result.")
        warnings.add("Old .xls format: values, number formats, bold/italic, widths and merged cells are kept; cell colours and borders are not.")
        return Workbook(sheets, warnings.distinct())
    }
}
