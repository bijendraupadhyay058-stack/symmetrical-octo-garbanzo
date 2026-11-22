package com.cashbook.core

/** Every filter the transaction list, dashboard and custom report understand. Empty = no restriction. */
data class TxnFilter(
    val range: DateRange? = null,
    val cashbookIds: Set<Long> = emptySet(),
    val accountIds: Set<Long> = emptySet(),
    val types: Set<TxnType> = emptySet(),
    val categoryIds: Set<Long> = emptySet(),
    val partyIds: Set<Long> = emptySet(),
    val paymentModes: Set<PaymentMode> = emptySet(),
    val minAmount: Long? = null,
    val maxAmount: Long? = null,
    val withAttachmentsOnly: Boolean = false,
    val query: String = "",
) {
    /** True when anything other than the cashbook scope narrows the list. */
    val isActive: Boolean
        get() = range != null || accountIds.isNotEmpty() || types.isNotEmpty() || categoryIds.isNotEmpty() ||
            partyIds.isNotEmpty() || paymentModes.isNotEmpty() || minAmount != null || maxAmount != null ||
            withAttachmentsOnly || query.isNotBlank()
}

enum class SortOrder { LATEST, OLDEST, HIGHEST, LOWEST }

/** Resolves ids to display names for searching. */
interface NameLookup {
    fun account(id: Long?): String
    fun category(id: Long?): String
    fun party(id: Long?): String
}

object TxnQuery {
    fun apply(
        txns: List<Txn>,
        filter: TxnFilter,
        names: NameLookup,
        txnsWithAttachments: Set<Long> = emptySet(),
    ): List<Txn> {
        val q = filter.query.trim().lowercase()
        val qAmount = (Money.parse(filter.query) as? Money.ParseResult.Ok)?.paise
        return txns.filter { t ->
            (filter.range == null || t.date in filter.range) &&
                (filter.cashbookIds.isEmpty() || t.cashbookId in filter.cashbookIds) &&
                (filter.accountIds.isEmpty() || Ledger.touches(t, filter.accountIds)) &&
                (filter.types.isEmpty() || t.type in filter.types) &&
                (filter.categoryIds.isEmpty() || t.categoryId in filter.categoryIds) &&
                (filter.partyIds.isEmpty() || t.partyId in filter.partyIds) &&
                (filter.paymentModes.isEmpty() || t.paymentMode in filter.paymentModes) &&
                (filter.minAmount == null || t.amount >= filter.minAmount) &&
                (filter.maxAmount == null || t.amount <= filter.maxAmount) &&
                (!filter.withAttachmentsOnly || t.id in txnsWithAttachments) &&
                (q.isEmpty() || matches(t, q, qAmount, names))
        }
    }

    private fun matches(t: Txn, q: String, qAmount: Long?, names: NameLookup): Boolean =
        t.description.lowercase().contains(q) ||
            t.reference.lowercase().contains(q) ||
            t.notes.lowercase().contains(q) ||
            t.tags.lowercase().contains(q) ||
            names.party(t.partyId).lowercase().contains(q) ||
            names.category(t.categoryId).lowercase().contains(q) ||
            (qAmount != null && t.amount == qAmount) ||
            Money.toPlain(t.amount).startsWith(q)

    fun sort(txns: List<Txn>, order: SortOrder): List<Txn> = when (order) {
        SortOrder.LATEST -> txns.sortedWith(TxnChronological.reversed())
        SortOrder.OLDEST -> txns.sortedWith(TxnChronological)
        SortOrder.HIGHEST -> txns.sortedWith(compareByDescending<Txn> { it.amount }.then(TxnChronological.reversed()))
        SortOrder.LOWEST -> txns.sortedWith(compareBy<Txn> { it.amount }.then(TxnChronological.reversed()))
    }
}
