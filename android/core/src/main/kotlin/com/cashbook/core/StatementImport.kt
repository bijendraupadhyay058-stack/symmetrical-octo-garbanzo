package com.cashbook.core

import java.math.BigDecimal
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeFormatterBuilder
import java.util.Locale

/** One line of a bank statement. [amount] is signed from the account's side: credit (money in) +, debit −. */
data class StatementLine(val row: Int, val date: LocalDate, val description: String, val reference: String, val amount: Long, val balance: Long? = null)

/**
 * Reads bank statements exported as CSV (or tab / semicolon separated text). Indian banks differ in layout, so the
 * header row is found by its column names and each column is recognised by keywords:
 *  - date: "Txn Date", "Transaction Date", "Date", "Value Date" (the first date column wins);
 *  - description: "Narration", "Description", "Particulars", "Remarks", "Details";
 *  - reference: "Ref No", "Chq / Ref No", "Cheque No", "UTR";
 *  - money: either "Withdrawal / Debit" + "Deposit / Credit" columns, or one "Amount" column that is signed or
 *    paired with a "Dr/Cr" (or "Type") column;
 *  - "Balance" (optional; gives the closing balance).
 * Rows above the header (account details) and rows that aren't transactions (totals, blank lines) are skipped.
 */
object StatementImport {
    data class Result(val lines: List<StatementLine>, val skipped: Int, val closingBalance: Long?) {
        val lastDate: LocalDate? get() = lines.maxOfOrNull { it.date }
    }

    class FormatException(message: String) : Exception(message)

    fun parse(text: String): Result {
        val rows = splitRows(text.removePrefix("﻿"))
        val headerIndex = rows.indexOfFirst { r -> r.any { isDateHeader(it) } && r.any { isMoneyHeader(it) } }
        if (headerIndex < 0) throw FormatException("No header row with a date and an amount column")
        val header = rows[headerIndex].map { norm(it) }
        fun col(vararg keys: String, exclude: (String) -> Boolean = { false }) = header.indexOfFirst { h -> !exclude(h) && keys.any { k -> h.contains(k) } }
        val date = header.indexOfFirst { isDateHeader(it) }
        val desc = col("narration", "description", "particular", "remark", "detail")
        val ref = col("ref", "chq", "cheque", "utr")
        val debit = col("withdrawal", "debit", "dr amount", "paid out") { it == "dr/cr" || it == "type" || it.contains("cr/dr") }
        val credit = col("deposit", "credit", "cr amount", "paid in") { it == "dr/cr" || it == "type" || it.contains("cr/dr") }
        val amount = col("amount") { it.contains("withdrawal") || it.contains("deposit") || it.contains("debit") || it.contains("credit") }
        val drcr = header.indexOfFirst { it == "dr/cr" || it == "cr/dr" || it == "type" || it == "dr / cr" || it == "transaction type" }
        val balance = col("balance")
        if (debit < 0 && credit < 0 && amount < 0) throw FormatException("No amount columns")

        val out = ArrayList<StatementLine>()
        var skipped = 0
        rows.drop(headerIndex + 1).forEachIndexed { i, r ->
            if (r.all { it.isBlank() }) return@forEachIndexed
            val d = r.getOrNull(date)?.let { parseDate(it) }
            val signed: Long? = when {
                debit >= 0 || credit >= 0 -> {
                    val dr = r.getOrNull(debit)?.let { parseAmount(it) } ?: 0L
                    val cr = r.getOrNull(credit)?.let { parseAmount(it) } ?: 0L
                    if (dr == 0L && cr == 0L) null else cr - dr
                }
                else -> r.getOrNull(amount)?.let { raw ->
                    val a = parseAmount(raw) ?: return@let null
                    val flag = (r.getOrNull(drcr) ?: "") + " " + raw
                    val isDebit = Regex("\\b(dr|debit|d)\\b", RegexOption.IGNORE_CASE).containsMatchIn(flag.replace(".", ""))
                    val isCredit = Regex("\\b(cr|credit|c)\\b", RegexOption.IGNORE_CASE).containsMatchIn(flag.replace(".", ""))
                    when { a < 0 -> a; isDebit && !isCredit -> -a; else -> a }
                }
            }
            if (d == null || signed == null || signed == 0L) { skipped++; return@forEachIndexed }
            out += StatementLine(headerIndex + 2 + i, d, r.getOrNull(desc)?.trim().orEmpty().replace(Regex("\\s+"), " "),
                r.getOrNull(ref)?.trim().orEmpty().takeUnless { it == "-" || it.all { c -> c == '0' } }.orEmpty(),
                signed, r.getOrNull(balance)?.let { parseBalance(it) })
        }
        if (out.isEmpty()) throw FormatException("No transactions found")
        // statements come newest-first or oldest-first: the closing balance is on the chronologically last row
        val descending = out.first().date.isAfter(out.last().date)
        val chronological = if (descending) out.reversed() else out
        return Result(chronological, skipped, chronological.last().balance)
    }

