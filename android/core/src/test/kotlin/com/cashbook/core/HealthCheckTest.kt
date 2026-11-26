package com.cashbook.core

import com.cashbook.core.HealthCheck.Check
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class HealthCheckTest {
    private val d = LocalDate.of(2026, 11, 1)
    private val cash = AccountInfo(1, 1, "Cash", AccountType.CASH, 100_000, d)
    private val bank = AccountInfo(2, 1, "Bank", AccountType.BANK, 0, d)
    private val other = AccountInfo(3, 2, "Other book", AccountType.CASH, 0, d)
    private val fees = CategoryInfo(10, CategoryKind.INCOME, "Fees")
    private val rent = CategoryInfo(20, CategoryKind.EXPENSE, "Rent")

    @Test fun cleanLedgerIsAllOk() {
        val txns = listOf(Txn(1, 1, TxnType.INCOME, d, 50_000, 2, categoryId = 10), Txn(2, 1, TxnType.TRANSFER, d, 10_000, 1, toAccountId = 2))
        val inv = InvoiceInfo(5, 1, InvoiceKind.SALE, "INV/1", 9, d, d, 50_000)
        val r = HealthCheck.ledger(listOf(cash, bank), listOf(fees, rent), txns, emptyList(), listOf(inv), listOf(Allocation(1, 5, 1, 50_000)))
        assertEquals(Check.entries.toList(), r.map { it.check })
        assertTrue(r.all { it.severity == Severity.OK && it.count == 0 })
    }

    @Test fun findsEachKindOfProblem() {
        val txns = listOf(
            Txn(1, 1, TxnType.INCOME, d, 50_000, 2, categoryId = 20, description = "Fees in an expense category"),
            Txn(2, 1, TxnType.TRANSFER, d, 10_000, 1, toAccountId = 1, description = "Transfer to itself"),
            Txn(3, 1, TxnType.EXPENSE, d, 5_000, 3, categoryId = 20, description = "Account from another cashbook"),
            Txn(4, 1, TxnType.EXPENSE, d, 300_000, 1, categoryId = 20, description = "Big rent"),          // cash goes negative
        )
        val binned = listOf(Txn(9, 1, TxnType.INCOME, d, 1_000, 2, deletedAt = 1))
        val docs = listOf(InvoiceInfo(5, 1, InvoiceKind.SALE, "INV/1", 9, d, d, 10_000),
            InvoiceInfo(6, 1, InvoiceKind.SALE, "QT/1", 9, d, d, 10_000, docType = DocType.QUOTATION, convertedInvoiceId = 77))
        val allocs = listOf(Allocation(1, 5, 1, 40_000), Allocation(2, 5, 1, 20_000),       // 60,000 applied from a 50,000 entry
            Allocation(3, 5, 9, 1_000),                                                         // binned entry: fine
            Allocation(4, 99, 1, 1), Allocation(5, 5, 404, 1))                                  // missing invoice / entry
        val r = HealthCheck.ledger(listOf(cash, bank, other), listOf(fees, rent), txns, binned, docs, allocs).associateBy { it.check }
        assertEquals(2, r[Check.ALLOCATIONS_ORPHANED]!!.count); assertEquals(Severity.ERROR, r[Check.ALLOCATIONS_ORPHANED]!!.severity)
        assertEquals(1, r[Check.OVER_ALLOCATED]!!.count)
        assertEquals(listOf("#2 2026-11-01 Transfer to itself"), r[Check.TRANSFER_BROKEN]!!.examples)
        assertEquals(1, r[Check.CASHBOOK_MISMATCH]!!.count)
        assertEquals(1, r[Check.CATEGORY_KIND]!!.count); assertEquals(Severity.WARNING, r[Check.CATEGORY_KIND]!!.severity)
        assertEquals(listOf("QT/1 → #77"), r[Check.CONVERSION_LINK]!!.examples)
        assertTrue("Cash" in r[Check.NEGATIVE_BALANCE]!!.examples); assertEquals(Severity.INFO, r[Check.NEGATIVE_BALANCE]!!.severity)   // "Other book" too, from the mismatched entry
    }
}
