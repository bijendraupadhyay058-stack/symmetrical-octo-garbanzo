package com.cashbook.core

import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

data class ReportInput(
    val type: ReportType,
    val cashbookName: String,
    val currency: String = "INR",
    /** Accounts of the cashbook(s) in scope, including archived ones. */
    val accounts: List<AccountInfo>,
    /** Accounts the user selected; empty means every account in scope. */
    val selectedAccountIds: Set<Long> = emptySet(),
    val categories: Map<Long, CategoryInfo>,
    val parties: Map<Long, PartyInfo>,
    /** Live (not deleted) entries of the cashbook(s) in scope, any date. */
    val txns: List<Txn>,
    val range: DateRange,
    /** Extra filters (category, party, type, mode, amount, text). Used by detail reports. */
    val filter: TxnFilter = TxnFilter(),
    val filtersLabel: String = "",
    val generatedAt: String,
    val dateFormat: DateFormatOption = DateFormatOption.DD_MM_YYYY,
    val labels: ReportLabels = ReportLabels(),
    val cashbookNames: Map<Long, String> = emptyMap(),
    val locale: Locale = Locale.ENGLISH,
    val txnsWithAttachments: Set<Long> = emptySet(),
)

/**
 * Builds every report from the same ledger rules as the rest of the app, so report totals always
 * match the dashboard and transaction list.
 */
class ReportEngine(private val input: ReportInput) {
    private val l = input.labels
    private val scope: List<AccountInfo> =
        if (input.selectedAccountIds.isEmpty()) input.accounts else input.accounts.filter { it.id in input.selectedAccountIds }
    private val ids: Set<Long> = scope.map { it.id }.toSet()
    private val accountNames = input.accounts.associate { it.id to it.name }
    private val range = input.range

    private val names = object : NameLookup {
        override fun account(id: Long?) = id?.let { accountNames[it] } ?: ""
        override fun category(id: Long?) = categoryName(id)
        override fun party(id: Long?) = id?.let { input.parties[it]?.name } ?: ""
    }

    /** Entries touching the selected accounts (any date), chronological. */
    private val scoped: List<Txn> = input.txns.filter { Ledger.touches(it, ids) }.sortedWith(TxnChronological)
    private val inRange: List<Txn> = scoped.filter { it.date in range }

    /** In-range entries after the detail filters (used by detail reports). */
    private val detail: List<Txn> by lazy {
        TxnQuery.apply(inRange, input.filter.copy(range = null, accountIds = emptySet(), cashbookIds = emptySet()), names, input.txnsWithAttachments)
    }

    fun build(): ReportDocument {
        val (summary, tables, notes) = when (input.type) {
            ReportType.DAILY_CASHBOOK -> daily()
            ReportType.MONTHLY_SUMMARY -> monthly()
            ReportType.YEARLY_SUMMARY -> yearly(includeCategories = false)
            ReportType.FINANCIAL_YEAR -> yearly(includeCategories = true)
            ReportType.CATEGORY_WISE -> categoryWise()
            ReportType.PARTY_WISE -> partyWise()
            ReportType.ACCOUNT_WISE -> accountWise()
            ReportType.INCOME_EXPENSE -> incomeExpense()
            ReportType.TRANSFERS -> transfers()
            ReportType.CUSTOM -> custom()
        }
        val exportTxns = if (input.type.supportsDetailFilters) detail else inRange
        return ReportDocument(
            type = input.type,
            title = l.titles[input.type] ?: input.type.name,
            cashbookName = input.cashbookName,
            periodLabel = range.label(input.dateFormat),
            filtersLabel = input.filtersLabel,
            generatedAt = input.generatedAt,
            currency = input.currency,
            summary = summary,
            tables = tables,
            notes = notes,
            exportTable = exportTable(exportTxns),
            labels = l,
        )
    }

    private data class Parts(val summary: List<SummaryItem>, val tables: List<ReportTable>, val notes: List<String>)

    // ---------- helpers ----------

    private fun categoryName(id: Long?): String {
        val c = id?.let { input.categories[it] } ?: return ""
        val parent = c.parentId?.let { input.categories[it] }
        return if (parent != null) "${parent.name} › ${c.name}" else c.name
    }

