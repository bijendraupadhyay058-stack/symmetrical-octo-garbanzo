package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BankReviewTest {
    private fun b(s: String?) = s?.let { BigDecimal(it) }
    private fun row(d: String, narr: String, dr: String?, cr: String?, bal: String?, src: String = "A.pdf", page: Int = 1, flags: List<String> = emptyList()) =
        StatementRow(LocalDate.parse(d), d, narr, "", b(dr), b(cr), b(bal), bal ?: "", src, page, flags)

    // Opening 1,000: +5,000 credit, -200 charges, -1,500 ATM → 4,300
    private val asc = listOf(
        row("2024-04-01", "NEFT CR ACME LTD", null, "5000", "6000"),
        row("2024-04-03", "SMS ALERT CHGS", "200", null, "5800"),
        row("2024-04-05", "ATM WDL MG ROAD", "1500", null, "4300"),
    )

    @Test fun suggestsCategories() {
        assertEquals(TxnCategory.UPI_PAYMENT, Categoriser.suggest("UPI/123456/SWIGGY", b("250"), null))
        assertEquals(TxnCategory.UPI_RECEIPT, Categoriser.suggest("UPI/9876/RAMESH", null, b("250")))
        assertEquals(TxnCategory.BANK_CHARGES, Categoriser.suggest("SMS ALERT CHGS QTR", b("15"), null))
        assertEquals(TxnCategory.INTEREST_RECEIVED, Categoriser.suggest("SB INT CREDIT", null, b("120")))
        assertEquals(TxnCategory.CASH_WITHDRAWAL, Categoriser.suggest("ATM WDL 1234", b("2000"), null))
        assertEquals(TxnCategory.TAXES, Categoriser.suggest("GST CHALLAN 27AAAA", b("9000"), null))
        assertEquals(TxnCategory.CHEQUE_DEPOSIT, Categoriser.suggest("BY CLG CHQ 000123", null, b("9000")))
        assertNull(Categoriser.suggest("NEFT ACME LTD", null, b("9000"))) // customer or not: user decides
        assertNull(Categoriser.suggest("INTERNET BANKING TRF", b("10"), b("10")))
    }

    @Test fun ascendingReconciles() {
        val s = ReviewSession(asc)
        assertEquals(StatementOrder.OLDEST_FIRST, s.order); assertTrue(s.orderConfirmed)
        val op = s.opening("A.pdf")
        assertEquals(BigDecimal("1000"), op.value); assertFalse(op.confirmed)
        var r = Reconciler.reconcile(s).single()
        assertEquals(CheckStatus.INCOMPLETE, r.lines.first { it.label == "Difference" }.status) // agrees but not confirmed
        s.confirmOpening("A.pdf", BigDecimal("1000")); s.confirmClosing("A.pdf", BigDecimal("4300"))
        r = Reconciler.reconcile(s).single()
        assertEquals(BigDecimal("4300"), r.lines.first { it.label == "Calculated closing balance" }.value)
        assertEquals(CheckStatus.OK, r.lines.first { it.label == "Difference" }.status)
        assertEquals(emptyList<Int>(), r.runningBreaks)
        assertEquals(TxnCategory.BANK_CHARGES, s.rows[1].category); assertTrue(s.rows[1].categorySuggested)
    }

    @Test fun descendingStatementUsesReverseOrder() {
        val s = ReviewSession(asc.reversed())
        assertEquals(StatementOrder.NEWEST_FIRST, s.order)
        assertEquals(BigDecimal("1000"), s.opening("A.pdf").value)
        assertEquals(BigDecimal("4300"), s.closing("A.pdf").value)
        assertEquals(emptyList<Int>(), Reconciler.reconcile(s).single().runningBreaks)
        // Forcing the wrong order makes the running balance break – the check depends on the order.
        s.setOrder(StatementOrder.OLDEST_FIRST)
        assertTrue(Reconciler.reconcile(s).single().runningBreaks.isNotEmpty())
    }

    @Test fun sameDayOrderNeedsConfirmation() {
        val same = asc.map { it.copy(date = LocalDate.parse("2024-04-01")) }.reversed()
        val s = ReviewSession(same)
        assertEquals(StatementOrder.NEWEST_FIRST, s.order) // from the balances
        assertFalse(s.orderConfirmed)
        assertEquals(CheckStatus.INCOMPLETE, Reconciler.reconcile(s).single().lines.last().status)
    }

    @Test fun editsAreAuditedAndMissingRowIsFound() {
        // Middle row missed by extraction: difference and a running-balance break show up.
        val s = ReviewSession(listOf(asc[0], asc[2]))
        s.confirmOpening("A.pdf", BigDecimal("1000")); s.confirmClosing("A.pdf", BigDecimal("4300"))
        var r = Reconciler.reconcile(s).single()
        assertEquals(BigDecimal("4500"), r.lines.first { it.label == "Calculated closing balance" }.value) // 200 charge missing
        assertEquals(CheckStatus.DIFFERENCE, r.lines.first { it.label == "Difference" }.status)
        assertEquals(1, r.runningBreaks.size)
        val id = s.insertAfter(s.rows[0].id)
        s.update(id, s.find(id).copy(date = LocalDate.parse("2024-04-03"), dateRaw = "03-04-2024", description = "SMS ALERT CHGS", debit = BigDecimal("200"), balance = BigDecimal("5800")))
        r = Reconciler.reconcile(s).single()
        assertEquals(CheckStatus.OK, r.lines.first { it.label == "Difference" }.status)
        assertTrue(s.audit.any { it.action == "Added row" } && s.audit.any { it.action == "Edited" && it.detail.contains("Debit: \"\" → \"200\"") })
    }

    @Test fun splitMergeAndDuplicates() {
        val s = ReviewSession(listOf(
            row("2024-04-01", "UPI/1/ACME", null, "500", "1500"),
            StatementRow(null, "", "PAYMENT FOR INV 42", "", null, null, null, "", "A.pdf", 1),
            row("2024-04-01", "UPI/1/ACME", null, "500", "1500", src = "B.pdf"),
        ))
        assertFalse(s.mergeWithNext(s.rows[1].id)) // different files
        assertTrue(s.mergeWithNext(s.rows[0].id))
        assertEquals("UPI/1/ACME PAYMENT FOR INV 42", s.rows[0].description)
        assertTrue(s.rows[0].original.contains("⏎"))
        val sid = s.split(s.rows[0].id)
        assertTrue(s.find(sid).flags.single().startsWith("Split from"))
        s.delete(sid)
        val ex = Reconciler.exceptions(s, Reconciler.reconcile(s), listOf("B.pdf" to "Page 3: OCR failed"))
        assertFalse(ex.any { it.kind == "Possible duplicate" }) // narration differs after merge
        assertTrue(ex.any { it.kind == "Page not processed" })
        // Two rows of different amounts can't be merged.
        val t = ReviewSession(asc)
        assertFalse(t.mergeWithNext(t.rows[0].id))
    }

    @Test fun workbookHasSheetsAndCorrections() {
        val s = ReviewSession((listOf(row("2024-04-05", "ATM WDL MG ROAD", "1500", null, "4300", flags = listOf("Low OCR confidence"))) + asc.reversed()).map { it.copy(reference = "000123") })
        assertEquals(StatementOrder.NEWEST_FIRST, s.order)
        s.setCategory(s.rows[0].id, TxnCategory.OTHER)
        val sheets = BankWorkbook.build(s, listOf(PageStatus("A.pdf", 1, "Text", "Processed"), PageStatus("A.pdf", 2, "Scanned", "Failed", "OCR error")), listOf("Number format: Indian"))
        assertEquals(listOf("Transactions", "Monthly Summary", "Category Summary", "Reconciliation", "Exceptions", "Processing Report"), sheets.map { it.name })
        val out = java.io.ByteArrayOutputStream(); XlsxWriter.write(sheets, out)
        val wb = XlsxReader.read(java.io.ByteArrayInputStream(out.toByteArray()))
        val tx = wb.sheets[0]
        assertEquals("Date", tx.cells[0]!![0]!!.display)
        assertEquals("000123", tx.cells[1]!![3]!!.display) // leading zeroes kept
        // Oldest first in the export although the statement was newest first.
        assertEquals("NEFT CR ACME LTD", tx.cells[1]!![2]!!.display)
        assertTrue((1..tx.maxRow).any { r -> tx.cells[r]?.get(7)?.display == "Other" && tx.cells[r]?.get(12)?.display == "Yes" })
        val exc = wb.sheets[4]
        assertTrue((1..exc.maxRow).any { r -> exc.cells[r]?.get(3)?.display == "Possible duplicate" })
        assertTrue((1..exc.maxRow).any { r -> exc.cells[r]?.get(3)?.display == "Page not processed" })
        val pr = wb.sheets[5]
        assertTrue((0..pr.maxRow).any { r -> pr.cells[r]?.get(2)?.display == "Edited" })
        assertTrue(String(out.toByteArray(), Charsets.ISO_8859_1).isNotEmpty())
    }
}
