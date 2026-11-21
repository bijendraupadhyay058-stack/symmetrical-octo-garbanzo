package com.docdesk.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OoxmlRoundTripTest {
    @Test fun xlsxRoundTrip() {
        val sheets = listOf(
            XSheet("Tables", listOf(
                listOf(XStyledCell(XCell.Text("Date"), bold = true), XStyledCell(XCell.Text("Amount"), bold = true), XStyledCell(XCell.Text("Ref"), bold = true)),
                listOf(XStyledCell(XCell.Date(45747)), XStyledCell(XCell.Number(BigDecimal("123456.78"), ExcelExport.INDIAN_FORMAT)), XStyledCell(XCell.Text("000123"))),
                listOf(XStyledCell(XCell.Blank), XStyledCell(XCell.Number(BigDecimal("-50.00"), "#,##0.00;(#,##0.00)"), highlight = true), XStyledCell(XCell.Text("a & <b>"))),
            ), listOf(12.0, 14.0, 10.0), freezeTopRow = true),
            XSheet("Tables", listOf(listOf(XStyledCell(XCell.Text("dup name"))))),
        )
        val out = ByteArrayOutputStream()
        XlsxWriter.write(sheets, out)
        val wb = XlsxReader.read(ByteArrayInputStream(out.toByteArray()))
        assertEquals(listOf("Tables", "Tables (2)"), wb.sheets.map { it.name })
        val s = wb.sheets[0]
        assertEquals("31-03-2025", s.cells[1]!![0]!!.display)
        assertEquals("1,23,456.78", s.cells[1]!![1]!!.display)
        assertEquals("000123", s.cells[1]!![2]!!.display)
        assertEquals("(50.00)", s.cells[2]!![1]!!.display)
        assertEquals("a & <b>", s.cells[2]!![2]!!.display)
        assertTrue(s.cells[0]!![0]!!.bold)
        assertEquals("FFF2B3", s.cells[2]!![1]!!.fillHex)
    }

    @Test fun excelExportKeepsRawText() {
        val t = ExtractedTable(0, 0, 3, listOf(
            TableRow(listOf(TableCell("Date"), TableCell("Particulars"), TableCell("Amount")), 0, isHeader = true),
            TableRow(listOf(TableCell("01/04/2024"), TableCell("Fees"), TableCell("(1,500.00)")), 0),
            TableRow(listOf(TableCell("31/02/2024", flags = setOf(CellFlag.UNPARSED_VALUE)), TableCell("Bad date"), TableCell("12,000.00 Cr")), 0),
        ), listOf(ColumnType.DATE, ColumnType.TEXT, ColumnType.AMOUNT), TextSource.PDF_TEXT)
        val built = ExcelExport.build(listOf(t), ExcelExportOptions(), listOf("Pages processed" to "1 of 1"))
        assertEquals(listOf("Tables", "Source text", "Review"), built.sheets.map { it.name })
        val main = built.sheets[0].rows
        assertEquals(XCell.Number(BigDecimal("-1500.00"), "#,##0.00;(#,##0.00)"), main[1][2].cell)
        assertEquals(XCell.Text("31/02/2024"), main[2][0].cell) // invalid date kept as text
        assertTrue(main[2][0].highlight)
        assertEquals(XCell.Text("(1,500.00)"), built.sheets[1].rows[1][2].cell)
        assertEquals(1, built.flaggedCells)
        val out = ByteArrayOutputStream(); XlsxWriter.write(built.sheets, out)
        val wb = XlsxReader.read(ByteArrayInputStream(out.toByteArray()))
        assertEquals("12,000.00 Cr", wb.sheets[0].cells[2]!![2]!!.display)
    }

    @Test fun docxRoundTrip() {
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        val doc = DocDocument(listOf(
            DocBlock.Paragraph(listOf(DocRun("Annual Report")), headingLevel = 1),
            DocBlock.Paragraph(listOf(DocRun("Revenue grew "), DocRun("12%", bold = true), DocRun(" in FY 2024-25 – राजस्व", italic = true))),
            DocBlock.Paragraph(listOf(DocRun("First point")), listLabel = "•"),
            DocBlock.Paragraph(listOf(DocRun("Numbered")), listLabel = "1."),
            DocBlock.Table(listOf(
                listOf(DocBlock.Table.Cell(listOf(DocBlock.Paragraph(listOf(DocRun("Head", bold = true))))), DocBlock.Table.Cell(listOf(DocBlock.Paragraph(listOf(DocRun("Value")))))),
                listOf(DocBlock.Table.Cell(listOf(DocBlock.Paragraph(listOf(DocRun("A & B"))))), DocBlock.Table.Cell(listOf(DocBlock.Paragraph(listOf(DocRun("1,000.00")))))),
            )),
            DocBlock.Image(png, "png", 100f, 50f),
            DocBlock.PageBreak,
            DocBlock.Paragraph(listOf(DocRun("Page two\twith tab"))),
        ), header = listOf(DocBlock.Paragraph(listOf(DocRun("Company Ltd")))), footer = listOf(DocBlock.Paragraph(listOf(DocRun("Confidential")))))
        val out = ByteArrayOutputStream()
        DocxWriter.write(doc, out)
        val back = DocxReader.read(ByteArrayInputStream(out.toByteArray()))
        val paras = back.blocks.filterIsInstance<DocBlock.Paragraph>()
        assertEquals(1, paras[0].headingLevel)
        assertEquals("Revenue grew 12% in FY 2024-25 – राजस्व", paras[1].text)
        assertTrue(paras[1].runs.first { it.text == "12%" }.bold)
        assertEquals("•", paras[2].listLabel)
        assertTrue(paras[3].text.startsWith("1.\tNumbered"))
        val table = back.blocks.filterIsInstance<DocBlock.Table>().single()
        assertEquals("A & B", (table.rows[1][0].blocks[0] as DocBlock.Paragraph).text)
        assertEquals(1, back.blocks.filterIsInstance<DocBlock.Image>().size)
        assertTrue(back.blocks.any { it is DocBlock.PageBreak })
        assertEquals("Page two\twith tab", paras.last().text)
        assertEquals("Company Ltd", (back.header.single() as DocBlock.Paragraph).text)
        assertEquals("Confidential", (back.footer.single() as DocBlock.Paragraph).text)
    }

    @Test(expected = UnsupportedDocumentException::class) fun rejectsBinaryDoc() {
        // Old .doc/.xls files are OLE compound files, not zips.
        DocxReader.read(ByteArrayInputStream(byteArrayOf(0xD0.toByte(), 0xCF.toByte(), 0x11, 0xE0.toByte(), 0, 0, 0, 0)))
    }
}
