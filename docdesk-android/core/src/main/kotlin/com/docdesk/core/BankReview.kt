package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Transaction categories for summaries. Automatic choices are only ever suggestions. */
enum class TxnCategory(val label: String) {
    CASH_DEPOSIT("Cash deposit"), CASH_WITHDRAWAL("Cash withdrawal"), BANK_CHARGES("Bank charges"),
    INTEREST_RECEIVED("Interest received"), INTEREST_PAID("Interest paid"),
    UPI_RECEIPT("UPI receipt"), UPI_PAYMENT("UPI payment"), CHEQUE_DEPOSIT("Cheque deposit"), CHEQUE_PAYMENT("Cheque payment"),
    CUSTOMER_RECEIPT("Customer receipt"), SUPPLIER_PAYMENT("Supplier payment"), SALARY("Salary and wages"),
    TAXES("Taxes and statutory payments"), LOAN_RECEIPT("Loan receipt"), LOAN_REPAYMENT("Loan repayment"),
    OWN_TRANSFER("Transfer between own accounts"), OTHER("Other"), UNCATEGORISED("Uncategorised"),
}

/** Keyword-based category suggestions from the narration. Never final: the user reviews them. */
object Categoriser {
    private fun has(n: String, vararg words: String) = words.any { w -> Regex("""(?<![A-Z])${Regex.escape(w)}(?![A-Z])""").containsMatchIn(n) }

    fun suggest(narration: String, debit: BigDecimal?, credit: BigDecimal?): TxnCategory? {
        val n = narration.uppercase()
        val out = debit != null && debit.signum() > 0 && (credit == null || credit.signum() == 0)
        val inn = credit != null && credit.signum() > 0 && (debit == null || debit.signum() == 0)
        if (!out && !inn) return null
        return when {
            has(n, "GST", "CBDT", "TDS", "ITD", "INCOME TAX", "ADVANCE TAX", "EPFO", "EPF", "ESIC", "PROFESSIONAL TAX", "GSTN", "CHALLAN") && out &&
                !has(n, "CHARGES", "CHGS", "CHG") -> TxnCategory.TAXES
            has(n, "CHARGES", "CHGS", "CHG", "COMMISSION", "SMS ALERT", "AMC", "MIN BAL", "MINIMUM BALANCE", "PENALTY", "DEBIT CARD FEE", "FEE") && out -> TxnCategory.BANK_CHARGES
            has(n, "INT", "INTEREST", "INT.PD", "INT PD", "INT.CR", "INT CR", "SB INT", "FD INT") || n.contains("INTEREST") ->
                if (inn) TxnCategory.INTEREST_RECEIVED else TxnCategory.INTEREST_PAID
            has(n, "SALARY", "SAL", "WAGES", "PAYROLL") -> TxnCategory.SALARY
            has(n, "EMI", "LOAN", "LN REPAY") -> if (inn) TxnCategory.LOAN_RECEIPT else TxnCategory.LOAN_REPAYMENT
            has(n, "SELF", "OWN A/C", "OWN ACCOUNT", "SWEEP", "TRF TO OWN", "FD BOOKED") -> TxnCategory.OWN_TRANSFER
            has(n, "ATM", "ATW", "CASH WDL", "CASH WITHDRAWAL", "CASH-WDL", "NWD", "CWDR") && out -> TxnCategory.CASH_WITHDRAWAL
            has(n, "CASH DEP", "CASH DEPOSIT", "BY CASH", "CASH-DEP", "CDM") && inn -> TxnCategory.CASH_DEPOSIT
            has(n, "UPI") -> if (inn) TxnCategory.UPI_RECEIPT else TxnCategory.UPI_PAYMENT
            has(n, "CHQ", "CHEQUE", "CLG", "CLEARING", "CTS", "INWARD CLG", "OUTWARD CLG", "TO CLG", "BY CLG") -> if (inn) TxnCategory.CHEQUE_DEPOSIT else TxnCategory.CHEQUE_PAYMENT
            else -> null
        }
    }
}

enum class StatementOrder(val label: String) { OLDEST_FIRST("Oldest first (dates go forward)"), NEWEST_FIRST("Newest first (dates go backward)") }

