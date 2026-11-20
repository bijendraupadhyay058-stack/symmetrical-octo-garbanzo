package com.docdesk.core

import java.math.BigDecimal

/**
 * Optional consistency checks for statements. They help spot extraction errors; they do not
 * prove that the extraction is complete or correct.
 */
data class FinancialCheckResult(
    val transactionRows: Int,
    val debitColumn: String?,
    val creditColumn: String?,
    val balanceColumn: String?,
    val totalDebit: BigDecimal?,
    val totalCredit: BigDecimal?,
    val balanceRowsChecked: Int,
    /** 1-based row numbers (within the table body) whose running balance does not reconcile. */
    val balanceMismatches: List<Int>,
    val openingBalance: BigDecimal?,
    val closingBalance: BigDecimal?,
    val statementTotalsFound: List<String>,
    val notes: List<String>,
)

object FinancialChecks {
    private val debitNames = listOf("debit", "withdrawal", "withdrawals", "dr", "paid out", "payments", "debit amount", "withdrawal amt")
    private val creditNames = listOf("credit", "deposit", "deposits", "cr", "paid in", "receipts", "credit amount", "deposit amt")
    private val balanceNames = listOf("balance", "closing balance", "running balance", "bal")

    fun run(table: ExtractedTable, style: NumberStyle, statementLines: List<String> = emptyList()): FinancialCheckResult {
        val header = table.header?.cells?.map { it.raw.lowercase().trim() }
        fun find(names: List<String>): Int? {
            header ?: return null
            return header.indexOfFirst { h -> names.any { n -> h == n || h.startsWith("$n ") || h.startsWith("$n.") || h.contains(n) && n.length > 3 } }
                .takeIf { it >= 0 && table.columnTypes.getOrNull(it) == ColumnType.AMOUNT }
        }
        val di = find(debitNames)
        val ci = find(creditNames)
        val bi = find(balanceNames)
        val body = table.bodyRows
        val notes = mutableListOf<String>()
        if (header == null) notes.add("No header row was recognised, so debit/credit/balance columns could not be identified.")

        fun amt(row: TableRow, i: Int?): BigDecimal? = i?.let { row.cells.getOrNull(it)?.raw }?.takeIf { it.isNotBlank() }?.let { AmountParser.parse(it, style)?.value }
        val totalDebit = di?.let { body.mapNotNull { r -> amt(r, di) }.fold(BigDecimal.ZERO) { a, b -> a + b.abs() } }
        val totalCredit = ci?.let { body.mapNotNull { r -> amt(r, ci) }.fold(BigDecimal.ZERO) { a, b -> a + b.abs() } }

        val mismatches = mutableListOf<Int>()
        var checked = 0
        if (bi != null && (di != null || ci != null)) {
            // Determine direction: most statements are credit-increases-balance; some (loan/
            // credit card) are the opposite. Use whichever direction reconciles more rows.
            val pairs = mutableListOf<Triple<Int, BigDecimal, BigDecimal>>() // rowNo, expectedDelta, actualDelta
            var prevBal: BigDecimal? = null
            for ((idx, r) in body.withIndex()) {
                val bal = amt(r, bi)
                val d = amt(r, di)?.abs() ?: BigDecimal.ZERO
                val c = amt(r, ci)?.abs() ?: BigDecimal.ZERO
                if (bal != null && prevBal != null && (d.signum() != 0 || c.signum() != 0)) {
                    pairs.add(Triple(idx + 1, c - d, bal - prevBal))
                }
                if (bal != null) prevBal = bal
            }
            val forward = pairs.count { (_, e, a) -> (e - a).abs() <= BigDecimal("0.01") }
            val reverse = pairs.count { (_, e, a) -> (e.negate() - a).abs() <= BigDecimal("0.01") }
            val sign = if (reverse > forward) -1 else 1
            for ((row, e, a) in pairs) {
                checked++
                val exp = if (sign == 1) e else e.negate()
                if ((exp - a).abs() > BigDecimal("0.01")) mismatches.add(row)
            }
            if (sign == -1) notes.add("Balance moves opposite to credits (typical of loan or credit-card statements).")
        } else notes.add("Running-balance check skipped: debit/credit and balance columns were not all identified.")

        // Look for statement totals in the page text only when they are explicitly labelled.
        val found = mutableListOf<String>()
        var opening: BigDecimal? = null
        var closing: BigDecimal? = null
        val amountRegex = Regex("""\(?-?[₹]?\s?\d[\d,]*\.\d{2}\)?(\s?(Dr|Cr))?""", RegexOption.IGNORE_CASE)
        for (line in statementLines) {
            val l = line.lowercase()
            val value = amountRegex.findAll(line).lastOrNull()?.value?.let { AmountParser.parse(it, style)?.value } ?: continue
            when {
                "opening balance" in l -> { opening = value; found.add(line.trim()) }
                "closing balance" in l -> { closing = value; found.add(line.trim()) }
                l.contains("total") && (l.contains("debit") || l.contains("withdraw") || l.contains("credit") || l.contains("deposit")) -> found.add(line.trim())
            }
        }
        if (opening != null && closing != null && totalDebit != null && totalCredit != null) {
            val expected = opening + totalCredit - totalDebit
            if ((expected - closing).abs() > BigDecimal("0.01")) {
                notes.add("Opening balance + credits − debits = $expected, but the statement shows closing balance $closing. Some rows may be missing or misread.")
            } else notes.add("Opening balance + credits − debits matches the closing balance printed on the statement.")
        }
        return FinancialCheckResult(
            body.size, di?.let { header?.get(it) }, ci?.let { header?.get(it) }, bi?.let { header?.get(it) },
            totalDebit, totalCredit, checked, mismatches, opening, closing, found, notes,
        )
    }
}
