package com.docdesk.core

import java.io.InputStream
import java.util.zip.ZipInputStream

class UnsupportedDocumentException(message: String) : Exception(message)

/** Reads the parts of an OOXML zip package with limits that protect against zip bombs. */
class OoxmlPackage private constructor(val parts: Map<String, ByteArray>) {

    operator fun get(path: String): ByteArray? = parts[path.removePrefix("/")]

    /** Relationship id -> target path (resolved relative to [partPath]'s folder). */
    fun relationships(partPath: String): Map<String, String> {
        val folder = partPath.substringBeforeLast('/', "")
        val relsPath = (if (folder.isEmpty()) "" else "$folder/") + "_rels/" + partPath.substringAfterLast('/') + ".rels"
        val bytes = this[relsPath] ?: return emptyMap()
        val doc = Xml.parse(bytes)
        val list = doc.getElementsByTagNameNS("*", "Relationship")
        val out = HashMap<String, String>()
        for (i in 0 until list.length) {
            val e = list.item(i) as org.w3c.dom.Element
            if (e.getAttribute("TargetMode") == "External") continue
            val target = e.getAttribute("Target")
            out[e.getAttribute("Id")] = resolve(folder, target)
        }
        return out
    }

    companion object {
        private const val MAX_TOTAL = 400L * 1024 * 1024
        private const val MAX_ENTRY = 150L * 1024 * 1024

        fun read(input: InputStream): OoxmlPackage {
            val parts = HashMap<String, ByteArray>()
            var total = 0L
            try {
                ZipInputStream(input).use { zip ->
                    var e = zip.nextEntry
                    while (e != null) {
                        if (!e.isDirectory) {
                            val buf = java.io.ByteArrayOutputStream()
                            val chunk = ByteArray(64 * 1024)
                            var entrySize = 0L
                            while (true) {
                                val n = zip.read(chunk)
                                if (n < 0) break
                                entrySize += n; total += n
                                if (entrySize > MAX_ENTRY || total > MAX_TOTAL) throw UnsupportedDocumentException("The file is too large to open on this device.")
                                buf.write(chunk, 0, n)
                            }
                            parts[e.name.removePrefix("/")] = buf.toByteArray()
                        }
                        e = zip.nextEntry
                    }
                }
            } catch (ex: java.util.zip.ZipException) {
                throw UnsupportedDocumentException("The file is damaged or is not an Office Open XML (.docx/.xlsx) file.")
            }
            if (parts.isEmpty() || "[Content_Types].xml" !in parts) {
                throw UnsupportedDocumentException("This is not a .docx or .xlsx file. Older .doc and .xls files are not supported yet – save them in the newer format first.")
            }
            return OoxmlPackage(parts)
        }

        fun resolve(folder: String, target: String): String {
            if (target.startsWith("/")) return target.removePrefix("/")
            val stack = if (folder.isEmpty()) ArrayDeque() else ArrayDeque(folder.split('/'))
            for (seg in target.split('/')) {
                when (seg) { ".." -> stack.removeLastOrNull(); ".", "" -> Unit; else -> stack.addLast(seg) }
            }
            return stack.joinToString("/")
        }
    }
}