    private fun particulars(t: Txn): String = when (t.type) {
        TxnType.TRANSFER -> l.transferArrow.format(names.account(t.accountId), names.account(t.toAccountId)) +
            (if (t.description.isNotBlank()) " · ${t.description}" else "")
        else -> buildString {
            append(t.description.ifBlank { categoryName(t.categoryId) })
            val p = names.party(t.partyId)
            if (p.isNotBlank()) append(" · ").append(p)
        }
    }

    private fun openingTotal(date: java.time.LocalDate) = scope.sumOf { Ledger.balanceBefore(it, input.txns, date) }
    private fun closingTotal(date: java.time.LocalDate) = scope.sumOf { Ledger.balanceAsOf(it, input.txns, date) }
    private fun introducedIn(r: DateRange) = scope.filter { it.openingDate in r }

    private fun balanceSummary(totals: Totals): List<SummaryItem> {
        val opening = openingTotal(range.start)
        val introduced = introducedIn(range).sumOf { it.openingBalance }
        val items = mutableListOf(
            SummaryItem(l.opening, Cell.Amount(opening + introduced)),
            SummaryItem(l.income, Cell.Amount(totals.income)),
            SummaryItem(l.expenses, Cell.Amount(totals.expense)),
            SummaryItem(l.netSurplusOrDeficit, Cell.Amount(totals.net)),
        )
        if (totals.transferIn != totals.transferOut || totals.transferCount > 0) {
            items += SummaryItem(l.transferIn, Cell.Amount(totals.transferIn))
            items += SummaryItem(l.transferOut, Cell.Amount(totals.transferOut))
        }
        items += SummaryItem(l.closing, Cell.Amount(closingTotal(range.end)))
        return items
    }

    private fun accountsTable(): ReportTable {
        val rows = scope.map { acc ->
            val s = Ledger.statement(acc, input.txns, range)
            Row(listOf(Cell.Text(acc.name), Cell.Amount(s.opening + s.openingIntroduced), Cell.Amount(s.totals.income),
                Cell.Amount(s.totals.expense), Cell.Amount(s.totals.transferIn), Cell.Amount(s.totals.transferOut), Cell.Amount(s.closing)))
        }
        val total = Row(listOf(Cell.Text(l.total)) + (1..6).map { i -> Cell.Amount(rows.sumOf { (it.cells[i] as Cell.Amount).paise }) }, RowStyle.TOTAL)
        return ReportTable(l.accountBalances, listOf(
            Column(l.account, 2.2f), Column(l.opening, 1.4f, Align.END), Column(l.income, 1.3f, Align.END),
            Column(l.expenses, 1.3f, Align.END), Column(l.transferIn, 1.3f, Align.END), Column(l.transferOut, 1.3f, Align.END),
            Column(l.closing, 1.4f, Align.END),
        ), rows + total)
    }

    private fun categoryRows(txns: List<Txn>, type: TxnType): Pair<List<Row>, Long> {
        val list = txns.filter { it.type == type }
        val total = list.sumOf { it.amount }
        val rows = list.groupBy { it.categoryId }
            .map { (cat, ts) -> Triple(categoryName(cat).ifBlank { l.uncategorised }, ts.size, ts.sumOf { it.amount }) }
            .sortedByDescending { it.third }
            .map { (name, n, amt) -> Row(listOf(Cell.Text(name), Cell.Count(n), Cell.Amount(amt), Cell.Text(Money.percent(amt, total)))) }
        return rows to total
    }

    private fun categoryTable(title: String, txns: List<Txn>, type: TxnType): ReportTable {
        val (rows, total) = categoryRows(txns, type)
        val count = txns.count { it.type == type }
        return ReportTable(title, listOf(Column(l.category, 3f), Column(l.count, 1.2f, Align.END),
            Column(l.amount, 1.6f, Align.END), Column(l.percent, 1.1f, Align.END)),
            if (rows.isEmpty()) emptyList() else rows + Row(listOf(Cell.Text(l.total), Cell.Count(count), Cell.Amount(total),
                Cell.Text(if (total > 0) "100.0%" else "")), RowStyle.TOTAL))
    }

    private fun monthLabel(m: YearMonth) = m.format(DateTimeFormatter.ofPattern("MMM yyyy", input.locale))

    // ---------- reports ----------

