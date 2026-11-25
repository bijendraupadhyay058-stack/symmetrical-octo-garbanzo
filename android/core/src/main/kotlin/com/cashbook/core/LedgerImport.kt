package com.cashbook.core

import java.time.LocalDate
import java.util.Locale

/**
 * Importing entries kept elsewhere — another cashbook app's CSV export, or a spreadsheet — as income and expense
 * entries. The file is read by [StatementFiles]; this decides which column is which (guessed from the header, the user
 * can change it) and turns each row into an [ImportRow] or a reason it can't be imported.
 */
object LedgerImport {
    enum class Field { DATE, DESCRIPTION, AMOUNT, DEBIT, CREDIT, TYPE, CATEGORY, PARTY, ACCOUNT, MODE, REFERENCE, NOTES }

    /** Column index per field (absent = not in the file). [headerRow] is the row with the column names. */
    data class Mapping(val headerRow: Int, val columns: Map<Field, Int>) {
        operator fun get(f: Field) = columns[f]
        val usable: Boolean get() = Field.DATE in columns && (Field.AMOUNT in columns || Field.DEBIT in columns || Field.CREDIT in columns)
    }

    data class ImportRow(
        val row: Int, val date: LocalDate, val type: TxnType, val amount: Long, val description: String = "",
        val category: String = "", val party: String = "", val account: String = "", val mode: PaymentMode? = null,
        val reference: String = "", val notes: String = "",
    )

    data class Problem(val row: Int, val reason: Reason, val text: String = "")
    enum class Reason { NO_DATE, NO_AMOUNT, ZERO_AMOUNT, TRANSFER, UNKNOWN_TYPE }

    data class Parsed(val rows: List<ImportRow>, val problems: List<Problem>)

    private val keywords: List<Pair<Field, List<String>>> = listOf(
        Field.DATE to listOf("date", "txn date", "transaction date", "entry date", "dated"),
        Field.DEBIT to listOf("debit", "withdrawal", "paid out", "cash out", "expense amount", "out"),
        Field.CREDIT to listOf("credit", "deposit", "paid in", "cash in", "income amount", "in"),
        Field.AMOUNT to listOf("amount", "amt", "value", "total"),
        Field.TYPE to listOf("type", "dr/cr", "cr/dr", "income/expense", "entry type", "transaction type", "in/out"),
        Field.CATEGORY to listOf("category", "head", "account head", "ledger"),
        Field.PARTY to listOf("party", "customer", "supplier", "vendor", "payee", "paid to", "received from", "contact", "name"),
        Field.ACCOUNT to listOf("account", "bank", "wallet", "cash book", "book"),
        Field.MODE to listOf("mode", "payment mode", "payment method", "method"),
        Field.REFERENCE to listOf("reference", "ref", "ref no", "cheque", "chq", "bill no", "invoice no", "voucher", "utr"),
        Field.NOTES to listOf("notes", "note", "comment", "comments", "memo"),
        Field.DESCRIPTION to listOf("description", "desc", "particulars", "particular", "narration", "details", "detail", "remarks", "remark", "item", "purpose"),
    )

    private fun norm(s: String) = s.trim().lowercase(Locale.ROOT).replace(Regex("[.:_]"), " ").replace(Regex("\\s+"), " ").trim()

    /** Which field a column name means: exact keyword first, then "contains" (so "Bank Account" → ACCOUNT, "Cash In" → CREDIT). */
    fun fieldOf(header: String): Field? {
        val h = norm(header)
        if (h.isEmpty()) return null
        keywords.firstOrNull { (_, ks) -> h in ks }?.let { return it.first }
        return keywords.firstOrNull { (_, ks) -> ks.any { k -> k.length > 3 && h.contains(k) } }?.first
    }

    /** Finds the header row (the first with a date column and a money column) and guesses each field's column. */
    fun guess(rows: List<List<String>>): Mapping? {
        for ((i, r) in rows.withIndex().take(40)) {
            val cols = LinkedHashMap<Field, Int>()
            r.forEachIndexed { c, cell -> fieldOf(cell)?.let { f -> cols.putIfAbsent(f, c) } }
            val m = Mapping(i, cols)
            if (m.usable) return m
        }
        return null
    }