/** One reviewable transaction. [original] is the extracted text as read; it never changes. */
data class ReviewTxn(
    val id: Int,
    val date: LocalDate?, val dateRaw: String,
    val valueDate: LocalDate?, val valueDateRaw: String,
    val description: String, val reference: String,
    val debit: BigDecimal?, val credit: BigDecimal?, val balance: BigDecimal?, val balanceRaw: String,
    val source: String, val page: Int,
    val flags: List<String>, val original: String,
    val category: TxnCategory = TxnCategory.UNCATEGORISED, val categorySuggested: Boolean = false,
    val reviewed: Boolean = false, val manual: Boolean = false,
    /** Where the row sits on its page (fractions of page height), when known. */
    val top: Float? = null, val bottom: Float? = null,
) {
    val needsReview get() = flags.isNotEmpty() && !reviewed

    companion object {
        fun from(id: Int, r: StatementRow): ReviewTxn {
            val s = Categoriser.suggest(r.narration, r.debit, r.credit)
            return ReviewTxn(id, r.date, r.dateRaw, r.valueDate, r.valueDateRaw, r.narration, r.reference, r.debit, r.credit, r.balance, r.balanceRaw,
                r.source, r.page, r.flags, r.original.ifEmpty { listOf(r.dateRaw, r.narration, r.reference, r.debit?.toPlainString() ?: "", r.credit?.toPlainString() ?: "", r.balanceRaw).joinToString(" | ") },
                s ?: TxnCategory.UNCATEGORISED, s != null, top = r.top, bottom = r.bottom)
        }
    }
}

data class AuditEntry(val seq: Int, val rowId: Int?, val action: String, val detail: String)

/** Opening/closing balance with where it came from; [confirmed] once the user has checked it. */
data class BalanceValue(val value: BigDecimal?, val source: String, val confirmed: Boolean)

/**
 * A statement-review session: the rows of all statements in extraction order (per file), edits with
 * an audit trail, and the user's confirmations of order and balances. Pure Kotlin so it's testable.
 */
class ReviewSession(rows: List<StatementRow>) {
    private var nextId = 1
    private var seq = 1
    val rows: MutableList<ReviewTxn> = rows.map { ReviewTxn.from(nextId++, it) }.toMutableList()
    val audit = mutableListOf<AuditEntry>()
    var order: StatementOrder = StatementOrder.OLDEST_FIRST; private set
    var orderConfirmed = false; private set
    private val openings = HashMap<String, BalanceValue>()
    private val closings = HashMap<String, BalanceValue>()

    init {
        val (o, confident) = detectOrder(this.rows)
        order = o
        // Dates that clearly run one way settle the order; otherwise the user must confirm it.
        if (confident) { orderConfirmed = true; log(null, "Statement order", "Detected from the dates: ${o.label}") }
    }

    val sources: List<String> get() = rows.map { it.source }.distinct()

    private fun log(rowId: Int?, action: String, detail: String) { audit.add(AuditEntry(seq++, rowId, action, detail)) }

    fun setOrder(o: StatementOrder) {
        if (o != order || !orderConfirmed) log(null, "Statement order", "${if (orderConfirmed) "Changed" else "Confirmed"}: ${o.label}")
        order = o; orderConfirmed = true
    }

    fun opening(source: String): BalanceValue = openings[source] ?: derivedOpening(source)
    fun closing(source: String): BalanceValue = closings[source] ?: derivedClosing(source)

    fun confirmOpening(source: String, value: BigDecimal?) { log(null, "Opening balance", "$source: ${value?.toPlainString() ?: "unknown"} (confirmed by user)"); openings[source] = BalanceValue(value, "Entered/confirmed by user", true) }
    fun confirmClosing(source: String, value: BigDecimal?) { log(null, "Closing balance", "$source: ${value?.toPlainString() ?: "unknown"} (confirmed by user)"); closings[source] = BalanceValue(value, "Entered/confirmed by user", true) }

    /** Rows of one file in chronological order (oldest first), as the statement order says. */
    fun chronological(source: String): List<ReviewTxn> = rows.filter { it.source == source }.let { if (order == StatementOrder.NEWEST_FIRST) it.reversed() else it }

    private fun derivedOpening(source: String): BalanceValue {
        val first = chronological(source).firstOrNull { it.balance != null } ?: return BalanceValue(null, "Not found – enter it from the statement", false)
        val delta = (first.credit ?: BigDecimal.ZERO) - (first.debit ?: BigDecimal.ZERO)
        return BalanceValue(first.balance!! - delta, "Worked out from the first transaction's balance – check against the statement", false)
    }

