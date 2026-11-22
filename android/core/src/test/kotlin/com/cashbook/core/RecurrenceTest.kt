package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class RecurrenceTest {
    private fun d(y: Int, m: Int, day: Int) = LocalDate.of(y, m, day)
    private fun rule(start: LocalDate, f: Frequency, interval: Int = 1, end: LocalDate? = null, next: Int = 0, active: Boolean = true) =
        RecurringRule(1, 1, TxnType.EXPENSE, 250_000, 1, categoryId = 5, frequency = f, interval = interval, startDate = start, endDate = end, nextIndex = next, active = active)

    @Test fun monthEndDoesNotDrift() {
        val r = rule(d(2026, 1, 31), Frequency.MONTHLY)
        assertEquals(listOf(d(2026, 1, 31), d(2026, 2, 28), d(2026, 3, 31), d(2026, 4, 30)), (0..3).map { Recurrence.occurrence(r, it) })
        assertEquals(d(2028, 2, 29), Recurrence.occurrence(rule(d(2028, 1, 31), Frequency.MONTHLY), 1))
    }

    @Test fun frequencies() {
        val s = d(2026, 4, 1)
        assertEquals(d(2026, 4, 3), Recurrence.occurrence(rule(s, Frequency.DAILY, 2), 1))
        assertEquals(d(2026, 4, 15), Recurrence.occurrence(rule(s, Frequency.WEEKLY, 2), 1))
        assertEquals(d(2026, 7, 1), Recurrence.occurrence(rule(s, Frequency.QUARTERLY), 1))
        assertEquals(d(2027, 4, 1), Recurrence.occurrence(rule(s, Frequency.YEARLY), 1))
    }

    @Test fun dueCatchesUpAndRespectsEndDateAndProgress() {
        val r = rule(d(2026, 1, 5), Frequency.MONTHLY, end = d(2026, 4, 30))
        assertEquals(listOf(0 to d(2026, 1, 5), 1 to d(2026, 2, 5), 2 to d(2026, 3, 5)), Recurrence.due(r, d(2026, 3, 20)))
        assertEquals(4, Recurrence.due(r, d(2027, 1, 1)).size) // stops at end date
        assertEquals(listOf(3 to d(2026, 4, 5)), Recurrence.due(r.copy(nextIndex = 3), d(2026, 12, 31)))
        assertTrue(Recurrence.due(r.copy(active = false), d(2026, 12, 31)).isEmpty())
        assertNull(r.copy(nextIndex = 4).nextDate)
        assertTrue(r.copy(nextIndex = 4).finished)
    }

    @Test fun catchUpIsCapped() {
        val r = rule(d(2000, 1, 1), Frequency.DAILY)
        assertEquals(Recurrence.MAX_CATCH_UP, Recurrence.due(r, d(2026, 1, 1)).size)
    }

    @Test fun firstIndexOnOrAfter() {
        val r = rule(d(2026, 1, 10), Frequency.MONTHLY)
        assertEquals(3, Recurrence.firstIndexOnOrAfter(r, d(2026, 4, 1)))
        assertEquals(3, Recurrence.firstIndexOnOrAfter(r, d(2026, 4, 10)))
    }

    @Test fun createsLinkedEntry() {
        val t = rule(d(2026, 4, 1), Frequency.MONTHLY).toTxn(d(2026, 5, 1), 7)
        assertEquals(1L, t.recurringId)
        assertEquals(TxnType.EXPENSE, t.type)
        assertEquals(5L, t.categoryId)
        assertEquals(d(2026, 5, 1), t.date)
    }
}
