package com.docdesk.core

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Minimal reader for OLE2 / Compound File Binary containers (the format of .xls and .doc).
 * Read-only; validates chains to avoid loops on damaged files.
 */
class CompoundFile(private val data: ByteArray) {
    private val bb = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
    private val sectorSize: Int
    private val miniSectorSize: Int
    private val miniCutoff: Int
    private val fat: IntArray
    private val miniFat: IntArray
    private val entries: List<Entry>
    private val miniStream: ByteArray

    private data class Entry(val name: String, val type: Int, val start: Int, val size: Long)

    init {
        if (data.size < 512 || bb.getLong(0) != SIGNATURE) throw UnsupportedDocumentException("This is not an old-format Office file (.doc/.xls), or it is damaged.")
        sectorSize = 1 shl bb.getShort(30).toInt()
        miniSectorSize = 1 shl bb.getShort(32).toInt()
        if (sectorSize !in setOf(512, 4096)) throw UnsupportedDocumentException("Unsupported Office file structure.")
        val numFatSectors = bb.getInt(44)
        val dirStart = bb.getInt(48)
        miniCutoff = bb.getInt(56)
        val miniFatStart = bb.getInt(60)
        var difatStart = bb.getInt(68)
        val numDifat = bb.getInt(72)
        val fatSectors = ArrayList<Int>()
        for (i in 0 until 109) { val s = bb.getInt(76 + i * 4); if (s >= 0) fatSectors.add(s) }
        var guard = 0
        while (difatStart >= 0 && guard++ < numDifat + 1) {
            val off = offset(difatStart)
            val per = sectorSize / 4 - 1
            for (i in 0 until per) { val s = bb.getInt(off + i * 4); if (s >= 0) fatSectors.add(s) }
            difatStart = bb.getInt(off + per * 4)
        }
        val perSector = sectorSize / 4
        fat = IntArray(minOf(fatSectors.size, numFatSectors.coerceAtLeast(fatSectors.size)) * perSector)
        fatSectors.take(fat.size / perSector).forEachIndexed { k, s -> val off = offset(s); for (i in 0 until perSector) if (off + i * 4 + 4 <= data.size) fat[k * perSector + i] = bb.getInt(off + i * 4) }
        val dir = readChain(dirStart, -1)
        val list = ArrayList<Entry>()
        val db = ByteBuffer.wrap(dir).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until dir.size / 128) {
            val o = i * 128
            val nameLen = db.getShort(o + 64).toInt().coerceIn(0, 64)
            val name = String(dir, o, (nameLen - 2).coerceAtLeast(0), Charsets.UTF_16LE)
            list.add(Entry(name, dir[o + 66].toInt(), db.getInt(o + 116), db.getInt(o + 120).toLong() and 0xFFFFFFFFL))
        }
        entries = list
        miniFat = if (miniFatStart >= 0) readChain(miniFatStart, -1).let { b -> val m = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN); IntArray(b.size / 4) { m.getInt(it * 4) } } else IntArray(0)
        val root = entries.firstOrNull { it.type == 5 }
        miniStream = if (root != null && root.start >= 0) readChain(root.start, root.size) else ByteArray(0)
    }

    private fun offset(sector: Int) = (sector + 1) * sectorSize

    private fun readChain(start: Int, size: Long): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        var s = start; var n = 0
        while (s >= 0 && s < fat.size && n++ < fat.size) {
            val off = offset(s)
            if (off >= data.size) break
            out.write(data, off, minOf(sectorSize, data.size - off))
            s = fat[s]
        }
        val b = out.toByteArray()
        return if (size in 0 until b.size) b.copyOf(size.toInt()) else b
    }

    private fun readMini(start: Int, size: Long): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        var s = start; var n = 0
        while (s >= 0 && s < miniFat.size + 1 && n++ <= miniFat.size) {
            val off = s * miniSectorSize
            if (off >= miniStream.size) break
            out.write(miniStream, off, minOf(miniSectorSize, miniStream.size - off))
            s = if (s < miniFat.size) miniFat[s] else -2
        }
        return out.toByteArray().copyOf(size.toInt().coerceAtMost(out.size()))
    }

    fun streamNames(): List<String> = entries.filter { it.type == 2 }.map { it.name }

    fun stream(name: String): ByteArray? {
        val e = entries.firstOrNull { it.type == 2 && it.name.equals(name, ignoreCase = true) } ?: return null
        return if (e.size < miniCutoff) readMini(e.start, e.size) else readChain(e.start, e.size)
    }

    companion object {
        const val SIGNATURE = -0x1ee54e5e1fee3030L // D0 CF 11 E0 A1 B1 1A E1 read little-endian
        fun isCompound(bytes: ByteArray) = bytes.size >= 8 && ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).getLong(0) == SIGNATURE
    }
}
