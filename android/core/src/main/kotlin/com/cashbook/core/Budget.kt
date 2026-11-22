package com.cashbook.core

import java.time.YearMonth

/** Monthly spending limit for an expense category in one cashbook. Sub-categories count towards their parent's budget. */
data class BudgetInfo(val id: Long, val cashbookId: Long, val categoryId: Long, val monthlyAmount: Long)

enum class BudgetStatus { OK, NEAR, OVER }

data class BudgetProgress(val budget: BudgetInfo, val spent: Long) {
    val remaining: Long get() = budget.monthlyAmount - spent
    /** Fraction used, as a float for progress bars only (never used for money). */
    val fraction: Float get() = if (budget.monthlyAmount <= 0) 0f else (spent.toDouble() / budget.monthlyAmount).toFloat()
    val percent: String get() = Money.percent(spent, budget.monthlyAmount)
    val status: BudgetStatus get() = when {
        spent > budget.monthlyAmount -> BudgetStatus.OVER
        spent * 100 >= budget.monthlyAmount * NEAR_PERCENT -> BudgetStatus.NEAR
        else -> BudgetStatus.OK
    }

    companion object { const val NEAR_PERCENT = 80 }
}

object Budgets {
    /**
     * Budgets whose status got worse (OK → NEAR → OVER) because of a change in entries, e.g. after
     * saving an expense. Used to warn immediately in the app.
     */
    fun worsened(budgets: List<BudgetInfo>, before: List<Txn>, after: List<Txn>, categories: Map<Long, CategoryInfo>, month: YearMonth): List<BudgetProgress> {
        val old = progress(budgets, before, categories, month).associateBy { it.budget.id }
        return progress(budgets, after, categories, month).filter { p -> (old[p.budget.id]?.status?.ordinal ?: 0) < p.status.ordinal }
    }

    fun progress(budgets: List<BudgetInfo>, txns: List<Txn>, categories: Map<Long, CategoryInfo>, month: YearMonth): List<BudgetProgress> {
        val range = DateRange(month.atDay(1), month.atEndOfMonth())
        return budgets.map { b ->
            val ids = setOf(b.categoryId) + categories.values.filter { it.parentId == b.categoryId }.map { it.id }
            val spent = txns.filter { it.type == TxnType.EXPENSE && it.cashbookId == b.cashbookId && it.categoryId in ids && it.date in range }.sumOf { it.amount }
            BudgetProgress(b, spent)
        }.sortedByDescending { it.fraction }
    }
}