    private fun daily(): Parts {
        val totals = Ledger.totals(inRange, ids)
        val byDay = inRange.groupBy { it.date }
        val introducedByDay = introducedIn(range).groupBy { it.openingDate }
        val days = range.days().filter { it in byDay || it in introducedByDay || range.start == range.end }.toList()

        val summaryRows = ArrayList<Row>()
        val detailRows = ArrayList<Row>()
        for (day in days) {
            val opening = openingTotal(day)
            var bal = opening
            detailRows += Row(listOf(Cell.Day(day), Cell.Text(l.opening), Cell.Empty, Cell.Empty, Cell.Empty, Cell.Amount(opening)), RowStyle.HEADING)
            var intro = 0L
            for (acc in introducedByDay[day].orEmpty()) {
                bal += acc.openingBalance; intro += acc.openingBalance
                detailRows += Row(listOf(Cell.Empty, Cell.Text(l.openingOf.format(acc.name)), Cell.Text(acc.name),
                    Cell.Amount(acc.openingBalance), Cell.Empty, Cell.Amount(bal)))
            }
            val dayTxns = byDay[day].orEmpty()
            for (t in dayTxns) {
                val fromIn = t.accountId in ids
                val toIn = t.toAccountId != null && t.toAccountId in ids
                val (rec, pay) = when (t.type) {
                    TxnType.INCOME -> t.amount to 0L
                    TxnType.EXPENSE -> 0L to t.amount
                    TxnType.TRANSFER -> (if (toIn) t.amount else 0L) to (if (fromIn) t.amount else 0L)
                }
                bal += rec - pay
                val accText = if (t.type == TxnType.TRANSFER) l.transferArrow.format(names.account(t.accountId), names.account(t.toAccountId)) else names.account(t.accountId)
                detailRows += Row(listOf(Cell.Empty, Cell.Text(particulars(t)), Cell.Text(accText),
                    if (rec > 0) Cell.Amount(rec) else Cell.Empty, if (pay > 0) Cell.Amount(pay) else Cell.Empty, Cell.Amount(bal)))
            }
            detailRows += Row(listOf(Cell.Empty, Cell.Text(l.closing), Cell.Empty, Cell.Empty, Cell.Empty, Cell.Amount(bal)), RowStyle.SUBTOTAL)
            val dt = Ledger.totals(dayTxns, ids)
            summaryRows += Row(listOf(Cell.Day(day), Cell.Amount(opening + intro), Cell.Amount(dt.income), Cell.Amount(dt.expense),
                Cell.Amount(dt.transferIn - dt.transferOut), Cell.Amount(bal)))
        }
        if (summaryRows.isNotEmpty()) {
            summaryRows += Row(listOf(Cell.Text(l.total), Cell.Empty, Cell.Amount(totals.income), Cell.Amount(totals.expense),
                Cell.Amount(totals.transferIn - totals.transferOut), Cell.Amount(closingTotal(range.end))), RowStyle.TOTAL)
        }
        val t1 = ReportTable(l.daySummary, listOf(Column(l.date, 1.3f), Column(l.opening, 1.4f, Align.END), Column(l.income, 1.3f, Align.END),
            Column(l.expenses, 1.3f, Align.END), Column(l.transfersNet, 1.3f, Align.END), Column(l.closing, 1.4f, Align.END)), summaryRows)
        val t2 = ReportTable(l.dayDetail, listOf(Column(l.date, 1.2f), Column(l.particulars, 3f), Column(l.account, 1.8f),
            Column(l.receipts, 1.3f, Align.END), Column(l.payments, 1.3f, Align.END), Column(l.balance, 1.4f, Align.END)), detailRows)
        return Parts(balanceSummary(totals), listOf(t1, t2), listOf(l.transferNote))
    }

    private fun monthly(): Parts {
        val totals = Ledger.totals(inRange, ids)
        return Parts(balanceSummary(totals), listOf(
            accountsTable(),
            categoryTable(l.incomeByCategory, inRange, TxnType.INCOME),
            categoryTable(l.expenseByCategory, inRange, TxnType.EXPENSE),
        ), listOf(l.cashBasisNote, l.transferNote))
    }

