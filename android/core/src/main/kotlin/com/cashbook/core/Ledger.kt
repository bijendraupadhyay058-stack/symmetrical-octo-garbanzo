package com.cashbook.core

import java.time.LocalDate

/** Totals of a set of entries, as seen from a set of accounts. */
data class Totals(
    val income: Long = 0,
    val expense: Long = 0,
    val transferIn: Long = 0,
    val transferOut: Long = 0,
    val incomeCount: Int = 0,
    val expenseCount: Int = 0,
    val transferCount: Int = 0,
) {
    val net: Long get() = income - expense
    val movement: Long get() = income - expense + transferIn - transferOut
}

data class AccountStatement(
    val account: AccountInfo,
    val opening: Long,
    /** Opening balances of accounts whose opening date falls inside the period. */
    val openingIntroduced: Long,
    val totals: Totals,
    val closing: Long,
)

data class RunningLine(val txn: Txn, val inflow: Long, val outflow: Long, val balance: Long)

/**
 * The single source of truth for every balance in the app:
 *
 *   closing = opening balance + income received − expenses paid
 *             + transfers received − transfers sent
 *
 * An account's opening balance takes effect on its opening date. Callers must pass only
 * live (not deleted) entries. Transfers never count as income or expense.
 */
object Ledger {

    /** Signed effect of [txn] on [accountId]. */
    fun effect(txn: Txn, accountId: Long): Long = when (txn.type) {
        TxnType.INCOME -> if (txn.accountId == accountId) txn.amount else 0
        TxnType.EXPENSE -> if (txn.accountId == accountId) -txn.amount else 0
        TxnType.TRANSFER -> {
            var e = 0L
            if (txn.accountId == accountId) e -= txn.amount
            if (txn.toAccountId == accountId) e += txn.amount
            e
        }
    }

    /** Signed effect of [txn] on a set of accounts (internal transfers net to zero). */
    fun effect(txn: Txn, accountIds: Set<Long>): Long = accountIds.sumOf { effect(txn, it) }

    fun touches(txn: Txn, accountIds: Set<Long>): Boolean =
        txn.accountId in accountIds || (txn.toAccountId != null && txn.toAccountId in accountIds)

    /** Balance of an account at the end of [asOf] (inclusive). */
    fun balanceAsOf(account: AccountInfo, txns: List<Txn>, asOf: LocalDate): Long {
        var b = if (!account.openingDate.isAfter(asOf)) account.openingBalance else 0L
        for (t in txns) if (!t.date.isAfter(asOf)) b += effect(t, account.id)
        return b
    }

    /** Balance at the start of [date], i.e. everything strictly before it. */
    fun balanceBefore(account: AccountInfo, txns: List<Txn>, date: LocalDate): Long =
        balanceAsOf(account, txns, date.minusDays(1))

    fun currentBalance(account: AccountInfo, txns: List<Txn>): Long {
        var b = account.openingBalance
        for (t in txns) b += effect(t, account.id)
        return b
    }

    /** Totals inside [range] from the point of view of [accountIds]. */
    fun totals(txns: List<Txn>, accountIds: Set<Long>, range: DateRange? = null): Totals {
        var inc = 0L; var exp = 0L; var tin = 0L; var tout = 0L
        var ic = 0; var ec = 0; var tc = 0
        for (t in txns) {
            if (range != null && t.date !in range) continue
            if (!touches(t, accountIds)) continue
            when (t.type) {
                TxnType.INCOME -> { inc += t.amount; ic++ }
                TxnType.EXPENSE -> { exp += t.amount; ec++ }
                TxnType.TRANSFER -> {
                    val fromIn = t.accountId in accountIds
                    val toIn = t.toAccountId in accountIds
                    if (fromIn) tout += t.amount
                    if (toIn) tin += t.amount
                    tc++
                }
            }
        }
        return Totals(inc, exp, tin, tout, ic, ec, tc)
    }

    fun statement(account: AccountInfo, txns: List<Txn>, range: DateRange): AccountStatement {
        val opening = balanceBefore(account, txns, range.start)
        val introduced = if (account.openingDate in range) account.openingBalance else 0L
        val totals = totals(txns, setOf(account.id), range)
        val closing = opening + introduced + totals.movement
        return AccountStatement(account, opening, introduced, totals, closing)
    }

    /** Chronological lines with a running balance for one account (all time). */
    fun running(account: AccountInfo, txns: List<Txn>): List<RunningLine> {
        var bal = account.openingBalance
        return txns.filter { touches(it, setOf(account.id)) }.sortedWith(TxnChronological).map { t ->
            val e = effect(t, account.id)
            bal += e
            RunningLine(t, if (e > 0) e else 0, if (e < 0) -e else 0, bal)
        }
    }

    /**
     * Lowest running balance any account touched by [candidate] would reach if it were saved
     * (replacing [replacingId] when editing). Returns the offending account and balance, or
     * null when nothing goes below zero.
     */
    fun negativeCheck(
        accounts: List<AccountInfo>,
        txns: List<Txn>,
        candidate: Txn,
        replacingId: Long? = null,
    ): Pair<AccountInfo, Long>? {
        val others = if (replacingId == null) txns else txns.filter { it.id != replacingId }
        val all = others + candidate
        val touched = listOfNotNull(candidate.accountId, candidate.toAccountId)
        for (acc in accounts.filter { it.id in touched }) {
            if (effect(candidate, acc.id) >= 0) continue
            var bal = acc.openingBalance
            var min = Long.MAX_VALUE
            for (line in all.filter { touches(it, setOf(acc.id)) }.sortedWith(TxnChronological)) {
                bal += effect(line, acc.id)
                if (!line.date.isBefore(candidate.date)) min = minOf(min, bal)
            }
            if (min != Long.MAX_VALUE && min < 0) return acc to min
        }
        return null
    }
}
