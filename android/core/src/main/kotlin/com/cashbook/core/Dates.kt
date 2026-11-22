package com.cashbook.core

import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.temporal.TemporalAdjusters

/** Supported display formats. DD-MM-YYYY is the default. */
enum class DateFormatOption(val pattern: String) {
    DD_MM_YYYY("dd-MM-yyyy"),
    DD_SLASH_MM_YYYY("dd/MM/yyyy"),
    DD_MMM_YYYY("dd MMM yyyy"),
    YYYY_MM_DD("yyyy-MM-dd");

    val formatter: DateTimeFormatter get() = DateTimeFormatter.ofPattern(pattern)
    fun format(date: LocalDate): String = date.format(formatter)
}

data class DateRange(val start: LocalDate, val end: LocalDate) {
    init { require(!end.isBefore(start)) { "end before start" } }
    operator fun contains(d: LocalDate) = !d.isBefore(start) && !d.isAfter(end)
    fun months(): List<YearMonth> {
        val out = ArrayList<YearMonth>()
        var m = YearMonth.from(start)
        val last = YearMonth.from(end)
        while (!m.isAfter(last)) { out.add(m); m = m.plusMonths(1) }
        return out
    }
    fun days(): Sequence<LocalDate> = generateSequence(start) { it.plusDays(1) }.takeWhile { !it.isAfter(end) }
    fun label(fmt: DateFormatOption): String =
        if (start == end) fmt.format(start) else "${fmt.format(start)} to ${fmt.format(end)}"
}

/** Indian financial year: 1 April to 31 March. `startYear` 2026 means FY 2026-27. */
data class FinancialYear(val startYear: Int) {
    val range: DateRange get() = DateRange(LocalDate.of(startYear, 4, 1), LocalDate.of(startYear + 1, 3, 31))
    val label: String get() = "FY $startYear-" + ((startYear + 1) % 100).toString().padStart(2, '0')
    fun previous() = FinancialYear(startYear - 1)

    companion object {
        fun of(date: LocalDate): FinancialYear =
            FinancialYear(if (date.monthValue >= 4) date.year else date.year - 1)
    }
}

enum class PeriodPreset { TODAY, THIS_WEEK, THIS_MONTH, LAST_MONTH, THIS_FY, LAST_FY, THIS_YEAR, ALL_TIME, CUSTOM }

object Periods {
    fun resolve(
        preset: PeriodPreset,
        today: LocalDate,
        weekStart: DayOfWeek = DayOfWeek.MONDAY,
        custom: DateRange? = null,
        earliest: LocalDate? = null,
    ): DateRange = when (preset) {
        PeriodPreset.TODAY -> DateRange(today, today)
        PeriodPreset.THIS_WEEK -> {
            val s = today.with(TemporalAdjusters.previousOrSame(weekStart))
            DateRange(s, s.plusDays(6))
        }
        PeriodPreset.THIS_MONTH -> YearMonth.from(today).let { DateRange(it.atDay(1), it.atEndOfMonth()) }
        PeriodPreset.LAST_MONTH -> YearMonth.from(today).minusMonths(1).let { DateRange(it.atDay(1), it.atEndOfMonth()) }
        PeriodPreset.THIS_FY -> FinancialYear.of(today).range
        PeriodPreset.LAST_FY -> FinancialYear.of(today).previous().range
        PeriodPreset.THIS_YEAR -> DateRange(LocalDate.of(today.year, 1, 1), LocalDate.of(today.year, 12, 31))
        PeriodPreset.ALL_TIME -> DateRange(minOf(earliest ?: today, today), today.plusYears(50).let { maxOf(it, today) })
        PeriodPreset.CUSTOM -> custom ?: DateRange(today, today)
    }
}
