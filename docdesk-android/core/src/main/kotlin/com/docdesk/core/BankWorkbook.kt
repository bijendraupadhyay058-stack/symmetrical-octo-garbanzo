package com.docdesk.core

import java.math.BigDecimal
import java.time.YearMonth
import java.time.format.DateTimeFormatter

/** Page-level processing status for the Processing Report. */
data class PageStatus(val source: String, val page: Int, val type: String, val status: String, val note: String = "")

/** Builds the reviewed bank-statement workbook: Transactions, Monthly Summary, Category Summary, Reconciliation, Exceptions, Processing Report. */
object BankWorkbook {
    private val N = ExcelExport.INDIAN_FORMAT
    private fun t(s: String, bold: Boolean = false, hl: Boolean = false, wrap: Boolean = false) = XStyledCell(XCell.Text(s), bold, hl, wrap)
    private fun n(v: BigDecimal?, bold: Boolean = false, hl: Boolean = false) = XStyledCell(v?.let { XCell.Number(it, N) } ?: XCell.Blank, bold, hl)
    private fun i(v: Int) = XStyledCell(XCell.Number(BigDecimal(v)))
    private fun head(vararg h: String) = h.map { t(it, bold = true) }
    private fun sum(xs: List<BigDecimal?>) = xs.filterNotNull().fold(BigDecimal.ZERO, BigDecimal::add)

    /** Transactions oldest first: files in date order, rows within a file in chronological order. */
    fun ordered(s: ReviewSession): List<ReviewTxn> = s.sources.map { s.chronological(it) }
        .sortedBy { rs -> rs.firstNotNullOfOrNull { it.date } ?: java.time.LocalDate.MAX }.flatten()

