package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Phase7Test {
    private fun page(vararg lines: String): PageText {
        val words = lines.flatMapIndexed { li, l -> var x = 10f; l.split(" ").map { w -> TextWord(w, x, 20f + li * 15f, w.length * 5f, 10f).also { x += w.length * 5f + 3f } } }
        return PageText(0, 600f, 800f, words, TextSource.PDF_TEXT)
    }

    @Test fun checksums() {
        assertTrue(SensitiveFinder.verhoeff("234567890124"))   // valid Verhoeff test number
        assertFalse(SensitiveFinder.verhoeff("234567890123"))
        assertTrue(SensitiveFinder.luhn("4111111111111111"))
        assertFalse(SensitiveFinder.luhn("4111111111111112"))
        assertTrue(SensitiveFinder.gstinValid("27AAPFU0939F1ZV"))
        assertFalse(SensitiveFinder.gstinValid("27AAPFU0939F1ZX"))
    }

    @Test fun findsIdentifiers() {
        val p = page("Name: Asha  PAN: ABCPD1234E  GSTIN: 27AAPFU0939F1ZV", "Aadhaar 2345 6789 0124 mobile +91 98765 43210", "Card 4111 1111 1111 1111 email asha.rao@example.com IFSC SBIN0001234",
            "Invoice 2345 6789 0123 total 1,250.00")
        val m = SensitiveFinder.find(p, SensitiveKind.entries.toSet() - SensitiveKind.ACCOUNT)
        val kinds = m.groupBy { it.kind }.mapValues { e -> e.value.map { it.text } }
        assertEquals(listOf("ABCPD1234E"), kinds[SensitiveKind.PAN])
        assertEquals(listOf("27AAPFU0939F1ZV"), kinds[SensitiveKind.GSTIN])
        assertEquals(listOf("2345 6789 0124"), kinds[SensitiveKind.AADHAAR]) // the invoice number fails Verhoeff
        assertEquals(listOf("4111 1111 1111 1111"), kinds[SensitiveKind.CARD])
        assertEquals(listOf("asha.rao@example.com"), kinds[SensitiveKind.EMAIL])
        assertEquals(listOf("SBIN0001234"), kinds[SensitiveKind.IFSC])
        assertTrue(kinds[SensitiveKind.MOBILE]!!.single().contains("98765"))
        val custom = SensitiveFinder.find(p, setOf(SensitiveKind.CUSTOM), listOf("asha"))
        assertEquals(2, custom.size)
    }

    private fun table(header: List<String>, types: List<ColumnType>, vararg rows: List<String>) = ExtractedTable(0, 0, header.size,
        listOf(TableRow(header.map { TableCell(it) }, 0, true)) + rows.map { r -> TableRow(r.map { TableCell(it) }, 0) }, types, TextSource.PDF_TEXT)

    @Test fun normalizeDebitCreditStatement() {
        val t = table(listOf("Txn Date", "Description", "Chq No", "Withdrawal Amt", "Deposit Amt", "Closing Balance"),
            listOf(ColumnType.DATE, ColumnType.TEXT, ColumnType.TEXT, ColumnType.AMOUNT, ColumnType.AMOUNT, ColumnType.AMOUNT),
            listOf("01/04/2024", "Opening", "", "", "", "10,000.00"),
            listOf("02/04/2024", "UPI rent", "000123", "2,500.00", "", "7,500.00"),
            listOf("03/04/2024", "Salary", "", "", "50,000.00", "57,500.00"))
        val n = StatementNormalizer.normalize(listOf(t), NumberStyle.INDIAN, DateOrder.DMY, "apr.pdf")!!
        assertEquals(3, n.rows.size)
        assertEquals(BigDecimal("2500.00"), n.rows[1].debit); assertEquals("000123", n.rows[1].reference)
        assertEquals(LocalDate.of(2024, 4, 3), n.rows[2].date)
        assertEquals(emptyList<Int>(), StatementNormalizer.balanceMismatches(n.rows))
    }

    @Test fun normalizeAmountWithDrCr() {
        val t = table(listOf("Date", "Particulars", "Amount", "Dr/Cr", "Balance"),
            listOf(ColumnType.DATE, ColumnType.TEXT, ColumnType.AMOUNT, ColumnType.TEXT, ColumnType.AMOUNT),
            listOf("05-May-2024", "NEFT in", "1,000.00", "CR", "5,000.00 Cr"),
            listOf("06-May-2024", "ATM", "500.00", "DR", "4,500.00 Cr"),
            listOf("07-May-2024", "Unclear", "200.00", "", "4,300.00 Cr"))
        val n = StatementNormalizer.normalize(listOf(t), NumberStyle.INDIAN, DateOrder.DMY, "may.pdf")!!
        assertEquals(BigDecimal("1000.00"), n.rows[0].credit)
        assertEquals(BigDecimal("500.00"), n.rows[1].debit)
        assertTrue(n.rows[2].flags.any { it.contains("unclear") }) // never guesses the direction
        assertEquals(null, n.rows[2].debit)
    }

    @Test fun combineSortsAndFlagsOverlap() {
        val r1 = StatementRow(LocalDate.of(2024, 4, 30), "30/04/2024", "Fee", "", BigDecimal("10"), null, BigDecimal("90"), "90", "april.pdf", 2)
        val r0 = StatementRow(LocalDate.of(2024, 4, 1), "01/04/2024", "Open", "", null, BigDecimal("100"), BigDecimal("100"), "100", "april.pdf", 1)
        val r2 = r1.copy(source = "may.pdf", page = 1)
        val r3 = StatementRow(LocalDate.of(2024, 5, 2), "02/05/2024", "Salary", "", null, BigDecimal("1000"), BigDecimal("1090"), "1090", "may.pdf", 1)
        val norm = { rows: List<StatementRow> -> NormalizedStatement(rows, ColumnMapping(0, 1, null, 2, 3, 4, null, null), emptyList()) }
        val all = StatementNormalizer.combine(listOf(norm(listOf(r0, r1)), norm(listOf(r2, r3))))
        assertEquals(listOf("Open", "Fee", "Fee", "Salary"), all.map { it.narration })
        assertTrue(all[2].flags.single().contains("april.pdf"))
        assertTrue(StatementNormalizer.toCsv(all).startsWith("﻿Date,Narration"))
    }
}