    private fun derivedClosing(source: String): BalanceValue {
        val last = chronological(source).lastOrNull { it.balance != null } ?: return BalanceValue(null, "Not found – enter it from the statement", false)
        return BalanceValue(last.balance, "Balance on the last transaction – check against the statement", false)
    }

    private val fields = listOf<Pair<String, (ReviewTxn) -> String>>(
        "Date" to { it.date?.format(DMY) ?: it.dateRaw }, "Value date" to { it.valueDate?.format(DMY) ?: it.valueDateRaw },
        "Description" to { it.description }, "Reference" to { it.reference },
        "Debit" to { it.debit?.toPlainString() ?: "" }, "Credit" to { it.credit?.toPlainString() ?: "" }, "Balance" to { it.balance?.toPlainString() ?: it.balanceRaw },
        "Category" to { it.category.label + if (it.categorySuggested) " (suggested)" else "" }, "Page" to { it.page.toString() },
    )

    fun find(id: Int) = rows.first { it.id == id }

    /** Replaces a row with an edited version and records each changed field. Editing marks the row reviewed. */
    fun update(id: Int, edited: ReviewTxn) {
        val i = rows.indexOfFirst { it.id == id }; require(i >= 0)
        val old = rows[i]
        val changes = fields.mapNotNull { (n, f) -> val a = f(old); val b = f(edited); if (a != b) "$n: \"$a\" → \"$b\"" else null }
        rows[i] = edited.copy(id = id, original = old.original, reviewed = true)
        if (changes.isNotEmpty()) log(id, "Edited", changes.joinToString("; "))
        else if (!old.reviewed) log(id, "Marked reviewed", "")
    }

    fun setCategory(id: Int, c: TxnCategory) {
        val r = find(id); if (r.category == c && !r.categorySuggested) return
        update(id, r.copy(category = c, categorySuggested = false))
    }

    fun markReviewed(id: Int) { val r = find(id); if (!r.reviewed) { rows[rows.indexOf(r)] = r.copy(reviewed = true); log(id, "Marked reviewed", r.flags.joinToString("; ")) } }

    fun delete(id: Int) {
        val r = find(id); rows.remove(r)
        log(id, "Deleted", "${r.dateRaw} ${r.description.take(40)} Dr ${r.debit ?: "-"} Cr ${r.credit ?: "-"} (page ${r.page})")
    }

    /** Adds a blank manual row after [afterId] (same file and page). Returns its id. */
    fun insertAfter(afterId: Int): Int {
        val i = rows.indexOfFirst { it.id == afterId }; require(i >= 0)
        val a = rows[i]
        val n = ReviewTxn(nextId++, null, "", null, "", "", "", null, null, null, "", a.source, a.page, listOf("Added manually"), "(added by user)", manual = true, top = a.bottom, bottom = a.bottom)
        rows.add(i + 1, n)
        log(n.id, "Added row", "after row ${a.id} (page ${a.page})")
        return n.id
    }

    /** Splits a row in two: the copy keeps date, file and page; amounts and balance move to whichever part the user edits. */
    fun split(id: Int): Int {
        val i = rows.indexOfFirst { it.id == id }; require(i >= 0)
        val a = rows[i]
        val n = a.copy(id = nextId++, description = "", reference = "", debit = null, credit = null, balance = null, balanceRaw = "",
            flags = listOf("Split from row ${a.id} – enter its amounts"), manual = true, reviewed = false, category = TxnCategory.UNCATEGORISED, categorySuggested = false)
        rows.add(i + 1, n)
        log(id, "Split", "new row ${n.id} created")
        return n.id
    }

