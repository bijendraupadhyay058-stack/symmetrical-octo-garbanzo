package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test

class ParsingTest {
    @Test fun pageRanges() {
        assertEquals(listOf(0, 1, 2, 4), PageRanges.parse("1-3, 5", 10))
        assertEquals(listOf(listOf(0, 1, 2, 3, 4), listOf(5, 6, 7, 8, 9)), PageRanges.parseGroups("1–5, 6-10", 10))
        assertEquals((0 until 4).toList(), PageRanges.parse("all", 4))
        assertEquals(listOf(7, 8, 9), PageRanges.parse("8-", 10))
        assertEquals(listOf(listOf(0, 1, 2), listOf(3, 4, 5, 6), listOf(7, 8, 9)), PageRanges.splitAfter(listOf(3, 7), 10))
        assertEquals("1-3, 5, 7-8", PageRanges.format(listOf(0, 1, 2, 4, 6, 7)))
    }

    @Test(expected = PageRanges.ParseException::class) fun pageRangeOutOfBounds() { PageRanges.parse("1-12", 10) }
    @Test(expected = PageRanges.ParseException::class) fun pageRangeReversed() { PageRanges.parse("5-2", 10) }
    @Test(expected = PageRanges.ParseException::class) fun pageRangeJunk() { PageRanges.parse("abc", 10) }

    @Test fun indianAmounts() {
        val a = AmountParser.parse("1,23,456.78")!!
        assertEquals(BigDecimal("123456.78"), a.value); assertTrue(a.indianGrouping)
        assertEquals(BigDecimal("-1234.00"), AmountParser.parse("(1,234.00)")!!.value)
        assertTrue(AmountParser.parse("(1,234.00)")!!.bracketed)
        assertEquals(BigDecimal("-50.5"), AmountParser.parse("-50.5")!!.value)
        assertEquals(BigDecimal("2500.00"), AmountParser.parse("₹ 2,500.00")!!.value)
        assertEquals(BigDecimal("2500.00"), AmountParser.parse("Rs. 2,500.00")!!.value)
        val dr = AmountParser.parse("12,345.00 Dr")!!
        assertEquals(DrCr.DR, dr.drCr); assertEquals(BigDecimal("12345.00"), dr.value) // Dr never flips the sign
        assertEquals(DrCr.CR, AmountParser.parse("1,00,000.00CR")!!.drCr)
        assertEquals(BigDecimal("-75.00"), AmountParser.parse("75.00-")!!.value)
        assertEquals(BigDecimal("1234567.89"), AmountParser.parse("1,234,567.89", NumberStyle.INTERNATIONAL)!!.value)
        assertEquals(BigDecimal("1234.56"), AmountParser.parse("1.234,56", NumberStyle.EUROPEAN)!!.value)
    }

    @Test fun referenceNumbersStayText() {
        assertNull(AmountParser.parse("000123"))           // leading zeros
        assertNull(AmountParser.parse("123456789012345"))  // long account number
        assertNull(AmountParser.parse("UPI/1234/ABC"))
        assertNull(AmountParser.parse("12,34"))            // bad grouping
        assertNull(AmountParser.parse("1,23,456.78", NumberStyle.INTERNATIONAL)) // Indian grouping rejected in intl mode
        assertFalse(AmountParser.looksLikeMoney("123456", NumberStyle.INDIAN)) // bare integer, e.g. cheque no.
        assertTrue(AmountParser.looksLikeMoney("1,234.00", NumberStyle.INDIAN))
    }

    @Test fun formatIndian() {
        assertEquals("12,34,567.50", AmountParser.formatIndian(BigDecimal("1234567.5")))
        assertEquals("999.00", AmountParser.formatIndian(BigDecimal("999")))
        assertEquals("-1,00,000.00", AmountParser.formatIndian(BigDecimal("-100000")))
    }

    @Test fun dates() {
        assertEquals(LocalDate.of(2025, 3, 31), DateParser.parse("31/03/2025"))
        assertEquals(LocalDate.of(2025, 3, 31), DateParser.parse("31-03-25"))
        assertEquals(LocalDate.of(2024, 4, 1), DateParser.parse("01-Apr-2024"))
        assertEquals(LocalDate.of(2024, 4, 1), DateParser.parse("01 Apr 24"))
        assertEquals(LocalDate.of(2024, 4, 1), DateParser.parse("2024-04-01"))
        assertEquals(LocalDate.of(2025, 3, 4), DateParser.parse("03/04/2025", DateOrder.MDY))
        assertEquals(LocalDate.of(2025, 4, 3), DateParser.parse("03/04/2025", DateOrder.DMY))
        assertEquals(LocalDate.of(2024, 9, 5), DateParser.parse("Sept 5, 2024"))
        assertNull(DateParser.parse("31/02/2025"))
        assertNull(DateParser.parse("hello"))
        assertEquals(45747L, DateParser.toExcelSerial(LocalDate.of(2025, 3, 31)))
    }

    @Test fun numberFormatter() {
        assertEquals("1,234.50", NumberFormatter.format(1234.5, "#,##0.00"))
        assertEquals("(1,234.50)", NumberFormatter.format(-1234.5, "#,##0.00;(#,##0.00)"))
        assertEquals("12,34,567.00", NumberFormatter.format(1234567.0, ExcelExport.INDIAN_FORMAT))
        assertEquals("12.5%", NumberFormatter.format(0.125, "0.0%"))
        assertEquals("31-03-2025", NumberFormatter.format(45747.0, "dd-mm-yyyy"))
        assertEquals("31-Mar-25", NumberFormatter.format(45747.0, "dd-mmm-yy"))
        assertEquals("1234.5", NumberFormatter.format(1234.5, "General"))
        assertEquals("₹1,000", NumberFormatter.format(1000.0, "[\$₹-4009]#,##0"))
        assertEquals("14:30", NumberFormatter.format(0.6041666, "hh:mm"))
    }

    @Test fun pageTransform() {
        // Rotate 90: display (0,0) bottom-left of shown page -> PDF (x0+w, y0)
        val t = PageTransform.displayToPdf(0f, 0f, 600f, 800f, 90)
        assertEquals(600f to 0f, t.apply(0f, 0f))
        assertEquals(600f to 800f, t.apply(800f, 0f))
        assertEquals(0f to 0f, t.apply(0f, 600f))
        val t0 = PageTransform.displayToPdf(10f, 20f, 600f, 800f, 0)
        assertEquals(15f to 25f, t0.apply(5f, 5f))
        assertEquals(800f to 600f, PageTransform.displaySize(600f, 800f, 270))
    }
}