    private fun yearly(includeCategories: Boolean): Parts {
        val totals = Ledger.totals(inRange, ids)
        val rows = range.months().map { m ->
            val mr = DateRange(maxOf(m.atDay(1), range.start), minOf(m.atEndOfMonth(), range.end))
            val t = Ledger.totals(inRange, ids, mr)
            Row(listOf(Cell.Text(monthLabel(m)), Cell.Amount(t.income), Cell.Amount(t.expense), Cell.Amount(t.net),
                Cell.Amount(closingTotal(mr.end))))
        }
        val total = Row(listOf(Cell.Text(l.total), Cell.Amount(totals.income), Cell.Amount(totals.expense), Cell.Amount(totals.net),
            Cell.Amount(closingTotal(range.end))), RowStyle.TOTAL)
        val tables = mutableListOf(ReportTable(l.monthWise, listOf(Column(l.month, 1.6f), Column(l.income, 1.5f, Align.END),
            Column(l.expenses, 1.5f, Align.END), Column(l.net, 1.5f, Align.END), Column(l.closing, 1.6f, Align.END)), rows + total))
        if (includeCategories) {
            tables += categoryTable(l.incomeByCategory, inRange, TxnType.INCOME)
            tables += categoryTable(l.expenseByCategory, inRange, TxnType.EXPENSE)
        }
        tables += accountsTable()
        return Parts(balanceSummary(totals), tables, listOf(l.cashBasisNote, l.transferNote))
    }

    private fun categoryWise(): Parts {
        val t = Ledger.totals(detail, ids)
        return Parts(listOf(
            SummaryItem(l.totalIncome, Cell.Amount(t.income)),
            SummaryItem(l.totalExpenses, Cell.Amount(t.expense)),
            SummaryItem(l.netSurplusOrDeficit, Cell.Amount(t.net)),
        ), listOf(categoryTable(l.incomeByCategory, detail, TxnType.INCOME), categoryTable(l.expenseByCategory, detail, TxnType.EXPENSE)),
            listOf(l.cashBasisNote))
    }

    private fun partyWise(): Parts {
        val rows = ArrayList<Row>()
        val withParty = detail.filter { it.partyId != null && it.type != TxnType.TRANSFER }
        val groups = withParty.groupBy { it.partyId!! }.toList().sortedBy { names.party(it.first).lowercase() }
        var inc = 0L; var exp = 0L
        for ((pid, ts) in groups) {
            rows += Row(listOf(Cell.Text(names.party(pid)), Cell.Empty, Cell.Empty, Cell.Empty, Cell.Empty), RowStyle.HEADING)
            var pi = 0L; var pe = 0L
            for (t in ts) {
                if (t.type == TxnType.INCOME) pi += t.amount else pe += t.amount
                rows += Row(listOf(Cell.Day(t.date), Cell.Text(t.description.ifBlank { categoryName(t.categoryId) }),
                    Cell.Text(l.types[t.type] ?: ""), if (t.type == TxnType.INCOME) Cell.Amount(t.amount) else Cell.Empty,
                    if (t.type == TxnType.EXPENSE) Cell.Amount(t.amount) else Cell.Empty))
            }
            rows += Row(listOf(Cell.Empty, Cell.Text(l.totalTransactions.format(ts.size)), Cell.Empty, Cell.Amount(pi), Cell.Amount(pe)), RowStyle.SUBTOTAL)
            inc += pi; exp += pe
        }
        if (rows.isNotEmpty()) rows += Row(listOf(Cell.Text(l.total), Cell.Text(l.totalTransactions.format(withParty.size)), Cell.Empty,
            Cell.Amount(inc), Cell.Amount(exp)), RowStyle.TOTAL)
        return Parts(listOf(SummaryItem(l.income, Cell.Amount(inc)), SummaryItem(l.expenses, Cell.Amount(exp)),
            SummaryItem(l.count, Cell.Count(withParty.size))),
            listOf(ReportTable(null, listOf(Column(l.date, 1.2f), Column(l.description, 3f), Column(l.type, 1.1f),
                Column(l.income, 1.4f, Align.END), Column(l.expense, 1.4f, Align.END)), rows)), listOf(l.partyNote))
    }

