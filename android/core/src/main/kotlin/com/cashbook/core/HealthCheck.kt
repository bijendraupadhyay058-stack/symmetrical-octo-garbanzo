package com.cashbook.core

/** How serious a health-check finding is. OK findings are kept so the report lists every check that ran. */
enum class Severity { OK, INFO, WARNING, ERROR }

/**
 * Consistency checks over the whole ledger — things the app's own rules should prevent, so any hit points at a bug,
 * an old backup or a half-finished operation, and is worth reporting. Each check returns how many records are affected
 * and a few examples.
 */
object HealthCheck {
    enum class Check { ALLOCATIONS_ORPHANED, OVER_ALLOCATED, TRANSFER_BROKEN, CASHBOOK_MISMATCH, CATEGORY_KIND, CONVERSION_LINK, NEGATIVE_BALANCE }

    data class Finding(val check: Check, val severity: Severity, val count: Int = 0, val examples: List<String> = emptyList())

    fun ledger(accounts: List<AccountInfo>, categories: List<CategoryInfo>, live: List<Txn>, deleted: List<Txn>, docs: List<InvoiceInfo>,
               allocations: List<Allocation>): List<Finding> {
        val accountById = accounts.associateBy { it.id }
        val categoryById = categories.associateBy { it.id }
        val txnIds = (live + deleted).map { it.id }.toSet()
        val docIds = docs.map { it.id }.toSet()
        val liveById = live.associateBy { it.id }
        fun t(x: Txn) = "#${x.id} ${x.date} ${x.description.take(30)}".trim()
        fun finding(c: Check, bad: Severity, items: List<String>) = Finding(c, if (items.isEmpty()) Severity.OK else bad, items.size, items.take(5))

        // payment links pointing at an invoice or entry that no longer exists (an entry in the recycle bin is fine)
        val orphaned = allocations.filter { it.invoiceId !in docIds || it.txnId !in txnIds }.map { "allocation #${it.id} (invoice #${it.invoiceId}, entry #${it.txnId})" }
        // an entry applied to invoices for more than its amount
        val over = allocations.groupBy { it.txnId }.mapNotNull { (id, l) -> liveById[id]?.takeIf { l.sumOf { a -> a.amount } > it.amount }?.let { t(it) } }
        val transfers = live.filter { it.type == TxnType.TRANSFER && (it.toAccountId == null || it.toAccountId == it.accountId || it.toAccountId !in accountById) }.map { t(it) }
        val mismatch = live.filter { x -> accountById[x.accountId].let { it == null || it.cashbookId != x.cashbookId } }.map { t(it) }
        val kind = live.filter { x ->
            val c = x.categoryId?.let { categoryById[it] } ?: return@filter x.type == TxnType.TRANSFER && x.categoryId != null
            x.type == TxnType.TRANSFER || (x.type == TxnType.INCOME) != (c.kind == CategoryKind.INCOME)
        }.map { t(it) }
        val links = docs.filter { it.docType.isOffBook && it.convertedInvoiceId != null && it.convertedInvoiceId !in docIds }.map { "${it.number} → #${it.convertedInvoiceId}" }
        val negative = accounts.filter { !it.archived && Ledger.currentBalance(it, live) < 0 }.map { it.name }
        return listOf(
            finding(Check.ALLOCATIONS_ORPHANED, Severity.ERROR, orphaned),
            finding(Check.OVER_ALLOCATED, Severity.ERROR, over),
            finding(Check.TRANSFER_BROKEN, Severity.ERROR, transfers),
            finding(Check.CASHBOOK_MISMATCH, Severity.ERROR, mismatch),
            finding(Check.CATEGORY_KIND, Severity.WARNING, kind),
            finding(Check.CONVERSION_LINK, Severity.WARNING, links),
            finding(Check.NEGATIVE_BALANCE, Severity.INFO, negative),            // allowed by a setting; just worth knowing
        )
    }
}
