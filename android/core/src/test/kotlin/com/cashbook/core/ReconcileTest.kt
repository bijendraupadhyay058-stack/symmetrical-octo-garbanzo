package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class ReconcileTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)
    private val bank = AccountInfo(2, 1, "SBI Bank", AccountType.BANK, 5_000_000, d(4, 1))
    private val hdfc = AccountInfo(3, 1, "HDFC Bank", AccountType.BANK, 0, d(4, 1))
    private val txns = listOf(
        Txn(1, 1, TxnType.INCOME, d(4, 3), 1_000_000, 2, clearedOn = d(4, 30)),                         // cleared last month
        Txn(2, 1, TxnType.EXPENSE, d(5, 2), 200_000, 2),
        Txn(3, 1, TxnType.TRANSFER, d(5, 5), 300_000, 2, toAccountId = 3, toClearedOn = d(5, 31)),      // cleared on HDFC only
        Txn(4, 1, TxnType.INCOME, d(5, 20), 50_000, 2),
        Txn(5, 1, TxnType.INCOME, d(6, 2), 70_000, 2),                                                   // after the statement
    )

    @Test fun clearedBalanceAndDifference() {
        assertEquals(6_000_000L, Reconcile.clearedBalance(bank, txns))                                   // 50,000 + 10,000
        assertEquals(listOf(2L, 3L, 4L), Reconcile.uncleared(bank, txns, d(5, 31)).map { it.id })
        assertTrue(Reconcile.isCleared(txns[2], 3)); assertFalse(Reconcile.isCleared(txns[2], 2))
        assertEquals(300_000L, Reconcile.clearedBalance(hdfc, txns))
        // statement closes at 55,500: 60,000 − 2,000 − 3,000 + 500
        val statement = 5_550_000L
        assertEquals(statement - 6_000_000, Reconcile.difference(statement, bank, txns, emptyList()))
        assertEquals(50_000L, Reconcile.difference(statement, bank, txns, txns.filter { it.id in setOf(2L, 3L) }))   // the ₹500 receipt is still missing
        assertEquals(0L, Reconcile.difference(statement, bank, txns, txns.filter { it.id in setOf(2L, 3L, 4L) }))
    }

    @Test fun cashCount() {
        val counts = mapOf(500 to 10, 200 to 3, 10 to 7, 1 to 4)
        assertEquals((5_000 + 600 + 70 + 4) * 100L, CashCount.total(counts))
        assertEquals("500x10,200x3,10x7,1x4", CashCount.encode(counts + (50 to 0)))
        assertEquals(counts, CashCount.decode("500x10, 200x3,10x7,1x4,bad,20x0,x5"))
        assertEquals(-12_000L, CashCountRecord(1, 1, d(5, 1), 488_000, 500_000, emptyMap()).difference)
        assertFalse(2000 in CashCount.DENOMINATIONS)
    }

    @Test fun bankReconciliationStatement() {
        fun brs(asOf: LocalDate) = ReportEngine(ReportInput(ReportType.BANK_RECONCILIATION, "Office", accounts = listOf(bank, hdfc), categories = emptyMap(),
            parties = emptyMap(), txns = txns, range = DateRange(d(4, 1), asOf), generatedAt = "now",
            reconciliations = listOf(Reconciliation(1, 2, d(4, 30), 6_000_000, 1)))).build()
        val may = brs(d(5, 31))
        val sbi = may.tables.first { it.title == "SBI Bank" }.rows
        // books 50,000 + 10,000 − 2,000 − 3,000 + 500 = 55,500; deposit 500 not credited; payments 2,000 + 3,000 not debited
        assertEquals(Cell.Amount(5_550_000), sbi[0].cells[2])
        assertEquals(Cell.Amount(-50_000), sbi[1].cells[2])
        val lessAt = sbi.indexOfFirst { it.cells[1] == Cell.Text("Less: deposits not yet credited by the bank") }
        val addAt = sbi.indexOfFirst { it.cells[1] == Cell.Text("Add: payments not yet debited by the bank") }
        assertEquals(listOf(Cell.Amount(50_000)), sbi.subList(lessAt + 1, addAt).map { it.cells[2] })                   // the ₹500 receipt of 20 May
        assertEquals(listOf(d(5, 2), d(5, 5)), sbi.subList(addAt + 1, sbi.indexOfFirst { it.style == RowStyle.TOTAL }).map { (it.cells[0] as Cell.Day).date })
        val total = sbi.single { it.style == RowStyle.TOTAL }
        assertEquals(Cell.Amount(5_550_000 - 50_000 + 500_000), total.cells[2])                       // the bank should show 60,000
        assertEquals(Cell.Amount(6_000_000), sbi.last().cells[2])                                      // last reconciled balance
        // HDFC: the transfer was cleared on 31 May, so on 15 May it is still outstanding, on 31 May it isn't
        assertEquals(Cell.Amount(0), brs(d(5, 15)).tables.first { it.title == "HDFC Bank" }.rows.single { it.style == RowStyle.TOTAL }.cells[2])
        assertEquals(Cell.Amount(300_000), may.tables.first { it.title == "HDFC Bank" }.rows.single { it.style == RowStyle.TOTAL }.cells[2])
        assertTrue(may.notes.isNotEmpty())
    }
}