    /** Joins a row with the next one (e.g. a narration that continued on a separate line). Refuses when both carry amounts. */
    fun mergeWithNext(id: Int): Boolean {
        val i = rows.indexOfFirst { it.id == id }
        if (i < 0 || i + 1 >= rows.size) return false
        val a = rows[i]; val b = rows[i + 1]
        if (a.source != b.source) return false
        val aAmt = a.debit != null || a.credit != null; val bAmt = b.debit != null || b.credit != null
        if (aAmt && bAmt) return false
        val merged = a.copy(
            date = a.date ?: b.date, dateRaw = a.dateRaw.ifEmpty { b.dateRaw }, valueDate = a.valueDate ?: b.valueDate, valueDateRaw = a.valueDateRaw.ifEmpty { b.valueDateRaw },
            description = listOf(a.description, b.description).filter { it.isNotBlank() }.joinToString(" "), reference = listOf(a.reference, b.reference).filter { it.isNotBlank() }.joinToString(" "),
            debit = a.debit ?: b.debit, credit = a.credit ?: b.credit, balance = a.balance ?: b.balance, balanceRaw = a.balanceRaw.ifEmpty { b.balanceRaw },
            flags = (a.flags + b.flags).distinct(), original = a.original + " ⏎ " + b.original, reviewed = true,
            top = listOfNotNull(a.top, b.top).minOrNull(), bottom = listOfNotNull(a.bottom, b.bottom).maxOrNull(),
        )
        rows[i] = merged; rows.removeAt(i + 1)
        log(id, "Combined", "with row ${b.id} (page ${b.page})")
        return true
    }

    companion object {
        val DMY: DateTimeFormatter = DateTimeFormatter.ofPattern("dd-MM-yyyy")

        /** Guesses the order from dates, then from which direction the running balance works. Second value: confident? */
        fun detectOrder(rows: List<ReviewTxn>): Pair<StatementOrder, Boolean> {
            val bySource = rows.groupBy { it.source }
            var fwd = 0; var back = 0
            for ((_, rs) in bySource) {
                val d = rs.mapNotNull { it.date }
                if (d.size >= 2) { if (d.last() > d.first()) fwd++ else if (d.last() < d.first()) back++ }
            }
            if (fwd > 0 && back == 0) return StatementOrder.OLDEST_FIRST to true
            if (back > 0 && fwd == 0) return StatementOrder.NEWEST_FIRST to true
            // Same-day statements: use the running balance.
            val f = rows.groupBy { it.source }.values.sumOf { Reconciler.breaks(it, StatementOrder.OLDEST_FIRST).size }
            val b = rows.groupBy { it.source }.values.sumOf { Reconciler.breaks(it, StatementOrder.NEWEST_FIRST).size }
            return (if (b < f) StatementOrder.NEWEST_FIRST else StatementOrder.OLDEST_FIRST) to false
        }
    }
}

enum class CheckStatus(val label: String) { OK("OK"), DIFFERENCE("Difference"), INCOMPLETE("Incomplete – needs confirmation"), INFO("Information") }

data class CheckLine(val label: String, val value: BigDecimal?, val status: CheckStatus, val note: String = "")

data class FileReconciliation(val source: String, val lines: List<CheckLine>, val runningBreaks: List<Int>, val transactions: Int)

data class Exception1(val rowId: Int?, val source: String, val page: Int?, val kind: String, val detail: String)

object Reconciler {
    private val TOL = BigDecimal("0.01")

    /** Ids of rows whose balance doesn't follow from the previous balance and this row's amounts, in the given order. */
    fun breaks(fileRows: List<ReviewTxn>, order: StatementOrder): List<Int> {
        val chron = if (order == StatementOrder.NEWEST_FIRST) fileRows.reversed() else fileRows
        var prev: BigDecimal? = null
        val out = mutableListOf<Int>()
        for (r in chron) {
            val b = r.balance
            if (b != null && prev != null && (r.debit != null || r.credit != null)) {
                val expect = prev + (r.credit ?: BigDecimal.ZERO) - (r.debit ?: BigDecimal.ZERO)
                if ((expect - b).abs() > TOL) out.add(r.id)
            }
            if (b != null) prev = b
        }
        return out
    }