    private fun norm(s: String) = s.trim().lowercase(Locale.ROOT).replace(Regex("\\s+"), " ").replace(".", "")
    /** "Date", "Txn Date", "Transaction Date", "Value Date", "Date of transaction" … (short cells only, so account notes don't count). */
    private fun isDateHeader(s: String) = norm(s).let { h -> h.length <= 25 && (h == "date" || h.endsWith(" date") || h.startsWith("date")) }
    private fun isMoneyHeader(s: String) = norm(s).let { h -> listOf("amount", "withdrawal", "deposit", "debit", "credit").any { h.contains(it) } }

    /** "1,23,456.78", "₹ 500", "(250.00)", "500.00 Dr", "-75" → paise (debit markers aren't applied here). */
    fun parseAmount(raw: String): Long? {
        var t = raw.trim().replace("₹", "").replace("INR", "", ignoreCase = true).replace(",", "").replace(" ", "")
        t = t.replace(Regex("(?i)(dr|cr)$"), "")
        if (t.isEmpty() || t == "-") return null
        val neg = t.startsWith("(") && t.endsWith(")") || t.startsWith("-")
        t = t.trim('(', ')').removePrefix("-")
        return runCatching { BigDecimal(t).movePointRight(2).setScale(0, java.math.RoundingMode.HALF_UP).longValueExact() }.getOrNull()?.let { if (neg) -it else it }
    }

    /** A balance can be marked "Dr" when the account is overdrawn. */
    private fun parseBalance(raw: String): Long? = parseAmount(raw)?.let { if (Regex("(?i)dr\\s*$").containsMatchIn(raw.trim())) -kotlin.math.abs(it) else it }

    private val datePatterns = listOf("dd/MM/yyyy", "dd-MM-yyyy", "dd.MM.yyyy", "dd/MM/yy", "dd-MM-yy", "yyyy-MM-dd", "dd-MMM-yyyy", "dd MMM yyyy",
        "dd-MMM-yy", "dd MMM yy", "d/M/yyyy", "d-M-yyyy", "d MMM yyyy").map {
        DateTimeFormatterBuilder().parseCaseInsensitive().appendPattern(it).toFormatter(Locale.ENGLISH)
    }

    /** Dates as Indian banks print them (day first). A time after the date ("01/04/2026 10:15") is ignored. */
    fun parseDate(raw: String): LocalDate? {
        val t = raw.trim().split(Regex("\\s+(?=\\d{1,2}:)"))[0].trim()
        if (t.isEmpty()) return null
        for (f in datePatterns) runCatching { return LocalDate.parse(t, f).let { if (it.year < 100) it.plusYears(2000) else it } }
        return null
    }

