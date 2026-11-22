package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.DayOfWeek
import java.time.LocalDate

class DatesTest {
    @Test fun financialYearRunsAprilToMarch() {
        assertEquals(FinancialYear(2026), FinancialYear.of(LocalDate.of(2026, 4, 1)))
        assertEquals(FinancialYear(2025), FinancialYear.of(LocalDate.of(2026, 3, 31)))
        assertEquals(DateRange(LocalDate.of(2026, 4, 1), LocalDate.of(2027, 3, 31)), FinancialYear(2026).range)
        assertEquals("FY 2026-27", FinancialYear(2026).label)
        assertEquals("FY 2099-00", FinancialYear(2099).label)
    }

    @Test fun presets() {
        val today = LocalDate.of(2026, 11, 22) // Sunday
        assertEquals(DateRange(LocalDate.of(2026, 11, 16), LocalDate.of(2026, 11, 22)), Periods.resolve(PeriodPreset.THIS_WEEK, today, DayOfWeek.MONDAY))
        assertEquals(DateRange(today, LocalDate.of(2026, 11, 28)), Periods.resolve(PeriodPreset.THIS_WEEK, today, DayOfWeek.SUNDAY))
        assertEquals(DateRange(LocalDate.of(2026, 10, 1), LocalDate.of(2026, 10, 31)), Periods.resolve(PeriodPreset.LAST_MONTH, today))
        assertEquals(FinancialYear(2025).range, Periods.resolve(PeriodPreset.LAST_FY, today))
    }

    @Test fun formatDefaultIsDdMmYyyy() {
        assertEquals("05-04-2026", DateFormatOption.DD_MM_YYYY.format(LocalDate.of(2026, 4, 5)))
    }
}
