package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate

/** One transaction in a standard layout, with the exact source text kept alongside. */
data class StatementRow(
    val date: LocalDate?,
    val dateRaw: String,
    val narration: String,
    val reference: String,
    val debit: BigDecimal?,
    val credit: BigDecimal?,
    val balance: BigDecimal?,
    val balanceRaw: String,
    val source: String,
    val page: Int,
    val flags: List<String> = emptyList(),
)

data class ColumnMapping(val date: Int?, val narration: Int?, val reference: Int?, val debit: Int?, val credit: Int?, val balance: Int?, val amount: Int?, val drCr: Int?) {
    fun describe(header: List<String>?): String {
        fun n(i: Int?) = i?.let { header?.getOrNull(it)?.takeIf { h -> h.isNotBlank() } ?: "column ${it + 1}" } ?: "–"
        return "Date=${n(date)}, Narration=${n(narration)}, Ref=${n(reference)}, " +
            (if (amount != null) "Amount=${n(amount)}${drCr?.let { ", Dr/Cr=${n(it)}" } ?: ""}" else "Debit=${n(debit)}, Credit=${n(credit)}") + ", Balance=${n(balance)}"
    }
}

data class NormalizedStatement(val rows: List<StatementRow>, val mapping: ColumnMapping, val notes: List<String>)

/**
 * Converts extracted bank-statement tables into a standard transaction layout so statements
 * from different banks and months can be combined. Columns are recognised from header names,
 * falling back to column types. Nothing is invented: if a value can't be read, the row is kept
 * with the raw text and a flag.
 */
object StatementNormalizer {
    private val dateNames = listOf("date", "txn date", "transaction date", "value date", "posting date", "tran date")
    private val narrNames = listOf("narration", "description", "particulars", "details", "remarks", "transaction details", "transaction remarks")
    private val refNames = listOf("ref", "chq", "cheque", "reference", "utr", "instrument")
    private val debitNames = listOf("debit", "withdrawal", "withdrawals", "dr", "paid out", "payments")
    private val creditNames = listOf("credit", "deposit", "deposits", "cr", "paid in", "receipts")
    private val balanceNames = listOf("balance", "closing balance", "running balance", "bal")
    private val amountNames = listOf("amount", "txn amount", "transaction amount")
    private val drCrNames = listOf("dr/cr", "cr/dr", "type", "dr / cr", "debit/credit")

    fun mapColumns(t: ExtractedTable): ColumnMapping? {
        val h = t.header?.cells?.map { it.raw.lowercase().replace(Regex("""[^a-z/ ]"""), " ").replace(Regex("""\s+"""), " ").trim() }
        val used = mutableSetOf<Int>()
        fun find(names: List<String>, type: ColumnType? = null): Int? {
            h ?: return null
            val i = h.indices.firstOrNull { i -> i !in used && (type == null || t.columnTypes.getOrNull(i) == type) && names.any { n -> h[i] == n || h[i].startsWith("$n ") || (n.length > 3 && h[i].contains(n)) } }
            i?.let { used.add(it) }
            return i
        }
        var date = find(dateNames)
        // "Value date" columns: prefer the first date column as transaction date.
        val drCr = find(drCrNames)
        var debit = find(debitNames, ColumnType.AMOUNT)
        var credit = find(creditNames, ColumnType.AMOUNT)
        var balance = find(balanceNames, ColumnType.AMOUNT)
        val amount = if (debit == null && credit == null) find(amountNames, ColumnType.AMOUNT) else null
        val ref = find(refNames)
        var narr = find(narrNames)
        // Fallback by column types when headers are missing or unusual.
        val amountCols = t.columnTypes.indices.filter { t.columnTypes[it] == ColumnType.AMOUNT && it !in used }
        if (date == null) date = t.columnTypes.indices.firstOrNull { t.columnTypes[it] == ColumnType.DATE && it !in used }?.also { used.add(it) }
        if (debit == null && credit == null && amount == null && amountCols.size >= 3) { debit = amountCols[0]; credit = amountCols[1]; balance = balance ?: amountCols[2] }
        if (narr == null) narr = t.columnTypes.indices.filter { t.columnTypes[it] == ColumnType.TEXT && it !in used }
            .maxByOrNull { c -> t.bodyRows.sumOf { it.cells.getOrNull(c)?.raw?.length ?: 0 } }
        if (date == null || (debit == null && credit == null && amount == null)) return null
        return ColumnMapping(date, narr, ref, debit, credit, balance, amount, drCr)
    }