    private fun accountWise(): Parts {
        val totals = Ledger.totals(inRange, ids)
        val tables = mutableListOf(accountsTable())
        for (acc in scope) {
            val s = Ledger.statement(acc, input.txns, range)
            var bal = s.opening
            val rows = ArrayList<Row>()
            rows += Row(listOf(Cell.Day(range.start), Cell.Text(l.opening), Cell.Empty, Cell.Empty, Cell.Empty, Cell.Amount(bal)), RowStyle.HEADING)
            if (s.openingIntroduced != 0L) {
                bal += s.openingIntroduced
                rows += Row(listOf(Cell.Day(acc.openingDate), Cell.Text(l.openingOf.format(acc.name)), Cell.Empty,
                    Cell.Amount(s.openingIntroduced), Cell.Empty, Cell.Amount(bal)))
            }
            for (t in inRange.filter { Ledger.touches(it, setOf(acc.id)) }) {
                val e = Ledger.effect(t, acc.id)
                bal += e
                rows += Row(listOf(Cell.Day(t.date), Cell.Text(particulars(t)), Cell.Text(l.types[t.type] ?: ""),
                    if (e > 0) Cell.Amount(e) else Cell.Empty, if (e < 0) Cell.Amount(-e) else Cell.Empty, Cell.Amount(bal)))
            }
            rows += Row(listOf(Cell.Day(range.end), Cell.Text(l.closing), Cell.Empty, Cell.Amount(s.totals.income + s.totals.transferIn + s.openingIntroduced),
                Cell.Amount(s.totals.expense + s.totals.transferOut), Cell.Amount(s.closing)), RowStyle.TOTAL)
            tables += ReportTable(acc.name, listOf(Column(l.date, 1.2f), Column(l.particulars, 3f), Column(l.type, 1.1f),
                Column(l.receipts, 1.3f, Align.END), Column(l.payments, 1.3f, Align.END), Column(l.balance, 1.4f, Align.END)), rows)
        }
        return Parts(balanceSummary(totals), tables, listOf(l.transferNote))
    }

    private fun incomeExpense(): Parts {
        val t = Ledger.totals(detail, ids)
        val (inc, incTotal) = categoryRows(detail, TxnType.INCOME)
        val (exp, expTotal) = categoryRows(detail, TxnType.EXPENSE)
        fun two(r: Row) = Row(listOf(r.cells[0], r.cells[2]), r.style)
        val rows = ArrayList<Row>()
        rows += Row(listOf(Cell.Text(l.income), Cell.Empty), RowStyle.HEADING)
        rows += inc.map(::two)
        rows += Row(listOf(Cell.Text(l.totalIncome), Cell.Amount(incTotal)), RowStyle.SUBTOTAL)
        rows += Row(listOf(Cell.Text(l.expenses), Cell.Empty), RowStyle.HEADING)
        rows += exp.map(::two)
        rows += Row(listOf(Cell.Text(l.totalExpenses), Cell.Amount(expTotal)), RowStyle.SUBTOTAL)
        val net = incTotal - expTotal
        rows += Row(listOf(Cell.Text(if (net >= 0) l.netSurplus else l.netDeficit), Cell.Amount(net)), RowStyle.TOTAL)
        return Parts(listOf(SummaryItem(l.totalIncome, Cell.Amount(t.income)), SummaryItem(l.totalExpenses, Cell.Amount(t.expense)),
            SummaryItem(if (net >= 0) l.netSurplus else l.netDeficit, Cell.Amount(net))),
            listOf(ReportTable(null, listOf(Column(l.particulars, 4f), Column(l.amount, 1.6f, Align.END)), rows)),
            listOf(l.cashBasisNote, l.transferNote))
    }

    private fun transfers(): Parts {
        val list = inRange.filter { it.type == TxnType.TRANSFER }
        val rows = list.map { t ->
            Row(listOf(Cell.Day(t.date), Cell.Text(names.account(t.accountId)), Cell.Text(names.account(t.toAccountId)),
                Cell.Amount(t.amount), Cell.Text(t.reference), Cell.Text(t.description)))
        }
        val total = list.sumOf { it.amount }
        return Parts(listOf(SummaryItem(l.count, Cell.Count(list.size)), SummaryItem(l.total, Cell.Amount(total))),
            listOf(ReportTable(null, listOf(Column(l.date, 1.2f), Column(l.from, 1.8f), Column(l.to, 1.8f), Column(l.amount, 1.4f, Align.END),
                Column(l.reference, 1.4f), Column(l.description, 2.2f)),
                if (rows.isEmpty()) rows else rows + Row(listOf(Cell.Text(l.total), Cell.Empty, Cell.Empty, Cell.Amount(total), Cell.Empty, Cell.Empty), RowStyle.TOTAL))),
            listOf(l.transferNote))
    }