    /** "Income", "Credit", "Cr", "In", "Received" → INCOME; "Expense", "Debit", "Dr", "Out", "Paid" → EXPENSE; "Transfer" → TRANSFER. */
    fun typeOf(raw: String): TxnType? = when (norm(raw).removeSuffix(" entry")) {
        "income", "credit", "cr", "in", "cash in", "received", "receipt", "deposit", "+" -> TxnType.INCOME
        "expense", "debit", "dr", "out", "cash out", "paid", "payment", "withdrawal", "-" -> TxnType.EXPENSE
        "transfer", "contra" -> TxnType.TRANSFER
        else -> null
    }

    fun modeOf(raw: String): PaymentMode? = when (norm(raw)) {
        "cash" -> PaymentMode.CASH
        "upi", "gpay", "google pay", "phonepe", "paytm", "bhim" -> PaymentMode.UPI
        "bank", "bank transfer", "neft", "rtgs", "imps", "net banking", "netbanking", "online" -> PaymentMode.BANK_TRANSFER
        "card", "debit card", "credit card" -> PaymentMode.CARD
        "cheque", "check", "chq" -> PaymentMode.CHEQUE
        "" -> null
        else -> PaymentMode.OTHER
    }

    fun parse(rows: List<List<String>>, m: Mapping): Parsed {
        val out = ArrayList<ImportRow>(); val problems = ArrayList<Problem>()
        rows.drop(m.headerRow + 1).forEachIndexed { i, r ->
            val rowNo = m.headerRow + 2 + i
            fun cell(f: Field) = m[f]?.let { r.getOrNull(it) }?.trim().orEmpty()
            if (r.all { it.isBlank() }) return@forEachIndexed
            val desc = cell(Field.DESCRIPTION).replace(Regex("\\s+"), " ")
            val date = StatementImport.parseDate(cell(Field.DATE))
            if (date == null) {
                // totals / opening / closing rows and notes are skipped quietly; a row with an amount but no date is reported
                val summaryRow = r.any { c -> norm(c).let { it == "total" || it == "grand total" || it.startsWith("opening balance") || it.startsWith("closing balance") } }
                if (!summaryRow && (cell(Field.AMOUNT).isNotEmpty() || cell(Field.DEBIT).isNotEmpty() || cell(Field.CREDIT).isNotEmpty()))
                    problems += Problem(rowNo, Reason.NO_DATE, desc)
                return@forEachIndexed
            }
            val signed: Long? = when {
                Field.DEBIT in m.columns || Field.CREDIT in m.columns -> {
                    val dr = StatementImport.parseAmount(cell(Field.DEBIT)) ?: 0L
                    val cr = StatementImport.parseAmount(cell(Field.CREDIT)) ?: 0L
                    if (cell(Field.DEBIT).isEmpty() && cell(Field.CREDIT).isEmpty() && Field.AMOUNT !in m.columns) null
                    else if (dr == 0L && cr == 0L) StatementImport.parseAmount(cell(Field.AMOUNT)) ?: 0L else cr - dr
                }
                else -> StatementImport.parseAmount(cell(Field.AMOUNT))?.let { a ->
                    if (Regex("(?i)dr\\s*$").containsMatchIn(cell(Field.AMOUNT))) -kotlin.math.abs(a) else a
                }
            }
            if (signed == null) { problems += Problem(rowNo, Reason.NO_AMOUNT, desc); return@forEachIndexed }
            if (signed == 0L) { problems += Problem(rowNo, Reason.ZERO_AMOUNT, desc); return@forEachIndexed }
            val typeCell = cell(Field.TYPE)
            val type = if (typeCell.isNotEmpty()) typeOf(typeCell) ?: run { problems += Problem(rowNo, Reason.UNKNOWN_TYPE, typeCell); return@forEachIndexed }
                else if (signed < 0) TxnType.EXPENSE else TxnType.INCOME
            if (type == TxnType.TRANSFER) { problems += Problem(rowNo, Reason.TRANSFER, desc); return@forEachIndexed }
            out += ImportRow(rowNo, date, type, kotlin.math.abs(signed), desc.take(200), cell(Field.CATEGORY), cell(Field.PARTY), cell(Field.ACCOUNT),
                modeOf(cell(Field.MODE)), cell(Field.REFERENCE).take(60), cell(Field.NOTES).take(500))
        }
        return Parsed(out, problems)
    }

    /** Same day, type, amount and description (ignoring case and spacing): already in the books, so skipped. */
    fun isDuplicate(r: ImportRow, existing: List<Txn>, accountId: Long): Boolean = existing.any { t ->
        t.date == r.date && t.type == r.type && t.amount == r.amount && t.accountId == accountId &&
            t.description.trim().replace(Regex("\\s+"), " ").equals(r.description.trim(), ignoreCase = true)
    }
}