    fun normalize(tables: List<ExtractedTable>, style: NumberStyle, order: DateOrder, source: String): NormalizedStatement? {
        val combined = TableExtractor.combine(tables)
        val rows = mutableListOf<StatementRow>()
        val notes = mutableListOf<String>()
        var mapping: ColumnMapping? = null
        for (t in combined) {
            val m = mapColumns(t) ?: continue
            if (mapping == null) { mapping = m; notes.add("Columns recognised: " + m.describe(t.header?.cells?.map { it.raw })) }
            for (r in t.bodyRows) {
                fun cell(i: Int?) = i?.let { r.cells.getOrNull(it)?.raw?.trim() } ?: ""
                val flags = mutableListOf<String>()
                if (r.cells.any { CellFlag.LOW_OCR_CONFIDENCE in it.flags }) flags.add("Low OCR confidence")
                val dateRaw = cell(m.date)
                val date = DateParser.parse(dateRaw, order)
                if (dateRaw.isNotEmpty() && date == null) flags.add("Date not recognised")
                fun amt(i: Int?): BigDecimal? {
                    val raw = cell(i); if (raw.isEmpty()) return null
                    val p = AmountParser.parse(raw, style)
                    if (p == null) { flags.add("Amount \"$raw\" not recognised"); return null }
                    return p.value.abs()
                }
                var debit = amt(m.debit); var credit = amt(m.credit)
                if (m.amount != null) {
                    val raw = cell(m.amount); val p = AmountParser.parse(raw, style)
                    val marker = (cell(m.drCr) + " " + raw).lowercase()
                    when {
                        p == null -> if (raw.isNotEmpty()) flags.add("Amount \"$raw\" not recognised")
                        p.drCr == DrCr.DR || Regex("""\bdr\b|debit""").containsMatchIn(marker) -> debit = p.value.abs()
                        p.drCr == DrCr.CR || Regex("""\bcr\b|credit""").containsMatchIn(marker) -> credit = p.value.abs()
                        p.value.signum() < 0 -> debit = p.value.abs()
                        else -> { flags.add("Debit or credit unclear (single amount column without Dr/Cr)"); credit = null; debit = null }
                    }
                }
                val balRaw = cell(m.balance)
                val balP = AmountParser.parse(balRaw, style)
                // A "Dr" balance (overdraft) is shown negative in the standard layout.
                val bal = balP?.let { if (it.drCr == DrCr.DR) it.value.abs().negate() else it.value }
                if (balRaw.isNotEmpty() && balP == null) flags.add("Balance not recognised")
                if (dateRaw.isEmpty() && debit == null && credit == null) continue // e.g. "Opening balance" lines without a date are skipped from transactions
                rows.add(StatementRow(date, dateRaw, cell(m.narration), cell(m.reference), debit, credit, bal, balRaw, source, r.pageIndex + 1, flags))
            }
        }
        if (mapping == null) return null
        return NormalizedStatement(rows, mapping, notes)
    }

    /**
     * Combines statements, sorted by date (stable: original order within a day and file order),
     * and flags rows that appear in two files (overlapping statement periods) without removing them.
     */
    fun combine(statements: List<NormalizedStatement>): List<StatementRow> {
        val all = statements.flatMapIndexed { fi, s -> s.rows.mapIndexed { ri, r -> Triple(fi, ri, r) } }
        val sorted = all.sortedWith(compareBy({ it.third.date ?: LocalDate.MAX }, { it.first }, { it.second })).map { it.third }
        val seen = HashMap<String, String>()
        return sorted.map { r ->
            val key = listOf(r.date, r.debit?.stripTrailingZeros(), r.credit?.stripTrailingZeros(), r.balance?.stripTrailingZeros(), TextDiff.norm(r.narration).lowercase()).joinToString("|")
            val prev = seen[key]
            if (prev != null && prev != r.source && r.balance != null) r.copy(flags = r.flags + "Possible duplicate – same transaction also in $prev")
            else { seen.putIfAbsent(key, r.source); r }
        }
    }

    /** CSV (UTF-8 with BOM so Excel shows ₹ and Hindi correctly), dates as dd-MM-yyyy, plain numbers. */
    fun toCsv(rows: List<StatementRow>): String {
        fun q(s: String) = if (s.any { it == ',' || it == '"' || it == '\n' }) "\"" + s.replace("\"", "\"\"") + "\"" else s
        val fmt = java.time.format.DateTimeFormatter.ofPattern("dd-MM-yyyy")
        val sb = StringBuilder("﻿Date,Narration,Reference,Debit,Credit,Balance,Source file,Page,Review\n")
        for (r in rows) sb.append(listOf(r.date?.format(fmt) ?: r.dateRaw, r.narration, r.reference, r.debit?.toPlainString() ?: "", r.credit?.toPlainString() ?: "",
            r.balance?.toPlainString() ?: "", r.source, r.page.toString(), r.flags.joinToString("; ")).joinToString(",") { q(it) }).append('\n')
        return sb.toString()
    }

