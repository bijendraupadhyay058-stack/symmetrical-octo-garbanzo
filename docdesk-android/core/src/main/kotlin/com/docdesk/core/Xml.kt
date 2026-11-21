package com.docdesk.core

import java.io.ByteArrayInputStream
import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Document
import org.w3c.dom.Element
import org.w3c.dom.Node

internal object Xml {
    fun esc(s: String): String {
        val sb = StringBuilder(s.length + 8)
        for (ch in s) {
            when {
                ch == '&' -> sb.append("&amp;")
                ch == '<' -> sb.append("&lt;")
                ch == '>' -> sb.append("&gt;")
                ch == '"' -> sb.append("&quot;")
                // XML 1.0 forbids most control characters; drop them rather than corrupt the file.
                ch.code < 0x20 && ch != '\t' && ch != '\n' && ch != '\r' -> Unit
                ch == '￾' || ch == '￿' -> Unit
                else -> sb.append(ch)
            }
        }
        return sb.toString()
    }

    fun parse(bytes: ByteArray): Document {
        val f = DocumentBuilderFactory.newInstance()
        f.isNamespaceAware = true
        // Hardening: no DTDs or external entities in untrusted office files.
        runCatching { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
        runCatching { f.setFeature("http://xml.org/sax/features/external-general-entities", false) }
        runCatching { f.setFeature("http://xml.org/sax/features/external-parameter-entities", false) }
        f.isExpandEntityReferences = false
        return f.newDocumentBuilder().parse(ByteArrayInputStream(bytes))
    }

    fun Element.children(localName: String? = null): List<Element> {
        val out = ArrayList<Element>()
        var n: Node? = firstChild
        while (n != null) {
            if (n is Element && (localName == null || n.localName == localName)) out.add(n)
            n = n.nextSibling
        }
        return out
    }

    fun Element.child(localName: String): Element? {
        var n: Node? = firstChild
        while (n != null) {
            if (n is Element && n.localName == localName) return n
            n = n.nextSibling
        }
        return null
    }

    fun Element.descendants(localName: String): List<Element> {
        val nl = getElementsByTagNameNS("*", localName)
        return (0 until nl.length).map { nl.item(it) as Element }
    }

    /** Attribute by local name regardless of namespace prefix (w:val, r:id, ...). */
    fun Element.attr(localName: String): String? {
        val attrs = attributes
        for (i in 0 until attrs.length) {
            val a = attrs.item(i)
            if (a.localName == localName || a.nodeName == localName) return a.nodeValue
        }
        return null
    }
}
