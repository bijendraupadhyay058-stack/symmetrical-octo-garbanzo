package com.cashbook.core

import com.cashbook.core.SampleScenario.cash
import com.cashbook.core.SampleScenario.d
import com.cashbook.core.SampleScenario.sbi
import com.cashbook.core.SampleScenario.txns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class LedgerTest {
    @Test fun sampleDataMatchesExpectedBalances() {
        assertEquals(1_350_000L, Ledger.currentBalance(cash, txns)) // ₹13,500
        assertEquals(5_900_000L, Ledger.currentBalance(sbi, txns))  // ₹59,000
        assertEquals(7_250_000L, Ledger.currentBalance(cash, txns) + Ledger.currentBalance(sbi, txns)) // ₹72,500
    }

    @Test fun incomeIncreasesAndExpenseDecreasesBalance() {
        val before = Ledger.currentBalance(sbi, emptyList())
        val inc = Txn(9, 1, TxnType.INCOME, d(6), 100, sbi.id)
        assertEquals(before + 100, Ledger.currentBalance(sbi, listOf(inc)))
        val exp = inc.copy(type = TxnType.EXPENSE)
        assertEquals(before - 100, Ledger.currentBalance(sbi, listOf(exp)))
    }

    @Test fun transferKeepsCashbookTotalAndIsNotIncomeOrExpense() {
        val transfer = txns.last()
        val all = setOf(cash.id, sbi.id)
        val without = txns.dropLast(1)
        val totalBefore = Ledger.currentBalance(cash, without) + Ledger.currentBalance(sbi, without)
        val totalAfter = Ledger.currentBalance(cash, txns) + Ledger.currentBalance(sbi, txns)
        assertEquals(totalBefore, totalAfter)
        val t = Ledger.totals(txns, all)
        assertEquals(1_500_000L, t.income)
        assertEquals(250_000L, t.expense)
        assertEquals(transfer.amount, t.transferIn)
        assertEquals(transfer.amount, t.transferOut)
        assertEquals(0L, Ledger.effect(transfer, all))
        // From a single account's view the transfer is a movement, still not income
        val cashOnly = Ledger.totals(txns, setOf(cash.id))
        assertEquals(0L, cashOnly.income)
        assertEquals(500_000L, cashOnly.transferIn)
    }

    @Test fun editingAndDeletingRecalculate() {
        val edited = txns.map { if (it.id == 2L) it.copy(amount = 200_000) else it }
        assertEquals(1_300_000L, Ledger.currentBalance(cash, edited))
        val deleted = txns.filter { it.id != 4L } // deleting the transfer removes both sides
        assertEquals(850_000L, Ledger.currentBalance(cash, deleted))
        assertEquals(6_400_000L, Ledger.currentBalance(sbi, deleted))
    }

    @Test fun reportOpeningUsesEarlierTransactions() {
        val s = Ledger.statement(cash, txns, DateRange(d(4), d(30)))
        assertEquals(850_000L, s.opening) // 10,000 - 1,500
        assertEquals(0L, s.openingIntroduced)
        assertEquals(1_350_000L, s.closing)
        val first = Ledger.statement(sbi, txns, DateRange(d(1), d(30)))
        assertEquals(0L, first.opening)
        assertEquals(5_000_000L, first.openingIntroduced)
        assertEquals(5_900_000L, first.closing)
    }

    @Test fun balanceBeforeOpeningDateIsZero() {
        assertEquals(0L, Ledger.balanceAsOf(cash, txns, LocalDateHelper.march31))
    }

    @Test fun runningBalanceIsChronological() {
        val lines = Ledger.running(cash, txns)
        assertEquals(listOf(850_000L, 1_350_000L), lines.map { it.balance })
    }

    @Test fun sameDateEntriesSortedByCreationTime() {
        val a = Txn(10, 1, TxnType.EXPENSE, d(10), 1, cash.id, createdAt = 50)
        val b = Txn(5, 1, TxnType.EXPENSE, d(10), 1, cash.id, createdAt = 40)
        assertEquals(listOf(5L, 10L), listOf(a, b).sortedWith(TxnChronological).map { it.id })
    }

    @Test fun negativeBalanceIsDetected() {
        val big = Txn(0, 1, TxnType.EXPENSE, d(6), 2_000_000, cash.id, createdAt = 99)
        val hit = Ledger.negativeCheck(SampleScenario.accounts, txns, big)
        assertNotNull(hit)
        assertEquals(cash.id, hit!!.first.id)
        assertEquals(-650_000L, hit.second)
        assertNull(Ledger.negativeCheck(SampleScenario.accounts, txns, big.copy(amount = 100)))
        // Back-dated expense that is covered later but negative on its own date
        val early = Txn(0, 1, TxnType.EXPENSE, d(2), 1_200_000, cash.id, createdAt = 99)
        assertNotNull(Ledger.negativeCheck(SampleScenario.accounts, txns, early))
        // Editing an existing entry replaces the old version
        val edit = txns[1].copy(amount = 1_000_000)
        assertNull(Ledger.negativeCheck(SampleScenario.accounts, txns, edit, replacingId = 2))
    }
}

private object LocalDateHelper { val march31: java.time.LocalDate = java.time.LocalDate.of(2026, 3, 31) }
