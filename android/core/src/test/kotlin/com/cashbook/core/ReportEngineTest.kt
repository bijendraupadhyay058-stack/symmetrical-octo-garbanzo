package com.cashbook.core

import com.cashbook.core.SampleScenario.accounts
import com.cashbook.core.SampleScenario.categories
import com.cashbook.core.SampleScenario.d
import com.cashbook.core.SampleScenario.txns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReportEngineTest {
    private fun build(type: ReportType, range: DateRange = DateRange(d(1), d(30)), filter: TxnFilter = TxnFilter(), selected: Set<Long> = emptySet()) =
        ReportEngine(ReportInput(type, "Office Cashbook", accounts = accounts, selectedAccountIds = selected, categories = categories,
            parties = emptyMap(), txns = txns, range = range, filter = filter, generatedAt = "now")).build()

    private fun summary(doc: ReportDocument, label: String) = (doc.summary.first { it.label == label }.value as Cell.Amount).paise

    @Test fun monthlySummaryTotalsMatchTransactions() {
        val doc = build(ReportType.MONTHLY_SUMMARY)
        assertEquals(6_000_000L, summary(doc, "Opening balance"))
        assertEquals(1_500_000L, summary(doc, "Income"))
        assertEquals(250_000L, summary(doc, "Expenses"))
        assertEquals(1_250_000L, summary(doc, "Net surplus / (deficit)"))
        assertEquals(7_250_000L, summary(doc, "Closing balance"))
        val totalRow = doc.tables[0].rows.last()
        assertEquals(Cell.Amount(7_250_000), totalRow.cells.last())
    }

    @Test fun openingAndClosingForLaterPeriod() {
        val doc = build(ReportType.ACCOUNT_WISE, DateRange(d(4), d(5)), selected = setOf(SampleScenario.cash.id))
        assertEquals(850_000L, summary(doc, "Opening balance"))
        assertEquals(1_350_000L, summary(doc, "Closing balance"))
        assertEquals(500_000L, summary(doc, "Transfers in"))
    }

    @Test fun dailyCashbookRunsBalanceAcrossDays() {
        val doc = build(ReportType.DAILY_CASHBOOK)
        val days = doc.tables[0].rows.dropLast(1)
        assertEquals(5, days.size) // 1st (openings) + 4 activity days
        assertEquals(Cell.Amount(7_250_000), days.last().cells.last())
        // Transfer day: net transfers zero for the whole cashbook
        assertEquals(Cell.Amount(0), days.last().cells[4])
    }

    @Test fun categoryWisePercentages() {
        val doc = build(ReportType.CATEGORY_WISE)
        val exp = doc.tables[1]
        assertEquals("Printing and stationery", (exp.rows[0].cells[0] as Cell.Text).value)
        assertEquals("60.0%", (exp.rows[0].cells[3] as Cell.Text).value)
        assertEquals(Cell.Amount(250_000), exp.rows.last().cells[2])
    }

    @Test fun transfersExcludedFromIncomeExpenseStatement() {
        val doc = build(ReportType.INCOME_EXPENSE)
        assertEquals(1_500_000L, summary(doc, "Total income"))
        assertEquals(250_000L, summary(doc, "Total expenses"))
        assertEquals(1_250_000L, summary(doc, "Net surplus"))
    }

    @Test fun transferReportListsBothAccounts() {
        val doc = build(ReportType.TRANSFERS)
        val r = doc.tables[0].rows[0]
        assertEquals(Cell.Text("SBI Bank"), r.cells[1])
        assertEquals(Cell.Text("Office Cash"), r.cells[2])
        assertEquals(Cell.Amount(500_000), r.cells[3])
    }

    @Test fun customReportAppliesFilters() {
        val doc = build(ReportType.CUSTOM, filter = TxnFilter(types = setOf(TxnType.EXPENSE)))
        assertEquals(2, doc.tables[0].rows.size - 1)
        assertEquals(2, doc.exportTable.rows.size)
        assertEquals(250_000L, summary(doc, "Expenses"))
        assertEquals(0L, summary(doc, "Income"))
    }

    @Test fun financialYearMonthBreakdown() {
        val doc = build(ReportType.FINANCIAL_YEAR, FinancialYear(2026).range)
        val months = doc.tables[0]
        assertEquals(13, months.rows.size) // 12 months + total
        assertEquals(Cell.Amount(1_500_000), months.rows[0].cells[1])
        assertEquals(Cell.Amount(7_250_000), months.rows.last().cells[4])
        assertTrue(doc.notes.any { it.contains("accrual") })
    }

    @Test fun exportTableHasStandardColumns() {
        val doc = build(ReportType.CUSTOM)
        assertEquals(14, doc.exportTable.columns.size)
        assertEquals(4, doc.exportTable.rows.size)
    }
}
