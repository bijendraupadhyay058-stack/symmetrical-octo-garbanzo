package com.cashbook.app.data

import com.cashbook.core.AccountInfo
import com.cashbook.core.BudgetInfo
import com.cashbook.core.Allocation
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.Invoices
import com.cashbook.core.RecurringRule
import com.cashbook.core.CashbookInfo
import com.cashbook.core.CategoryInfo
import com.cashbook.core.CategoryKind
import com.cashbook.core.NameLookup
import com.cashbook.core.PartyInfo
import com.cashbook.core.Txn

/** An immutable, consistent view of the whole ledger, recomputed whenever the database changes. */
data class Snapshot(
    val loaded: Boolean = false,
    val cashbooks: List<CashbookInfo> = emptyList(),
    val accounts: List<AccountInfo> = emptyList(),
    val categories: List<CategoryInfo> = emptyList(),
    val parties: List<PartyInfo> = emptyList(),
    /** Live entries (not in the recycle bin). */
    val txns: List<Txn> = emptyList(),
    /** Entries in the recycle bin. */
    val deleted: List<Txn> = emptyList(),
    val attachmentCounts: Map<Long, Int> = emptyMap(),
    val recurring: List<RecurringRule> = emptyList(),
    val budgets: List<BudgetInfo> = emptyList(),
    /** Invoices, bills and credit/debit notes (never quotations, so balances, stock and reports can't pick them up). */
    val invoices: List<InvoiceInfo> = emptyList(),
    /** Sales quotations / estimates and purchase orders. */
    val quotations: List<InvoiceInfo> = emptyList(),
    /** Delivery challans (they move stock but owe nothing until billed). */
    val challans: List<InvoiceInfo> = emptyList(),
    val allocations: List<Allocation> = emptyList(),
    /** Line items per invoice id (empty list = invoice entered as a single amount). */
    val invoiceItems: Map<Long, List<com.cashbook.core.InvoiceItem>> = emptyMap(),
    val catalog: List<com.cashbook.core.CatalogItem> = emptyList(),
    val stockAdjustments: List<com.cashbook.core.StockAdjustment> = emptyList(),
) {
    val catalogById by lazy { catalog.associateBy { it.id } }
    /** Every stock movement (document lines linked to saved goods + manual adjustments). */
    val stockMoves by lazy { com.cashbook.core.Stock.moves(invoices + challans, invoiceItems, stockAdjustments) }
    fun onHand(item: com.cashbook.core.CatalogItem) = com.cashbook.core.Stock.onHand(item, stockMoves)
    /** Invoice balances as of [today]; only payments that are not in the recycle bin count. */
    fun invoiceBalances(today: java.time.LocalDate = java.time.LocalDate.now()): List<InvoiceBalance> =
        Invoices.balances(invoices, allocations, txns.associate { it.id to it.type }, today)

    /** Any document (invoice, note or quotation) by id. */
    fun doc(id: Long): InvoiceInfo? = invoices.firstOrNull { it.id == id } ?: quotations.firstOrNull { it.id == id } ?: challans.firstOrNull { it.id == id }

    /** Quotations, purchase orders and challans that were converted into [invoiceId]. */
    fun sourcesOf(invoiceId: Long) = com.cashbook.core.Quotations.sourcesOf(invoiceId, quotations + challans)

    /** Credit/debit notes issued against an invoice. */
    fun notesOf(invoiceId: Long) = invoices.filter { it.refInvoiceId == invoiceId }
    val cashbookById = cashbooks.associateBy { it.id }
    val accountById = accounts.associateBy { it.id }
    val categoryById = categories.associateBy { it.id }
    val partyById = parties.associateBy { it.id }
    val withAttachments: Set<Long> get() = attachmentCounts.keys

    fun accountsOf(cashbookIds: Set<Long>) = accounts.filter { it.cashbookId in cashbookIds }
    fun txnsOf(cashbookIds: Set<Long>) = txns.filter { it.cashbookId in cashbookIds }

    fun categoryName(id: Long?): String {
        val c = id?.let { categoryById[it] } ?: return ""
        val p = c.parentId?.let { categoryById[it] }
        return if (p != null) "${p.name} › ${c.name}" else c.name
    }

    fun categoriesOf(kind: CategoryKind) = categories.filter { it.kind == kind }

    val names = object : NameLookup {
        override fun account(id: Long?) = id?.let { accountById[it]?.name } ?: ""
        override fun category(id: Long?) = categoryName(id)
        override fun party(id: Long?) = id?.let { partyById[it]?.name } ?: ""
    }
}
