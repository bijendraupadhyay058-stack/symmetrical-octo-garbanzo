package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.zip.ZipInputStream

class XlsxTest {
    @Test fun writesNumericCellsAndAllParts() {
        val doc = ReportEngine(ReportInput(ReportType.CUSTOM, "Office", accounts = SampleScenario.accounts, categories = SampleScenario.categories,
            parties = emptyMap(), txns = SampleScenario.txns, range = DateRange(SampleScenario.d(1), SampleScenario.d(30)), generatedAt = "now")).build()
        val out = ByteArrayOutputStream()
        XlsxWriter.write(ReportExcel.sheets(doc, DateFormatOption.DD_MM_YYYY, "INR"), out)
        val entries = HashMap<String, String>()
        ZipInputStream(ByteArrayInputStream(out.toByteArray())).use { z ->
            while (true) { val e = z.nextEntry ?: break; entries[e.name] = z.readBytes().toString(Charsets.UTF_8) }
        }
        assertTrue(entries.containsKey("[Content_Types].xml"))
        assertTrue(entries.containsKey("xl/workbook.xml"))
        assertTrue(entries.containsKey("xl/styles.xml"))
        val last = entries.keys.filter { it.startsWith("xl/worksheets/") }.maxByOrNull { it.filter(Char::isDigit).toInt() }!!
        val tx = entries[last]!!
        assertTrue("amount stored as number", tx.contains("<v>15000.00</v>"))
        assertTrue("date stored as serial", tx.contains("<v>${SampleScenario.d(2).toEpochDay() + 25569}</v>"))
    }

    @Test fun helpers() {
        assertEquals("A", XlsxWriter.colName(0))
        assertEquals("Z", XlsxWriter.colName(25))
        assertEquals("AA", XlsxWriter.colName(26))
        assertEquals("a &amp; b &lt;c&gt;", XlsxWriter.esc("a & b <c>\u0001"))
        assertEquals("Daily  Report", XSheet.sanitize("Daily/ Report"))
    }
}
