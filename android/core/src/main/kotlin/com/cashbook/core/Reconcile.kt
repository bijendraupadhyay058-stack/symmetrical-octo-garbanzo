package com.cashbook.core

import java.time.LocalDate

/** A finished bank reconciliation: the statement's closing balance matched the cleared entries. */
data class Reconciliation(val id: Long, val accountId: Long, val statementDate: LocalDate, val statementBalance: Long, val entries: Int, val createdAt: Long = 0)

/**
 * Bank reconciliation: tick the entries that appear on the bank statement until the app's cleared balance equals
 * the statement's closing balance. Each side of a transfer is cleared on its own account.
 */
object Reconcile {
    fun isCleared(t: Txn, accountId: Long) =
        (t.accountId == accountId && t.clearedOn != null) || (t.toAccountId == accountId && t.toClearedOn != null)

    /** Opening balance plus every entry already cleared on this account. */
    fun clearedBalance(account: AccountInfo, txns: List<Txn>): Long =
        account.openingBalance + txns.filter { isCleared(it, account.id) }.sumOf { Ledger.effect(it, account.id) }

    /** Entries on the account up to [upTo] that haven't been cleared yet, oldest first. */
    fun uncleared(account: AccountInfo, txns: List<Txn>, upTo: LocalDate): List<Txn> =
        txns.filter { Ledger.touches(it, setOf(account.id)) && !isCleared(it, account.id) && !it.date.isAfter(upTo) }.sortedWith(TxnChronological)

    /** Statement balance minus (cleared balance + the entries ticked now). Zero means the account is reconciled. */
    fun difference(statementBalance: Long, account: AccountInfo, txns: List<Txn>, ticked: Collection<Txn>): Long =
        statementBalance - clearedBalance(account, txns) - ticked.sumOf { Ledger.effect(it, account.id) }
}

/** A cash count of notes and coins in a cash account, compared with the book balance. */
data class CashCountRecord(
    val id: Long, val accountId: Long, val date: LocalDate, val counted: Long, val book: Long,
    /** Rupee denomination → number of notes / coins. */
    val counts: Map<Int, Int>, val adjustmentTxnId: Long? = null, val note: String = "", val createdAt: Long = 0,
) {
    /** Positive = more cash than the books say (excess), negative = shortage. */
    val difference: Long get() = counted - book
}

object CashCount {
    /** Indian notes and coins in circulation (₹2,000 notes were withdrawn in 2023). */
    val DENOMINATIONS = listOf(500, 200, 100, 50, 20, 10, 5, 2, 1)

    fun total(counts: Map<Int, Int>): Long = counts.entries.sumOf { (d, n) -> d * 100L * n }

    /** "500x10,200x3" — compact text form for storage and backups. */
    fun encode(counts: Map<Int, Int>) = counts.filterValues { it > 0 }.toSortedMap(compareByDescending { it }).entries.joinToString(",") { "${it.key}x${it.value}" }

    fun decode(s: String): Map<Int, Int> = s.split(',').mapNotNull { p ->
        val (d, n) = p.split('x').takeIf { it.size == 2 } ?: return@mapNotNull null
        val dd = d.trim().toIntOrNull(); val nn = n.trim().toIntOrNull()
        if (dd != null && nn != null && dd > 0 && nn > 0) dd to nn else null
    }.toMap()
}
