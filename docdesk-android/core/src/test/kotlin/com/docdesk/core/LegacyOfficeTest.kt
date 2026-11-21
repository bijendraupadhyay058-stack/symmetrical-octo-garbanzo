package com.docdesk.core

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Uses .xls/.doc made by LibreOffice from the .xlsx/.docx samples (see samples/make_samples.py). */
class LegacyOfficeTest {
    private val dir = File("../samples/out")

    @Test fun rk() {
        assertEquals(1.0, XlsReader.rk(0x3FF00000), 0.0)   // double 1.0 high bits
        assertEquals(5.0, XlsReader.rk((5 shl 2) or 2), 0.0) // integer 5
        assertEquals(1.23, XlsReader.rk((123 shl 2) or 3), 1e-9) // integer 123 / 100
    }

    @Test fun xls() {
        val f = File(dir, "workbook_multi_sheet.xls"); assumeTrue(f.exists())
        val wb = XlsReader.read(f.inputStream())
        assertEquals(listOf("Ledger", "Summary", "Wide", "Hidden notes"), wb.sheets.map { it.name })
        val l = wb.sheets[0]
        assertEquals("General Ledger - FY 2024-25", l.cells[0]!![0]!!.display)
        assertTrue(l.cells[0]!![0]!!.bold)
        assertEquals("05-04-2024", l.cells[3]!![0]!!.display)
        assertEquals("4,32,438.24", l.cells[3]!![4]!!.display)
        assertEquals("(1,830,000.00)", wb.sheets[1].cells[2]!![1]!!.display)
        assertEquals("23.5%", wb.sheets[1].cells[7]!![1]!!.display)
        assertTrue(wb.sheets[3].hidden)
        assertEquals(1, l.merges.size)
        assertEquals(30, wb.sheets[2].maxCol + 1)
    }

    @Test fun doc() {
        val f = File(dir, "word_tables_images.doc"); assumeTrue(f.exists())
        val d = DocReader.read(f.inputStream())
        val paras = d.blocks.filterIsInstance<DocBlock.Paragraph>().map { it.text }
        assertTrue(paras.contains("Engagement Letter for Audit Services"))
        assertTrue(paras.any { it.startsWith("We are pleased to confirm") })
        assertTrue(paras.any { it.startsWith("यह एक नमूना") })
        val t = d.blocks.filterIsInstance<DocBlock.Table>().single()
        assertEquals(4, t.rows.size)
        assertEquals("Statutory audit", (t.rows[1][0].blocks[0] as DocBlock.Paragraph).text)
        assertEquals("1,50,000.00", (t.rows[1][1].blocks[0] as DocBlock.Paragraph).text)
        // Page breaks stored as a paragraph option are not read (text-only reader); hard breaks are.
        assertTrue(DocReader.toModel("One\rTwo\u000CThree\r").blocks.any { it is DocBlock.PageBreak })
        assertEquals(1, DocReader.toModel("Head\rA\u0007B\u0007\u0007C\u0007D\u0007\u0007After\r").blocks.count { it is DocBlock.Table })
    }
}
