package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.time.LocalDate
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class StatementFilesTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)

    @Test fun xlsxWithDateCellsAndNumbers() {
        val sheet = XSheet("Statement").apply {
            row(XCell.Str("Account: 0001234"))
            row(XCell.Blank)
            row(XCell.Str("Txn Date"), XCell.Str("Narration"), XCell.Str("Withdrawal"), XCell.Str("Deposit"), XCell.Str("Balance"))
            row(XCell.Date(d(5, 2)), XCell.Str("NEFT ABC ENTERPRISES"), XCell.Blank, XCell.Money(2_500_000), XCell.Money(7_500_000))
            row(XCell.Date(d(5, 31)), XCell.Str("SMS CHARGES"), XCell.Money(1_770), XCell.Blank, XCell.Money(7_498_230))
        }
        val bytes = ByteArrayOutputStream().also { XlsxWriter.write(listOf(sheet), it) }.toByteArray()
        val r = StatementFiles.parse(bytes)
        assertEquals(listOf(d(5, 2), d(5, 31)), r.lines.map { it.date })
        assertEquals(listOf(2_500_000L, -1_770L), r.lines.map { it.amount })
        assertEquals(7_498_230L, r.closingBalance)
        assertEquals(5, r.lines.last().row)                                   // Excel row number
    }

    /** The way banks' Excel files usually look inside: shared strings, a custom date format, skipped cells and rows. */
    @Test fun xlsxWithSharedStringsAndCustomDateFormat() {
        fun zip(vararg files: Pair<String, String>) = ByteArrayOutputStream().also { o ->
            ZipOutputStream(o).use { z -> files.forEach { (n, b) -> z.putNextEntry(ZipEntry(n)); z.write(b.toByteArray()); z.closeEntry() } }
        }.toByteArray()
        val bytes = zip(
            "xl/workbook.xml" to """<workbook xmlns:r="r"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId7"/></sheets></workbook>""",
            "xl/_rels/workbook.xml.rels" to """<Relationships><Relationship Id="rId7" Target="worksheets/data.xml"/></Relationships>""",
            "xl/sharedStrings.xml" to """<sst><si><t>Value Date</t></si><si><t>Particulars</t></si><si><r><t>Amount</t></r><r><t xml:space="preserve"> (INR)</t></r></si><si><t>Dr/Cr</t></si><si><t>UPI/ACME/PAY</t></si><si><t>DR</t></si></sst>""",
            "xl/styles.xml" to """<styleSheet><numFmts count="1"><numFmt numFmtId="164" formatCode="dd\-mmm\-yyyy"/></numFmts><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs></styleSheet>""",
            "xl/worksheets/data.xml" to """<worksheet><sheetData>
                <row r="2"><c r="A2" t="s"><v>0</v></c><c r="C2" t="s"><v>1</v></c><c r="D2" t="s"><v>2</v></c><c r="E2" t="s"><v>3</v></c></row>
                <row r="3"><c r="A3" s="1"><v>46143</v></c><c r="C3" t="s"><v>4</v></c><c r="D3"><v>1200.5</v></c><c r="E3" t="s"><v>5</v></c></row>
                </sheetData></worksheet>""",
        )
        val rows = StatementFiles.rows(bytes)
        assertEquals(listOf("Value Date", "", "Particulars", "Amount (INR)", "Dr/Cr"), rows[1])
        assertEquals("01/05/2026", rows[2][0])                                // serial 46143 with a custom date format
        val r = StatementFiles.parse(bytes)
        assertEquals(StatementLine(3, d(5, 1), "UPI/ACME/PAY", "", -120_050, null), r.lines.single())
    }

    @Test fun htmlSavedAsXls() {
        val html = """<html><body><table>
            <tr><td>Statement of account</td></tr>
            <tr><th>Date</th><th>Description</th><th>Chq/Ref No</th><th>Debit</th><th>Credit</th><th>Balance</th></tr>
            <tr><td>03/05/2026</td><td>INTEREST&nbsp;CREDIT<br/>Q1</td><td>&#8212;</td><td></td><td>1,250.00</td><td>10,250.00</td></tr>
            <tr><td>04/05/2026</td><td>R&amp;D SUPPLIES</td><td>CHQ 44</td><td>250.00</td><td></td><td>10,000.00</td></tr>
            </table></body></html>"""
        val r = StatementFiles.parse(html.toByteArray(Charsets.UTF_8))
        assertEquals(listOf("INTEREST CREDIT Q1", "R&D SUPPLIES"), r.lines.map { it.description })
        assertEquals(listOf(125_000L, -25_000L), r.lines.map { it.amount })
        assertEquals("CHQ 44", r.lines[1].reference)
        assertEquals(1_000_000L, r.closingBalance)
    }

    @Test fun textEncodingsAndOldExcel() {
        val tsv = "Date\tNarration\tAmount\n05/05/2026\tCAFÉ ₹ BILL\t-99.00\n"
        val utf16 = byteArrayOf(0xFF.toByte(), 0xFE.toByte()) + tsv.toByteArray(Charsets.UTF_16LE)
        assertEquals("CAFÉ ₹ BILL", StatementFiles.parse(utf16).lines.single().description)
        val cp1252 = "Date,Narration,Amount\n05/05/2026,CAFÉ,-99.00\n".toByteArray(charset("windows-1252"))
        assertEquals("CAFÉ", StatementFiles.parse(cp1252).lines.single().description)
        val ole = byteArrayOf(0xD0.toByte(), 0xCF.toByte(), 0x11, 0xE0.toByte(), 0xA1.toByte(), 0xB1.toByte(), 0x1A, 0xE1.toByte())
        val e = runCatching { StatementFiles.parse(ole) }.exceptionOrNull()
        assertTrue(e is StatementImport.FormatException && e.message!!.contains(".xlsx"))
        assertEquals(LocalDate.of(2026, 5, 1), XlsxReader.serialToDate(46143.75))
        assertEquals(27, XlsxReader.colIndex("AB12"))
    }

    @Test fun categoryRuleKeys() {
        assertEquals("SMS CHARGES INCL", CategoryRules.key("SMS CHARGES INCL GST 0525"))
        assertEquals("UPI ACME TRADERS", CategoryRules.key("UPI/ACME TRADERS/4521987/PAYMENT"))
        assertEquals("NEFT ABC ENTERPRISES", CategoryRules.key("NEFT-ABC ENTERPRISES, MUMBAI"))
        assertEquals("", CategoryRules.key("12345 / 678"))
        val rules = listOf(CategoryRule(1, "SMS CHARGES INCL", 40))
        assertEquals(40L, CategoryRules.find(rules, "sms charges incl gst 0625")?.categoryId)
        assertNull(CategoryRules.find(rules, "SMS ALERT CHARGES"))
        assertNull(CategoryRules.find(rules, "0525"))
    }
}