    fun build(s: ReviewSession, pages: List<PageStatus>, settingsNotes: List<String>): List<XSheet> {
        val recon = Reconciler.reconcile(s)
        val failed = pages.filter { it.status != "Processed" }.map { it.source to "Page ${it.page}: ${it.status}${if (it.note.isNotEmpty()) " – ${it.note}" else ""}" }
        val ex = Reconciler.exceptions(s, recon, failed)
        val exRows = ex.mapNotNull { it.rowId }.toSet()
        val rows = ordered(s)

        val tx = listOf(head("Date", "Value date", "Description", "Reference", "Debit", "Credit", "Balance", "Category", "Category source", "Source file", "Page", "Review notes", "Edited", "Original extracted text")) +
            rows.map { r ->
                val hl = r.id in exRows
                listOf(
                    r.date?.let { XStyledCell(XCell.Date(DateParser.toExcelSerial(it))) } ?: t(r.dateRaw, hl = true),
                    r.valueDate?.let { XStyledCell(XCell.Date(DateParser.toExcelSerial(it))) } ?: t(r.valueDateRaw),
                    t(r.description), t(r.reference), // text cells keep leading zeroes of references
                    n(r.debit), n(r.credit), r.balance?.let { n(it) } ?: t(r.balanceRaw),
                    t(r.category.label), t(if (r.categorySuggested) "Suggested (not reviewed)" else if (r.category == TxnCategory.UNCATEGORISED) "" else "User"),
                    t(r.source), i(r.page),
                    t((r.flags + if (r.reviewed && r.flags.isNotEmpty()) listOf("reviewed") else emptyList()).joinToString("; "), hl = hl),
                    t(if (s.audit.any { a -> a.rowId == r.id && a.action != "Marked reviewed" } || r.manual) "Yes" else ""),
                    t(r.original),
                )
            }

        // Monthly summary
        val months = rows.filter { it.date != null }.groupBy { YearMonth.from(it.date) }.toSortedMap()
        val mf = DateTimeFormatter.ofPattern("MMM yyyy")
        val monthly = mutableListOf(head("Month", "Transactions", "Total debits", "Total credits", "Net (credits − debits)"))
        months.forEach { (m, rs) -> val d = sum(rs.map { it.debit }); val c = sum(rs.map { it.credit }); monthly.add(listOf(t(m.format(mf)), i(rs.size), n(d), n(c), n(c - d))) }
        val undated = rows.filter { it.date == null }
        if (undated.isNotEmpty()) monthly.add(listOf(t("No date (see Exceptions)", hl = true), i(undated.size), n(sum(undated.map { it.debit })), n(sum(undated.map { it.credit })), XStyledCell(XCell.Blank)))
        monthly.add(listOf(t("Total", bold = true), i(rows.size), n(sum(rows.map { it.debit }), true), n(sum(rows.map { it.credit }), true), n(sum(rows.map { it.credit }) - sum(rows.map { it.debit }), true)))

        // Category summary (+ cash, charges & interest sections)
        val cat = mutableListOf(head("Category", "Transactions", "Total debits", "Total credits", "Of which suggested (not reviewed)"))
        rows.groupBy { it.category }.toSortedMap(compareBy { it.ordinal }).forEach { (c, rs) ->
            cat.add(listOf(t(c.label), i(rs.size), n(sum(rs.map { it.debit })), n(sum(rs.map { it.credit })), i(rs.count { it.categorySuggested })))
        }
        fun section(title: String, cats: List<TxnCategory>) {
            cat.add(emptyList()); cat.add(listOf(t(title, bold = true)))
            cat.add(head("Category", "Transactions", "Total debits", "Total credits"))
            cats.forEach { c -> val rs = rows.filter { it.category == c }; cat.add(listOf(t(c.label), i(rs.size), n(sum(rs.map { it.debit })), n(sum(rs.map { it.credit })))) }
        }
        section("Cash deposits and withdrawals", listOf(TxnCategory.CASH_DEPOSIT, TxnCategory.CASH_WITHDRAWAL))
        section("Bank charges and interest", listOf(TxnCategory.BANK_CHARGES, TxnCategory.INTEREST_RECEIVED, TxnCategory.INTEREST_PAID))
        cat.add(emptyList()); cat.add(listOf(t("These are summary tables, not Excel PivotTables. Suggested categories come from keywords in the narration and may be wrong.", wrap = true)))

        // Reconciliation
        val rec = mutableListOf(head("Statement", "Check", "Amount", "Status", "Notes"))
        rec.add(listOf(t("All"), t("Statement order"), XStyledCell(XCell.Blank), t(if (s.orderConfirmed) "OK" else CheckStatus.INCOMPLETE.label, hl = !s.orderConfirmed), t(s.order.label)))
        recon.forEach { f -> f.lines.forEach { l -> rec.add(listOf(t(f.source), t(l.label), if (l.label == "Running-balance checks") i(l.value?.toInt() ?: 0) else n(l.value), t(l.status.label, hl = l.status == CheckStatus.DIFFERENCE || l.status == CheckStatus.INCOMPLETE), t(l.note, wrap = true))) } }
        rec.add(emptyList())
        rec.add(listOf(t("Formula: Opening balance + Total credits − Total debits = Calculated closing balance.", wrap = true)))
        rec.add(listOf(t("A balance check that agrees does not prove that every transaction was extracted correctly – compare with the printed statement.", wrap = true)))

        // Exceptions
        val exs = mutableListOf(head("Row", "Source file", "Page", "Type", "Details"))
        ex.forEach { e -> exs.add(listOf(e.rowId?.let { i(it) } ?: XStyledCell(XCell.Blank), t(e.source), e.page?.let { i(it) } ?: XStyledCell(XCell.Blank), t(e.kind, hl = true), t(e.detail, wrap = true))) }
        if (ex.isEmpty()) exs.add(listOf(t("No open exceptions.")))

        // Processing report
        val pr = mutableListOf(head("Source file", "Page", "Page type", "Status", "Notes"))
        pages.forEach { p -> pr.add(listOf(t(p.source), i(p.page), t(p.type), t(p.status, hl = p.status != "Processed"), t(p.note, wrap = true))) }
        pr.add(emptyList()); pr.add(listOf(t("Settings", bold = true)))
        settingsNotes.forEach { pr.add(listOf(t(it, wrap = true))) }
        pr.add(emptyList()); pr.add(head("#", "Row", "Action", "Details"))
        s.audit.forEach { a -> pr.add(listOf(i(a.seq), a.rowId?.let { i(it) } ?: XStyledCell(XCell.Blank), t(a.action), t(a.detail, wrap = true))) }
        if (s.audit.isEmpty()) pr.add(listOf(t("No manual corrections.")))

        return listOf(
            XSheet("Transactions", tx, listOf(12.0, 12.0, 48.0, 20.0, 14.0, 14.0, 16.0, 22.0, 20.0, 26.0, 6.0, 40.0, 8.0, 60.0), freezeTopRow = true, autoFilter = true),
            XSheet("Monthly Summary", monthly, listOf(16.0, 13.0, 16.0, 16.0, 20.0), freezeTopRow = true),
            XSheet("Category Summary", cat, listOf(30.0, 13.0, 16.0, 16.0, 22.0), freezeTopRow = true),
            XSheet("Reconciliation", rec, listOf(28.0, 28.0, 16.0, 26.0, 60.0), freezeTopRow = true),
            XSheet("Exceptions", exs, listOf(8.0, 28.0, 7.0, 20.0, 70.0), freezeTopRow = true, autoFilter = ex.isNotEmpty()),
            XSheet("Processing Report", pr, listOf(28.0, 8.0, 20.0, 24.0, 60.0)),
        )
    }
}