    private fun custom(): Parts {
        val t = Ledger.totals(detail, ids)
        var inc = 0L; var exp = 0L; var tr = 0L
        val rows = detail.map { x ->
            when (x.type) { TxnType.INCOME -> inc += x.amount; TxnType.EXPENSE -> exp += x.amount; TxnType.TRANSFER -> tr += x.amount }
            Row(listOf(Cell.Day(x.date), Cell.Text(l.types[x.type] ?: ""),
                Cell.Text(if (x.type == TxnType.TRANSFER) l.transferArrow.format(names.account(x.accountId), names.account(x.toAccountId)) else names.account(x.accountId)),
                Cell.Text(categoryName(x.categoryId)), Cell.Text(names.party(x.partyId)), Cell.Text(x.description),
                Cell.Text(l.modes[x.paymentMode] ?: ""), Cell.Text(x.reference),
                if (x.type == TxnType.INCOME) Cell.Amount(x.amount) else Cell.Empty,
                if (x.type == TxnType.EXPENSE) Cell.Amount(x.amount) else Cell.Empty,
                if (x.type == TxnType.TRANSFER) Cell.Amount(x.amount) else Cell.Empty))
        }
        val total = Row(listOf(Cell.Text(l.total), Cell.Empty, Cell.Empty, Cell.Empty, Cell.Empty, Cell.Text(l.totalTransactions.format(detail.size)),
            Cell.Empty, Cell.Empty, Cell.Amount(inc), Cell.Amount(exp), Cell.Amount(tr)), RowStyle.TOTAL)
        return Parts(listOf(SummaryItem(l.income, Cell.Amount(t.income)), SummaryItem(l.expenses, Cell.Amount(t.expense)),
            SummaryItem(l.netSurplusOrDeficit, Cell.Amount(t.net)), SummaryItem(l.transfers, Cell.Amount(tr)),
            SummaryItem(l.count, Cell.Count(detail.size))),
            listOf(ReportTable(null, listOf(Column(l.date, 1.1f), Column(l.type, 0.9f), Column(l.account, 1.5f), Column(l.category, 1.4f),
                Column(l.party, 1.3f), Column(l.description, 1.8f), Column(l.mode, 1f), Column(l.reference, 1.1f),
                Column(l.income, 1.2f, Align.END), Column(l.expense, 1.2f, Align.END), Column(l.transfer, 1.2f, Align.END)),
                if (rows.isEmpty()) rows else rows + total)),
            listOf(l.cashBasisNote))
    }

    private fun exportTable(txns: List<Txn>): ReportTable {
        val cols = listOf(l.date, l.type, l.cashbook, l.account, l.category, l.party, l.description, l.mode, l.reference,
            l.income, l.expense, l.transferSource, l.transferDestination, l.amount)
            .mapIndexed { i, s -> Column(s, 1f, if (i in setOf(9, 10, 13)) Align.END else Align.START) }
        val rows = txns.map { t ->
            Row(listOf(Cell.Day(t.date), Cell.Text(l.types[t.type] ?: ""), Cell.Text(input.cashbookNames[t.cashbookId] ?: input.cashbookName),
                Cell.Text(names.account(t.accountId)), Cell.Text(categoryName(t.categoryId)), Cell.Text(names.party(t.partyId)),
                Cell.Text(t.description), Cell.Text(l.modes[t.paymentMode] ?: ""), Cell.Text(t.reference),
                if (t.type == TxnType.INCOME) Cell.Amount(t.amount) else Cell.Empty,
                if (t.type == TxnType.EXPENSE) Cell.Amount(t.amount) else Cell.Empty,
                if (t.type == TxnType.TRANSFER) Cell.Text(names.account(t.accountId)) else Cell.Empty,
                if (t.type == TxnType.TRANSFER) Cell.Text(names.account(t.toAccountId)) else Cell.Empty,
                Cell.Amount(t.amount)))
        }
        return ReportTable("Transactions", cols, rows)
    }
}