    fun reconcile(s: ReviewSession): List<FileReconciliation> = s.sources.map { src ->
        val rs = s.rows.filter { it.source == src }
        val op = s.opening(src); val cl = s.closing(src)
        val dr = rs.mapNotNull { it.debit }.fold(BigDecimal.ZERO, BigDecimal::add)
        val cr = rs.mapNotNull { it.credit }.fold(BigDecimal.ZERO, BigDecimal::add)
        val calc = op.value?.let { it + cr - dr }
        val diff = if (calc != null && cl.value != null) calc - cl.value else null
        val confirmed = op.confirmed && cl.confirmed && s.orderConfirmed
        val br = breaks(rs, s.order)
        val lines = listOf(
            CheckLine("Opening balance", op.value, if (op.value == null || !op.confirmed) CheckStatus.INCOMPLETE else CheckStatus.OK, op.source),
            CheckLine("Total credits", cr, CheckStatus.INFO, "${rs.count { it.credit != null }} credit row(s)"),
            CheckLine("Total debits", dr, CheckStatus.INFO, "${rs.count { it.debit != null }} debit row(s)"),
            CheckLine("Calculated closing balance", calc, if (calc == null) CheckStatus.INCOMPLETE else CheckStatus.INFO, "Opening balance + total credits − total debits"),
            CheckLine("Statement closing balance", cl.value, if (cl.value == null || !cl.confirmed) CheckStatus.INCOMPLETE else CheckStatus.OK, cl.source),
            CheckLine("Difference", diff, when { diff == null -> CheckStatus.INCOMPLETE; diff.abs() > TOL -> CheckStatus.DIFFERENCE; !confirmed -> CheckStatus.INCOMPLETE; else -> CheckStatus.OK },
                when { diff == null -> "Needs opening and closing balance"; diff.abs() > TOL -> "Calculated and statement closing balances differ – look for missing or misread rows"; !confirmed -> "Agrees, but confirm the opening/closing balances and statement order to complete the check"; else -> "Agrees" }),
            CheckLine("Running-balance checks", BigDecimal(br.size), when { rs.none { it.balance != null } -> CheckStatus.INCOMPLETE; br.isEmpty() -> if (s.orderConfirmed) CheckStatus.OK else CheckStatus.INCOMPLETE; else -> CheckStatus.DIFFERENCE },
                when { rs.none { it.balance != null } -> "No balance column"; br.isEmpty() -> "Every row follows from the previous balance (${s.order.label.lowercase()})"; else -> "${br.size} row(s) don't follow from the previous balance" }),
        )
        FileReconciliation(src, lines, br, rs.size)
    }

    /** All exceptions: flagged rows not yet reviewed, running-balance breaks, duplicates, missing values, failed pages. */
    fun exceptions(s: ReviewSession, recon: List<FileReconciliation>, failedPages: List<Pair<String, String>>): List<Exception1> {
        val out = mutableListOf<Exception1>()
        val breaks = recon.flatMap { it.runningBreaks }.toSet()
        val seen = HashMap<String, ReviewTxn>()
        for (r in s.rows) {
            if (r.needsReview) r.flags.forEach { out.add(Exception1(r.id, r.source, r.page, "Needs review", it)) }
            if (r.id in breaks) out.add(Exception1(r.id, r.source, r.page, "Running balance", "Balance ${r.balance?.toPlainString()} doesn't follow from the previous row"))
            if (r.date == null && !r.reviewed) out.add(Exception1(r.id, r.source, r.page, "Missing date", r.dateRaw.ifEmpty { "No date" }))
            if (r.debit == null && r.credit == null && !r.reviewed) out.add(Exception1(r.id, r.source, r.page, "Missing amount", "No debit or credit"))
            if (r.balance == null && r.balanceRaw.isEmpty() && s.rows.any { it.source == r.source && it.balance != null } && !r.reviewed)
                out.add(Exception1(r.id, r.source, r.page, "Missing balance", "Other rows of this statement have a balance"))
            val key = listOf(r.date, r.debit?.stripTrailingZeros(), r.credit?.stripTrailingZeros(), r.balance?.stripTrailingZeros(), TextDiff.norm(r.description).lowercase()).joinToString("|")
            val prev = seen[key]
            if (prev != null && (r.debit != null || r.credit != null)) out.add(Exception1(r.id, r.source, r.page, "Possible duplicate",
                "Same date, amount${if (r.balance != null) ", balance" else ""} and description as row ${prev.id} (${prev.source}, page ${prev.page}) – keep it if it's a genuine repeat"))
            else seen[key] = r
        }
        for (rc in recon) rc.lines.filter { it.status == CheckStatus.DIFFERENCE && it.label == "Difference" }.forEach { out.add(Exception1(null, rc.source, null, "Closing balance", "Difference of ${it.value?.toPlainString()}")) }
        failedPages.forEach { (src, msg) -> out.add(Exception1(null, src, null, "Page not processed", msg)) }
        return out
    }
}
