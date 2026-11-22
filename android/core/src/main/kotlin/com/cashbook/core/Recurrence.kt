package com.cashbook.core

import java.time.LocalDate

enum class Frequency { DAILY, WEEKLY, MONTHLY, QUARTERLY, YEARLY }

/**
 * A rule that creates the same entry on a schedule (rent, salary, subscriptions).
 * Occurrence *n* is always computed from [startDate] (never from the previous date), so a
 * monthly rule starting on the 31st gives 31 Jan, 28/29 Feb, 31 Mar … without drifting.
 * [nextIndex] counts occurrences already posted or skipped.
 */
data class RecurringRule(
    val id: Long,
    val cashbookId: Long,
    val type: TxnType,
    val amount: Long,
    val accountId: Long,
    val toAccountId: Long? = null,
    val categoryId: Long? = null,
    val partyId: Long? = null,
    val paymentMode: PaymentMode = PaymentMode.CASH,
    val description: String = "",
    val reference: String = "",
    val notes: String = "",
    val tags: String = "",
    val frequency: Frequency = Frequency.MONTHLY,
    val interval: Int = 1,
    val startDate: LocalDate,
    val endDate: LocalDate? = null,
    val nextIndex: Int = 0,
    /** true: entries are created automatically; false: they wait on the dashboard for Post / Skip. */
    val autoPost: Boolean = true,
    val active: Boolean = true,
) {
    val nextDate: LocalDate? get() = Recurrence.occurrence(this, nextIndex).takeIf { endDate == null || !it.isAfter(endDate) }
    val finished: Boolean get() = nextDate == null

    /** The entry this rule creates for [date]. */
    fun toTxn(date: LocalDate, now: Long) = Txn(0, cashbookId, type, date, amount, accountId, if (type == TxnType.TRANSFER) toAccountId else null,
        if (type == TxnType.TRANSFER) null else categoryId, if (type == TxnType.TRANSFER) null else partyId, paymentMode, description,
        reference, notes, tags, now, now, recurringId = id)
}

object Recurrence {
    /** Hard cap so a rule left untouched for years cannot flood the ledger in one run. */
    const val MAX_CATCH_UP = 400

    fun occurrence(start: LocalDate, frequency: Frequency, interval: Int, n: Int): LocalDate {
        val step = interval.coerceAtLeast(1).toLong() * n
        return when (frequency) {
            Frequency.DAILY -> start.plusDays(step)
            Frequency.WEEKLY -> start.plusWeeks(step)
            Frequency.MONTHLY -> start.plusMonths(step)
            Frequency.QUARTERLY -> start.plusMonths(step * 3)
            Frequency.YEARLY -> start.plusYears(step)
        }
    }

    fun occurrence(rule: RecurringRule, n: Int) = occurrence(rule.startDate, rule.frequency, rule.interval, n)

    /** Occurrences still to be posted up to and including [upTo], as (index, date). */
    fun due(rule: RecurringRule, upTo: LocalDate, max: Int = MAX_CATCH_UP): List<Pair<Int, LocalDate>> {
        if (!rule.active) return emptyList()
        val out = ArrayList<Pair<Int, LocalDate>>()
        var n = rule.nextIndex
        while (out.size < max) {
            val d = occurrence(rule, n)
            if (d.isAfter(upTo) || (rule.endDate != null && d.isAfter(rule.endDate))) break
            out += n to d
            n++
        }
        return out
    }

    /** First occurrence index on or after [date] — used when a rule is created with a past start date. */
    fun firstIndexOnOrAfter(rule: RecurringRule, date: LocalDate): Int {
        var n = 0
        while (occurrence(rule, n).isBefore(date) && n < 100_000) n++
        return n
    }
}
