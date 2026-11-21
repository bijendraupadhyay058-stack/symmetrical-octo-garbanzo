package com.docdesk.core

import java.math.BigDecimal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNotNull
import org.junit.Test

class TableExtractorTest {
    /** Lays words out like a PDF would: each entry is (text, x). Font size 9, char width ~5. */
    private fun line(y: Float, vararg cells: Pair<String, Float>, conf: Float? = null): List<TextWord> =
        cells.flatMap { (text, x) ->
            var cx = x
            text.split(" ").map { w -> TextWord(w, cx, y, w.length * 5f, 9f, 9f, confidence = conf).also { cx += w.length * 5f + 2.5f } }
        }

    private fun statement(): PageText {
        val words = mutableListOf<TextWord>()
        words += line(40f, "ABC BANK - Statement of Account" to 150f)
        words += line(80f, "Date" to 40f, "Narration" to 110f, "Chq/Ref No" to 300f, "Withdrawal" to 380f, "Deposit" to 450f, "Balance" to 520f)
        words += line(100f, "01/04/2024" to 40f, "Opening balance" to 110f, "50,000.00" to 520f)
        words += line(115f, "02/04/2024" to 40f, "UPI/ramesh traders" to 110f, "000412345678" to 300f, "1,250.00" to 380f, "48,750.00" to 520f)
        words += line(127f, "payment for invoice 77" to 110f) // wrapped description
        words += line(142f, "05/04/2024" to 40f, "NEFT salary credit" to 110f, "N123456" to 300f, "1,00,000.00" to 450f, "1,48,750.00" to 520f)
        words += line(157f, "07/04/2024" to 40f, "ATM withdrawal" to 110f, "2,000.00" to 380f, "1,46,750.00" to 520f)
        words += line(200f, "Closing balance 1,46,750.00" to 40f)
        return PageText(0, 612f, 792f, words, TextSource.PDF_TEXT)
    }

    @Test fun bankStatement() {
        val tables = TableExtractor.extract(statement())
        assertEquals(1, tables.size)
        val t = tables[0]
        assertEquals(6, t.columnCount)
        val header = assertNotNull(t.header).let { t.header!! }
        assertEquals(listOf("Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Balance"), header.cells.map { it.raw })
        assertEquals(ColumnType.DATE, t.columnTypes[0])
        assertEquals(ColumnType.AMOUNT, t.columnTypes[3])
        assertEquals(ColumnType.AMOUNT, t.columnTypes[5])
        assertEquals(ColumnType.TEXT, t.columnTypes[2])
        val body = t.bodyRows
        assertEquals(4, body.size) // wrapped line merged, not a separate transaction
        assertEquals("UPI/ramesh traders payment for invoice 77", body[1].cells[1].raw)
        assertTrue(CellFlag.MERGED_WRAPPED_TEXT in body[1].cells[1].flags)
        assertEquals("000412345678", body[1].cells[2].raw) // reference kept verbatim
        assertEquals("", body[0].cells[3].raw)              // blank stays blank
    }

    @Test fun financialChecks() {
        val t = TableExtractor.extract(statement())[0]
        val r = FinancialChecks.run(t, NumberStyle.INDIAN, listOf("Opening balance 50,000.00", "Closing balance 1,46,750.00"))
        assertEquals(4, r.transactionRows)
        assertEquals(BigDecimal("3250.00"), r.totalDebit)
        assertEquals(BigDecimal("100000.00"), r.totalCredit)
        assertEquals(3, r.balanceRowsChecked)
        assertEquals(emptyList<Int>(), r.balanceMismatches)
        assertTrue(r.notes.any { it.contains("matches the closing balance") })
    }

    @Test fun balanceMismatchIsReported() {
        val page = statement()
        val tampered = page.copy(words = page.words.map { if (it.text == "1,46,750.00" && it.y == 157f) it.copy(text = "1,46,705.00") else it })
        val t = TableExtractor.extract(tampered)[0]
        val r = FinancialChecks.run(t, NumberStyle.INDIAN)
        assertEquals(listOf(4), r.balanceMismatches)
    }

    @Test fun lowConfidenceOcrIsFlagged() {
        val words = line(80f, "Item" to 40f, "Qty" to 200f, "Amount" to 300f) +
            line(100f, "Paper" to 40f, "2" to 200f, "1,200.00" to 300f, conf = 0.95f) +
            line(115f, "Toner" to 40f, "1" to 200f, "3,4O0.00" to 300f, conf = 0.4f)
        val t = TableExtractor.extract(PageText(0, 612f, 792f, words, TextSource.OCR))[0]
        val cell = t.bodyRows[1].cells[2]
        assertTrue(CellFlag.LOW_OCR_CONFIDENCE in cell.flags)
        assertTrue(CellFlag.UNPARSED_VALUE in cell.flags)
        assertEquals("3,4O0.00", cell.raw) // never "corrected" silently
    }

    @Test fun manualAreaLimitsExtraction() {
        val t = TableExtractor.extract(statement(), TableOptions(area = NormRect(0f, 0.12f, 1f, 0.17f)))
        assertEquals(1, t.size)
        assertTrue(t[0].rows.size <= 3)
    }

    @Test fun combineAcrossPages() {
        val p1 = TableExtractor.extract(statement())[0]
        val p2 = p1.copy(pageIndex = 1)
        val combined = TableExtractor.combine(listOf(p1, p2))
        assertEquals(1, combined.size)
        assertEquals(1, combined[0].rows.count { it.isHeader })
        assertEquals(8, combined[0].bodyRows.size)
    }
}