    /** Splits CSV text into rows of cells: quoted cells, doubled quotes, and comma / tab / semicolon separators. */
    fun splitRows(text: String): List<List<String>> {
        val firstLines = text.lineSequence().take(30).toList()
        val sep = listOf(',', '\t', ';').maxBy { c -> firstLines.sumOf { l -> l.count { it == c } } }
        val rows = ArrayList<List<String>>()
        var row = ArrayList<String>(); val cell = StringBuilder(); var quoted = false; var i = 0
        while (i < text.length) {
            val c = text[i]
            when {
                quoted && c == '"' && i + 1 < text.length && text[i + 1] == '"' -> { cell.append('"'); i++ }
                c == '"' -> quoted = !quoted
                !quoted && c == sep -> { row += cell.toString(); cell.clear() }
                !quoted && (c == '\n' || c == '\r') -> {
                    if (c == '\r' && i + 1 < text.length && text[i + 1] == '\n') i++
                    row += cell.toString(); cell.clear(); rows += row; row = ArrayList()
                }
                else -> cell.append(c)
            }
            i++
        }
        if (cell.isNotEmpty() || row.isNotEmpty()) { row += cell.toString(); rows += row }
        return rows
    }
}

/** A statement line paired with the Cashbook entry it most likely is. */
data class StatementMatch(val line: StatementLine, val txn: Txn)

object StatementMatcher {
    /**
     * Like [match], but statement lines that match an entry already cleared on [accountId] (an earlier reconciliation,
     * or an overlapping statement) are dropped first, so they're never offered as "missing" and added twice.
     */
    fun matchForReconcile(lines: List<StatementLine>, txns: List<Txn>, account: AccountInfo, upTo: LocalDate): Pair<List<StatementMatch>, List<StatementLine>> {
        val inPeriod = lines.filter { !it.date.isAfter(upTo) }
        val cleared = txns.filter { Ledger.touches(it, setOf(account.id)) && Reconcile.isCleared(it, account.id) }
        val (alreadyCleared, _) = match(inPeriod, cleared, account.id)
        val done = alreadyCleared.map { it.line.row }.toSet()
        return match(inPeriod.filter { it.row !in done }, Reconcile.uncleared(account, txns, upTo), account.id)
    }

    /** How far apart the bank's date and the entry's date may be (cheques and card settlements take a few days). */
    const val DAY_WINDOW = 4L

    /**
     * Pairs statement lines with uncleared entries of [accountId] that have exactly the same signed amount and a date
     * within [DAY_WINDOW] days. Closest dates win; a matching reference number wins over date. Each entry and line is
     * used at most once.
     */
    fun match(lines: List<StatementLine>, candidates: List<Txn>, accountId: Long): Pair<List<StatementMatch>, List<StatementLine>> {
        data class Option(val line: StatementLine, val txn: Txn, val score: Long)
        val options = lines.flatMap { l ->
            candidates.filter { Ledger.effect(it, accountId) == l.amount }.mapNotNull { t ->
                val days = kotlin.math.abs(java.time.temporal.ChronoUnit.DAYS.between(t.date, l.date))
                if (days > DAY_WINDOW) null
                else {
                    val refHit = l.reference.length >= 4 && t.reference.isNotBlank() &&
                        (l.reference.contains(t.reference.trim(), true) || t.reference.contains(l.reference, true) || l.description.contains(t.reference.trim(), true))
                    Option(l, t, days * 10 - if (refHit) 100 else 0)
                }
            }
        }.sortedWith(compareBy({ it.score }, { it.line.row }, { it.txn.id }))
        val usedLines = HashSet<Int>(); val usedTxns = HashSet<Long>()
        val matched = ArrayList<StatementMatch>()
        for (o in options) if (o.line.row !in usedLines && o.txn.id !in usedTxns) { usedLines += o.line.row; usedTxns += o.txn.id; matched += StatementMatch(o.line, o.txn) }
        return matched.sortedBy { it.line.date } to lines.filter { it.row !in usedLines }
    }
}
