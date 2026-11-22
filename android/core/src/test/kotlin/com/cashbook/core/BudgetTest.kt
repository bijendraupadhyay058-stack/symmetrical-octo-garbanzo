package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.time.YearMonth

class BudgetTest {
    private val parent = CategoryInfo(1, CategoryKind.EXPENSE, "Travel")
    private val child = CategoryInfo(2, CategoryKind.EXPENSE, "Fuel", parentId = 1)
    private val other = CategoryInfo(3, CategoryKind.EXPENSE, "Rent")
    private val cats = listOf(parent, child, other).associateBy { it.id }
    private fun e(cat: Long, amt: Long, day: Int, month: Int = 4, cb: Long = 1, type: TxnType = TxnType.EXPENSE) =
        Txn(0, cb, type, LocalDate.of(2026, month, day), amt, 1, categoryId = cat)

    @Test fun includesSubcategoriesAndOnlyThatMonthAndCashbook() {
        val txns = listOf(e(1, 100_000, 2), e(2, 50_000, 3), e(1, 999_999, 2, month = 5), e(1, 70_000, 2, cb = 2), e(3, 10_000, 4),
            e(1, 5_000, 5, type = TxnType.INCOME))
        val p = Budgets.progress(listOf(BudgetInfo(1, 1, 1, 200_000)), txns, cats, YearMonth.of(2026, 4)).single()
        assertEquals(150_000L, p.spent)
        assertEquals(50_000L, p.remaining)
        assertEquals("75.0%", p.percent)
        assertEquals(BudgetStatus.OK, p.status)
    }

    @Test fun detectsWorsenedBudgets() {
        val b = listOf(BudgetInfo(1, 1, 1, 100_000), BudgetInfo(2, 1, 3, 100_000))
        val before = listOf(e(1, 70_000, 2))
        val month = YearMonth.of(2026, 4)
        assertEquals(listOf(1L), Budgets.worsened(b, before, before + e(1, 15_000, 3), cats, month).map { it.budget.id })   // OK → NEAR
        assertEquals(BudgetStatus.OVER, Budgets.worsened(b, before, before + e(2, 40_000, 3), cats, month).single().status) // child counts → OVER
        assertEquals(0, Budgets.worsened(b, before, before + e(1, 1_000, 3), cats, month).size)                            // still OK
    }

    @Test fun statusThresholds() {
        fun status(spent: Long) = BudgetProgress(BudgetInfo(1, 1, 1, 100_000), spent).status
        assertEquals(BudgetStatus.OK, status(79_999))
        assertEquals(BudgetStatus.NEAR, status(80_000))
        assertEquals(BudgetStatus.NEAR, status(100_000))
        assertEquals(BudgetStatus.OVER, status(100_001))
    }
}