    /** Excel workbook: Transactions, Summary (per file totals and balance checks), Review. */
    fun toSheets(rows: List<StatementRow>, perFile: List<Pair<String, NormalizedStatement>>): List<XSheet> {
        val fmtN = ExcelExport.INDIAN_FORMAT
        fun n(v: BigDecimal?) = v?.let { XCell.Number(it, fmtN) } ?: XCell.Blank
        val head = listOf("Date", "Narration", "Reference", "Debit", "Credit", "Balance", "Source file", "Page", "Review").map { XStyledCell(XCell.Text(it), bold = true) }
        val tx = listOf(head) + rows.map { r ->
            val hl = r.flags.isNotEmpty()
            listOf(
                XStyledCell(r.date?.let { XCell.Date(DateParser.toExcelSerial(it)) } ?: XCell.Text(r.dateRaw), highlight = hl && r.date == null),
                XStyledCell(XCell.Text(r.narration)), XStyledCell(XCell.Text(r.reference)),
                XStyledCell(n(r.debit)), XStyledCell(n(r.credit)), XStyledCell(r.balance?.let { n(it) } ?: if (r.balanceRaw.isNotEmpty()) XCell.Text(r.balanceRaw) else XCell.Blank),
                XStyledCell(XCell.Text(r.source)), XStyledCell(XCell.Number(BigDecimal(r.page))),
                XStyledCell(XCell.Text(r.flags.joinToString("; ")), highlight = hl),
            )
        }
        val summaryHead = listOf("Source file", "Transactions", "Total debit", "Total credit", "First balance", "Last balance", "Balance check", "Columns used").map { XStyledCell(XCell.Text(it), bold = true) }
        val summary = listOf(summaryHead) + perFile.map { (name, st) ->
            val rs = st.rows
            val mism = balanceMismatches(rs)
            listOf(
                XStyledCell(XCell.Text(name)), XStyledCell(XCell.Number(BigDecimal(rs.size))),
                XStyledCell(n(rs.mapNotNull { it.debit }.fold(BigDecimal.ZERO, BigDecimal::add))), XStyledCell(n(rs.mapNotNull { it.credit }.fold(BigDecimal.ZERO, BigDecimal::add))),
                XStyledCell(n(rs.firstOrNull { it.balance != null }?.balance)), XStyledCell(n(rs.lastOrNull { it.balance != null }?.balance)),
                XStyledCell(XCell.Text(when { mism == null -> "Not possible (no balance column)"; mism.isEmpty() -> "All running balances reconcile"; else -> "${mism.size} row(s) do not reconcile: ${mism.take(10).joinToString()}" }), highlight = !mism.isNullOrEmpty()),
                XStyledCell(XCell.Text(st.mapping.describe(null)), wrap = true),
            )
        } + listOf(emptyList(), listOf(XStyledCell(XCell.Text("Checks help find extraction errors but cannot guarantee completeness. Compare totals with the printed statements."), wrap = true)))
        return listOf(
            XSheet("Transactions", tx, listOf(12.0, 50.0, 18.0, 14.0, 14.0, 16.0, 28.0, 6.0, 40.0), freezeTopRow = true),
            XSheet("Summary", summary, listOf(30.0, 12.0, 16.0, 16.0, 16.0, 16.0, 40.0, 60.0)),
        )
    }

    /** 1-based row numbers (within one statement) whose running balance does not reconcile; null if not checkable. */
    fun balanceMismatches(rows: List<StatementRow>): List<Int>? {
        if (rows.none { it.balance != null }) return null
        var prev: BigDecimal? = null
        val fwd = mutableListOf<Int>(); val rev = mutableListOf<Int>()
        rows.forEachIndexed { i, r ->
            val b = r.balance
            if (b != null && prev != null && (r.debit != null || r.credit != null)) {
                val delta = (r.credit ?: BigDecimal.ZERO) - (r.debit ?: BigDecimal.ZERO)
                if ((prev!! + delta - b).abs() > BigDecimal("0.01")) fwd.add(i + 1)
                if ((prev!! - delta - b).abs() > BigDecimal("0.01")) rev.add(i + 1)
            }
            if (b != null) prev = b
        }
        return if (rev.size < fwd.size) rev else fwd
    }
}
