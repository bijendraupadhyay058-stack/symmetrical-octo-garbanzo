package com.cashbook.app.data

import androidx.room.withTransaction
import com.cashbook.app.data.db.AccountEntity
import com.cashbook.app.data.db.AppDatabase
import com.cashbook.app.data.db.AttachmentEntity
import com.cashbook.app.data.db.BudgetEntity
import com.cashbook.app.data.db.AllocationEntity
import com.cashbook.app.data.db.InvoiceEntity
import com.cashbook.app.data.db.InvoiceItemEntity
import com.cashbook.app.data.db.CatalogItemEntity
import com.cashbook.app.data.db.StockAdjustmentEntity
import com.cashbook.app.data.db.toItem
import com.cashbook.app.data.db.toRule
import com.cashbook.app.data.db.CashbookEntity
import com.cashbook.app.data.db.CategoryEntity
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.data.db.toEntity
import com.cashbook.app.data.db.toInfo
import com.cashbook.app.data.db.toTxn
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.PaymentMode
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.DocType
import com.cashbook.core.InvoiceItem
import com.cashbook.core.CatalogItem
import com.cashbook.core.GstCalc
import com.cashbook.core.InvoiceKind
import com.cashbook.core.Invoices
import com.cashbook.core.Recurrence
import com.cashbook.core.RecurringRule
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.stateIn
import java.time.LocalDate

/**
 * Single entry point for reading and changing ledger data. Balances are never stored; they are
 * always derived from entries with [com.cashbook.core.Ledger], so add/edit/delete/restore all
 * recalculate automatically.
 */
class LedgerRepository(
    private val db: AppDatabase,
    private val attachments: AttachmentStore,
    scope: CoroutineScope,
) {
    private val now get() = System.currentTimeMillis()

    /**
     * Whenever any ledger table changes, every table is re-read inside ONE database transaction,
     * so screens never see a half-updated state (e.g. new entries before their accounts).
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    val snapshot: StateFlow<Snapshot> = db.invalidationTracker
        .createFlow("cashbooks", "accounts", "categories", "parties", "transactions", "attachments", "recurring", "budgets", "invoices", "allocations", "invoice_items", "catalog_items", "stock_adjustments", emitInitialState = true)
        .mapLatest { readSnapshot() }
        .flowOn(Dispatchers.IO)
        .stateIn(scope, SharingStarted.Eagerly, Snapshot())

    private suspend fun readSnapshot(): Snapshot = db.withTransaction {
        val docs = db.invoices().getAll().map { it.toInfo() }
        Snapshot(
            loaded = true,
            cashbooks = db.cashbooks().getAllSorted().map { it.toInfo() },
            accounts = db.accounts().getAllSorted().map { it.toInfo() },
            categories = db.categories().getAllSorted().map { it.toInfo() },
            parties = db.parties().getAllSorted().map { it.toInfo() },
            txns = db.transactions().getLive().map { it.toTxn() },
            deleted = db.transactions().getDeleted().map { it.toTxn() },
            attachmentCounts = db.attachments().getCounts().associate { it.transactionId to it.count },
            recurring = db.recurring().getAll().map { it.toRule() },
            budgets = db.budgets().getAll().map { it.toInfo() },
            invoices = docs.filter { it.docType != DocType.QUOTATION },
            quotations = docs.filter { it.docType == DocType.QUOTATION },
            allocations = db.invoices().allocations().map { it.toInfo() },
            invoiceItems = db.invoices().items().groupBy { it.invoiceId }.mapValues { (_, l) -> l.map { it.toItem() } },
            catalog = db.catalog().getAll().map { it.toInfo() },
            stockAdjustments = db.catalog().adjustments().map { it.toInfo() },
        )
    }

    fun attachmentsFor(txnId: Long): Flow<List<AttachmentEntity>> = db.attachments().observeFor(txnId)
    val backupHistory get() = db.backups().observeRecent()

    // ---------- cashbooks ----------

    data class NewAccount(val name: String, val type: AccountType, val openingBalance: Long, val openingDate: LocalDate,
                          val bankName: String = "", val last4: String = "")

    suspend fun createCashbook(name: String, description: String, openingDate: LocalDate, accounts: List<NewAccount>, isSample: Boolean = false): Long =
        db.withTransaction {
            val id = db.cashbooks().insert(CashbookEntity(name = name.trim(), description = description.trim(), openingDate = openingDate.toEpochDay(),
                createdAt = now, updatedAt = now, isSample = isSample))
            accounts.forEachIndexed { i, a -> db.accounts().insert(a.toEntity(id, i)) }
            id
        }

    private fun NewAccount.toEntity(cashbookId: Long, order: Int) = AccountEntity(cashbookId = cashbookId, name = name.trim(), type = type.name,
        openingBalance = openingBalance, openingDate = openingDate.toEpochDay(), bankName = bankName.trim(), last4 = last4.trim(),
        sortOrder = order, createdAt = now, updatedAt = now)

    suspend fun updateCashbook(id: Long, name: String, description: String, openingDate: LocalDate, currency: String) {
        val e = db.cashbooks().get(id) ?: return
        db.cashbooks().update(e.copy(name = name.trim(), description = description.trim(), openingDate = openingDate.toEpochDay(),
            currency = currency, updatedAt = now))
    }

    suspend fun setCashbookArchived(id: Long, archived: Boolean) {
        val e = db.cashbooks().get(id) ?: return
        db.cashbooks().update(e.copy(archived = archived, updatedAt = now))
    }

    data class DeleteImpact(val accounts: Int, val transactions: Int)

    suspend fun cashbookDeleteImpact(id: Long) = DeleteImpact(db.accounts().forCashbook(id).size, db.transactions().countForCashbook(id))

    /** Permanently removes a cashbook with its accounts, entries and attachment files. */
    suspend fun deleteCashbooks(ids: List<Long>) {
        if (ids.isEmpty()) return
        val txnIds = db.transactions().idsForCashbooks(ids)
        val files = if (txnIds.isEmpty()) emptyList() else txnIds.chunked(500).flatMap { db.attachments().getForMany(it) }
        db.withTransaction { ids.forEach { db.cashbooks().delete(it) } }
        files.forEach { attachments.delete(it.storedName) }
    }

    // ---------- accounts ----------

    suspend fun addAccount(cashbookId: Long, a: NewAccount, description: String = ""): Long {
        val order = db.accounts().forCashbook(cashbookId).size
        return db.accounts().insert(a.toEntity(cashbookId, order).copy(description = description.trim()))
    }

    suspend fun updateAccount(id: Long, a: NewAccount, description: String) {
        val e = db.accounts().getAll().firstOrNull { it.id == id } ?: return
        db.accounts().update(e.copy(name = a.name.trim(), type = a.type.name, openingBalance = a.openingBalance,
            openingDate = a.openingDate.toEpochDay(), bankName = a.bankName.trim(), last4 = a.last4.trim(),
            description = description.trim(), updatedAt = now))
    }

    suspend fun setAccountArchived(id: Long, archived: Boolean) {
        val e = db.accounts().getAll().firstOrNull { it.id == id } ?: return
        db.accounts().update(e.copy(archived = archived, updatedAt = now))
    }

    suspend fun accountUsage(id: Long) = db.transactions().countForAccount(id)

    /** Only accounts without any entries (including the recycle bin) can be deleted. */
    suspend fun deleteAccount(id: Long): Boolean {
        if (db.transactions().countForAccount(id) > 0 || db.recurring().countForAccount(id) > 0) return false
        db.accounts().delete(id); return true
    }

    // ---------- categories ----------

    suspend fun ensureDefaultCategories(language: String) {
        if (db.categories().count() > 0) return
        db.categories().insertAll(DefaultData.categories(language).map { (kind, name, icon) ->
            CategoryEntity(kind = kind.name, name = name, icon = icon, createdAt = now, updatedAt = now)
        })
    }

    suspend fun saveCategory(id: Long, kind: CategoryKind, name: String, parentId: Long?, icon: String): Long {
        if (id == 0L) return db.categories().insert(CategoryEntity(kind = kind.name, name = name.trim(), parentId = parentId, icon = icon, createdAt = now, updatedAt = now))
        val e = db.categories().get(id) ?: return id
        // Renaming keeps the same id, so existing entries simply show the new name.
        db.categories().update(e.copy(name = name.trim(), parentId = parentId?.takeIf { it != id }, icon = icon, updatedAt = now))
        return id
    }

    suspend fun setCategoryArchived(id: Long, archived: Boolean) {
        val e = db.categories().get(id) ?: return
        db.categories().update(e.copy(archived = archived, updatedAt = now))
    }

    suspend fun categoryUsage(id: Long) = db.transactions().countForCategory(id) + db.recurring().countForCategory(id)

    /** Deletes a category. Entries that use it must first be moved to [reassignTo]. */
    suspend fun deleteCategory(id: Long, reassignTo: Long?): Boolean = db.withTransaction {
        val used = db.transactions().countForCategory(id) + db.recurring().countForCategory(id)
        if (used > 0) {
            if (reassignTo == null || reassignTo == id) return@withTransaction false
            db.transactions().reassignCategory(id, reassignTo, now)
            db.recurring().reassignCategory(id, reassignTo, now)
        }
        db.categories().detachChildren(id)
        db.categories().delete(id)
        true
    }

    // ---------- parties ----------

    suspend fun saveParty(p: PartyEntity): Long {
        if (p.id == 0L) return db.parties().insert(p.copy(name = p.name.trim(), createdAt = now, updatedAt = now))
        val old = db.parties().getAll().firstOrNull { it.id == p.id }
        db.parties().update(p.copy(name = p.name.trim(), createdAt = old?.createdAt ?: now, updatedAt = now))
        return p.id
    }

    suspend fun partyUsage(id: Long) = db.transactions().countForParty(id) + db.recurring().countForParty(id) + db.invoices().countForParty(id)

    suspend fun deleteParty(id: Long): Boolean {
        if (partyUsage(id) > 0) return false
        db.parties().delete(id); return true
    }

    // ---------- transactions ----------

    /**
     * Inserts or updates an entry together with its attachment changes in one database transaction.
     * [newAttachments] are files already copied into private storage.
     */
    suspend fun saveTxn(txn: Txn, newAttachments: List<AttachmentStore.Imported>, removedAttachmentIds: List<Long>): Long {
        val removedFiles = ArrayList<String>()
        val id = db.withTransaction {
            val id = if (txn.id == 0L) {
                db.transactions().insert(txn.copy(createdAt = now, updatedAt = now, deletedAt = null).toEntity())
            } else {
                val old = db.transactions().get(txn.id) ?: error("missing")
            // An entry used to pay invoices can't drop below the amount applied to them.
            val applied = db.invoices().allocations().filter { it.transactionId == txn.id }.sumOf { it.amount }
            if (txn.amount < applied) throw InvoiceException(InvoiceException.Reason.BELOW_PAID)
                db.transactions().update(txn.copy(createdAt = old.createdAt, updatedAt = now, deletedAt = old.deletedAt).toEntity())
                txn.id
            }
            val existing = db.attachments().getFor(id).associateBy { it.id }
            removedAttachmentIds.forEach { aid -> existing[aid]?.let { db.attachments().delete(aid); removedFiles += it.storedName } }
            newAttachments.forEach {
                db.attachments().insert(AttachmentEntity(transactionId = id, fileName = it.fileName, mimeType = it.mimeType,
                    sizeBytes = it.sizeBytes, storedName = it.storedName, createdAt = now))
            }
            id
        }
        removedFiles.forEach { attachments.delete(it) }
        return id
    }

    suspend fun getTxn(id: Long) = db.transactions().get(id)?.toTxn()
    suspend fun attachmentList(txnId: Long) = db.attachments().getFor(txnId)

    /** Moves an entry (both sides of a transfer) to the recycle bin. */
    suspend fun deleteTxn(id: Long) = db.transactions().softDelete(id, now)

    /** Restores an entry (a transfer is one row, so both account effects return together). */
    suspend fun restoreTxn(id: Long) = db.transactions().restore(id)

    suspend fun purge(ids: List<Long>) {
        if (ids.isEmpty()) return
        val files = ids.chunked(500).flatMap { db.attachments().getForMany(it) }
        db.withTransaction { ids.forEach { db.transactions().deletePermanently(it) } }
        files.forEach { attachments.delete(it.storedName) }
    }

    suspend fun emptyRecycleBin() = purge(db.transactions().allDeletedIds())

    suspend fun purgeOlderThan(days: Int) {
        if (days <= 0) return
        purge(db.transactions().deletedBefore(now - days * 86_400_000L))
    }

    // ---------- recurring entries ----------

    /** Creates or updates a rule. A new rule whose start date is in the past starts from its first date (catch-up posts the missed ones). */
    suspend fun saveRecurring(rule: RecurringRule): Long {
        if (rule.id == 0L) return db.recurring().insert(rule.toEntity(now, now))
        val old = db.recurring().get(rule.id) ?: return rule.id
        // Changing the schedule restarts counting from the next occurrence on/after today, so nothing is posted twice.
        val scheduleChanged = old.startDate != rule.startDate.toEpochDay() || old.frequency != rule.frequency.name || old.interval != rule.interval
        val next = if (scheduleChanged) Recurrence.firstIndexOnOrAfter(rule, maxOf(LocalDate.now(), rule.startDate)) else old.nextIndex
        db.recurring().update(rule.copy(nextIndex = next).toEntity(old.createdAt, now))
        return rule.id
    }

    suspend fun setRecurringActive(id: Long, active: Boolean) {
        val e = db.recurring().get(id) ?: return
        db.recurring().update(e.copy(active = active, updatedAt = now))
    }

    /** Deletes the rule only; entries it already created stay in the ledger. */
    suspend fun deleteRecurring(id: Long) = db.recurring().delete(id)

    /**
     * Posts every due occurrence of auto-post rules up to [today]. Each occurrence is inserted and the
     * rule advanced in the same transaction, and an existing entry for the same rule and date is never
     * duplicated, so running this repeatedly (app start, daily worker) is safe. Returns entries created.
     */
    suspend fun postDueRecurring(today: LocalDate = LocalDate.now()): Int {
        var created = 0
        for (e in db.recurring().getAll()) {
            val rule = e.toRule()
            if (!rule.autoPost || !rule.active) continue
            val due = Recurrence.due(rule, today)
            if (due.isEmpty()) continue
            created += db.withTransaction {
                var n = 0
                for ((_, date) in due) {
                    if (db.transactions().countForRuleOn(rule.id, date.toEpochDay()) == 0) {
                        db.transactions().insert(rule.toTxn(date, now).toEntity()); n++
                    }
                }
                db.recurring().setNextIndex(rule.id, due.last().first + 1, now)
                n
            }
        }
        return created
    }

    /** Confirms the next occurrence of a manual rule (optionally with a different amount). */
    suspend fun postNextOccurrence(ruleId: Long, amount: Long? = null): Long? = db.withTransaction {
        val rule = db.recurring().get(ruleId)?.toRule() ?: return@withTransaction null
        val date = rule.nextDate ?: return@withTransaction null
        val id = db.transactions().insert(rule.toTxn(date, now).copy(amount = amount ?: rule.amount).toEntity())
        db.recurring().setNextIndex(ruleId, rule.nextIndex + 1, now)
        id
    }

    /** Skips the next occurrence of a rule without creating an entry. */
    suspend fun skipNextOccurrence(ruleId: Long) {
        val rule = db.recurring().get(ruleId) ?: return
        db.recurring().setNextIndex(ruleId, rule.nextIndex + 1, now)
    }

    // ---------- budgets ----------

    /** Sets a category's monthly budget; [monthlyAmount] 0 removes it. */
    suspend fun setBudget(cashbookId: Long, categoryId: Long, monthlyAmount: Long) {
        val existing = db.budgets().find(cashbookId, categoryId)
        when {
            monthlyAmount <= 0 -> existing?.let { db.budgets().delete(it.id) }
            existing == null -> db.budgets().insert(BudgetEntity(cashbookId = cashbookId, categoryId = categoryId, monthlyAmount = monthlyAmount, createdAt = now, updatedAt = now))
            else -> db.budgets().update(existing.copy(monthlyAmount = monthlyAmount, updatedAt = now))
        }
    }

    // ---------- invoices & bills ----------

    class InvoiceException(val reason: Reason) : Exception(reason.name) {
        enum class Reason { DUPLICATE_NUMBER, HAS_PAYMENTS, BELOW_PAID, INVALID_ALLOCATION, NOT_FOUND, INVALID_AMOUNT, HAS_NOTES, NOTE_TOO_LARGE, ALREADY_CONVERTED, DECLINED }
    }

    suspend fun nextInvoiceNumber(cashbookId: Long, kind: InvoiceKind, date: LocalDate, docType: DocType = DocType.INVOICE) =
        Invoices.nextNumber(kind, db.invoices().numbersOf(cashbookId, kind.name, docType.name), date, docType)

    /** Current position of one invoice (payments net of refunds, notes folded in). */
    private suspend fun balanceOf(invoiceId: Long): com.cashbook.core.InvoiceBalance? {
        val docs = db.invoices().getAll().map { it.toInfo() }
        val inv = docs.firstOrNull { it.id == invoiceId && it.docType == DocType.INVOICE } ?: return null
        val live = db.transactions().getLive().associate { it.id to enumValueOf<TxnType>(it.type) }
        return Invoices.balances(docs.filter { it.id == inv.id || it.refInvoiceId == inv.id }, db.invoices().allocations().map { it.toInfo() }, live, LocalDate.now()).single()
    }

    private suspend fun paidOn(invoiceId: Long): Long = balanceOf(invoiceId)?.paid ?: 0L

    /**
     * Creates or updates an invoice/bill. With [items] the amount is the GST grand total (tax split from
     * [sellerState] vs the place of supply); without items the entered amount is kept. Numbers are unique
     * per cashbook and kind; the amount can't go below what is already paid. Items are replaced atomically.
     */
    suspend fun saveInvoice(input: InvoiceInfo, items: List<InvoiceItem>? = null, sellerState: String = ""): Long = db.withTransaction {
        // A note always belongs to the original invoice's cashbook, kind, party and place of supply.
        val base = if (!input.docType.isNote) input.copy(refInvoiceId = null) else {
            val original = input.refInvoiceId?.let { db.invoices().get(it)?.toInfo() }?.takeIf { it.docType == DocType.INVOICE }
                ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
            input.copy(cashbookId = original.cashbookId, kind = original.kind, partyId = original.partyId,
                placeOfSupply = input.placeOfSupply.ifBlank { original.placeOfSupply })
        }
        val inv = if (items.isNullOrEmpty()) base
            else base.copy(amount = GstCalc.totals(items, GstCalc.isInterState(sellerState, base.placeOfSupply), base.roundOff).grandTotal)
        if (inv.docType.isNote) {
            val original = db.invoices().get(inv.refInvoiceId!!)!!.toInfo()
            if (Invoices.validateNote(original, db.invoices().getAll().map { it.toInfo() }, inv.docType, inv.amount, inv.id) != null)
                throw InvoiceException(InvoiceException.Reason.NOTE_TOO_LARGE)
        }
        val id = saveInvoiceRow(inv)
        if (items != null) {
            db.invoices().deleteItems(id)
            db.invoices().insertItems(items.mapIndexed { i, it -> InvoiceItemEntity(invoiceId = id, position = i, description = it.description.trim(),
                hsn = it.hsn.trim(), quantityMilli = it.quantityMilli, unit = it.unit.trim(), rate = it.rate, discountBp = it.discountBp, gstBp = it.gstBp,
                itemId = it.itemId) })
        }
        id
    }

    private suspend fun saveInvoiceRow(inv: InvoiceInfo): Long = db.withTransaction {
        if (inv.amount <= 0) throw InvoiceException(InvoiceException.Reason.INVALID_AMOUNT)
        if (db.invoices().countNumber(inv.cashbookId, inv.kind.name, inv.docType.name, inv.number.trim(), inv.id) > 0) throw InvoiceException(InvoiceException.Reason.DUPLICATE_NUMBER)
        if (inv.id == 0L) {
            db.invoices().insert(InvoiceEntity(cashbookId = inv.cashbookId, kind = inv.kind.name, number = inv.number.trim(), partyId = inv.partyId,
                issueDate = inv.issueDate.toEpochDay(), dueDate = inv.dueDate.toEpochDay(), amount = inv.amount, description = inv.description.trim(),
                notes = inv.notes.trim(), createdAt = now, updatedAt = now, placeOfSupply = inv.placeOfSupply, roundOff = inv.roundOff,
                docType = inv.docType.name, refInvoiceId = inv.refInvoiceId))
        } else {
            val old = db.invoices().get(inv.id) ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
            // what's owed after notes can't fall below what has been paid (refund it first)
            if (inv.docType == DocType.INVOICE) balanceOf(inv.id)?.let { b -> if (inv.amount + b.debited - b.credited < b.paid) throw InvoiceException(InvoiceException.Reason.BELOW_PAID) }
            db.invoices().update(old.copy(number = inv.number.trim(), partyId = inv.partyId, issueDate = inv.issueDate.toEpochDay(),
                dueDate = inv.dueDate.toEpochDay(), amount = inv.amount, description = inv.description.trim(), notes = inv.notes.trim(), updatedAt = now,
                placeOfSupply = inv.placeOfSupply, roundOff = inv.roundOff))
            inv.id
        }
    }

    /** Cancel (void) an invoice. Only possible while no payment is applied to it. */
    suspend fun setInvoiceCancelled(id: Long, cancelled: Boolean) {
        val e = db.invoices().get(id) ?: return
        if (cancelled && db.invoices().allocationsFor(id).isNotEmpty()) throw InvoiceException(InvoiceException.Reason.HAS_PAYMENTS)
        if (cancelled && db.invoices().countNotes(id) > 0) throw InvoiceException(InvoiceException.Reason.HAS_NOTES)
        db.invoices().update(e.copy(cancelled = cancelled, updatedAt = now))
    }

    /** Deletes an invoice that has no payments applied (payments stay as normal entries otherwise). */
    suspend fun deleteInvoice(id: Long) {
        if (db.invoices().allocationsFor(id).isNotEmpty()) throw InvoiceException(InvoiceException.Reason.HAS_PAYMENTS)
        if (db.invoices().countNotes(id) > 0) throw InvoiceException(InvoiceException.Reason.HAS_NOTES)
        db.withTransaction {
            db.invoices().unlinkQuotes(id)
            db.invoices().deleteItems(id)
            db.invoices().delete(id)
        }
    }

    /**
     * Turns a quotation into a sales invoice (or a purchase order into a bill) dated [date] (due after [dueDays]): same customer, place of supply,
     * round-off, description, notes and items (the amount is recalculated from the items). The quotation is
     * marked converted; deleting that invoice re-opens it.
     */
    suspend fun convertQuotation(quoteId: Long, date: LocalDate, dueDays: Long = 15, sellerState: String = ""): Long = db.withTransaction {
        val q = db.invoices().get(quoteId)?.toInfo()?.takeIf { it.docType == DocType.QUOTATION } ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
        if (q.convertedInvoiceId?.let { db.invoices().get(it) } != null) throw InvoiceException(InvoiceException.Reason.ALREADY_CONVERTED)
        if (q.cancelled) throw InvoiceException(InvoiceException.Reason.DECLINED)
        val items = db.invoices().items().filter { it.invoiceId == quoteId }.map { it.toItem().copy(id = 0) }
        val number = nextInvoiceNumber(q.cashbookId, q.kind, date)
        val invId = saveInvoice(q.copy(id = 0, number = number, issueDate = date, dueDate = date.plusDays(dueDays), docType = DocType.INVOICE,
            refInvoiceId = null, convertedInvoiceId = null, cancelled = false), items, sellerState)
        db.invoices().linkQuote(quoteId, invId, now)
        invId
    }

    /**
     * Records money received for an invoice (or paid for a bill): creates the income/expense entry and
     * applies it to the invoice in one database transaction.
     */
    suspend fun recordPayment(invoiceId: Long, accountId: Long, categoryId: Long, amount: Long, date: LocalDate, mode: PaymentMode, reference: String,
                              description: String): Long = db.withTransaction {
        val inv = db.invoices().get(invoiceId)?.toInfo()?.takeIf { it.docType == DocType.INVOICE } ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
        val outstanding = balanceOf(invoiceId)?.outstanding ?: 0
        if (inv.cancelled || amount <= 0 || amount > outstanding) throw InvoiceException(InvoiceException.Reason.INVALID_ALLOCATION)
        val txnId = db.transactions().insert(Txn(0, inv.cashbookId, inv.kind.paymentType, date, amount, accountId, categoryId = categoryId,
            partyId = inv.partyId, paymentMode = mode, description = description, reference = reference, createdAt = now, updatedAt = now).toEntity())
        db.invoices().insertAllocation(AllocationEntity(invoiceId = invoiceId, transactionId = txnId, amount = amount, createdAt = now))
        txnId
    }

    /**
     * Records money returned for an invoice whose credit notes exceed what was paid: an expense (refund to
     * the customer) for a sales invoice, or income (refund from the supplier) for a bill, applied to it.
     */
    suspend fun recordRefund(invoiceId: Long, accountId: Long, categoryId: Long, amount: Long, date: LocalDate, mode: PaymentMode, reference: String,
                             description: String): Long = db.withTransaction {
        val inv = db.invoices().get(invoiceId)?.toInfo()?.takeIf { it.docType == DocType.INVOICE } ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
        val due = balanceOf(invoiceId)?.refundDue ?: 0
        if (amount <= 0 || amount > due) throw InvoiceException(InvoiceException.Reason.INVALID_ALLOCATION)
        val type = if (inv.kind == InvoiceKind.SALE) TxnType.EXPENSE else TxnType.INCOME
        val txnId = db.transactions().insert(Txn(0, inv.cashbookId, type, date, amount, accountId, categoryId = categoryId, partyId = inv.partyId,
            paymentMode = mode, description = description, reference = reference, createdAt = now, updatedAt = now).toEntity())
        db.invoices().insertAllocation(AllocationEntity(invoiceId = invoiceId, transactionId = txnId, amount = amount, createdAt = now))
        txnId
    }

    /** Applies [amount] of an existing payment entry to an invoice (0 removes the link). Validated by [Invoices.validateAllocation]. */
    suspend fun allocate(invoiceId: Long, txnId: Long, amount: Long) = db.withTransaction {
        val existing = db.invoices().allocation(invoiceId, txnId)
        if (amount <= 0) { existing?.let { db.invoices().deleteAllocation(it.id) }; return@withTransaction }
        val txns = db.transactions().getLive().map { it.toTxn() }
        val txn = txns.firstOrNull { it.id == txnId } ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
        val bal = balanceOf(invoiceId) ?: throw InvoiceException(InvoiceException.Reason.NOT_FOUND)
        val allocs = db.invoices().allocations().map { it.toInfo() }
        if (Invoices.validateAllocation(bal, txn, amount, allocs) != null) throw InvoiceException(InvoiceException.Reason.INVALID_ALLOCATION)
        if (existing == null) db.invoices().insertAllocation(AllocationEntity(invoiceId = invoiceId, transactionId = txnId, amount = amount, createdAt = now))
        else db.invoices().updateAllocation(existing.id, amount)
    }

    // ---------- products & services ----------

    class CatalogException(val reason: Reason) : Exception(reason.name) { enum class Reason { DUPLICATE_NAME, IN_USE } }

    /** Creates or updates a saved product/service. Names are unique (ignoring case). */
    suspend fun saveCatalogItem(item: CatalogItem): Long = db.withTransaction {
        if (db.catalog().countName(item.name.trim(), item.id) > 0) throw CatalogException(CatalogException.Reason.DUPLICATE_NAME)
        val e = CatalogItemEntity(item.id, item.name.trim(), item.kind.name, item.hsn.trim(), item.unit.trim(), item.saleRate, item.purchaseRate, item.gstBp,
            item.description.trim(), item.openingStockMilli, item.openingDate.toEpochDay(), item.reorderLevelMilli, item.archived, now, now)
        if (item.id == 0L) db.catalog().insert(e)
        else { db.catalog().update(e.copy(createdAt = db.catalog().get(item.id)?.createdAt ?: now)); item.id }
    }

    suspend fun setCatalogItemArchived(id: Long, archived: Boolean) {
        val e = db.catalog().get(id) ?: return
        db.catalog().update(e.copy(archived = archived, updatedAt = now))
    }

    /** Deletes an item only if no invoice line uses it (archive it otherwise); its adjustments go with it. */
    suspend fun deleteCatalogItem(id: Long) {
        if (db.catalog().countLines(id) > 0) throw CatalogException(CatalogException.Reason.IN_USE)
        db.catalog().delete(id)
    }

    suspend fun addStockAdjustment(itemId: Long, date: LocalDate, quantityMilli: Long, reason: String): Long {
        require(quantityMilli != 0L)
        return db.catalog().insertAdjustment(StockAdjustmentEntity(itemId = itemId, date = date.toEpochDay(), quantityMilli = quantityMilli, reason = reason.trim(), createdAt = now))
    }

    suspend fun deleteStockAdjustment(id: Long) = db.catalog().deleteAdjustment(id)

    // ---------- sample data ----------

    /** Adds the "Office Cashbook" demo from the specification. Returns its id. */
    suspend fun addSampleData(language: String, names: SampleNames): Long {
        ensureDefaultCategories(language)
        val d = { day: Int -> LocalDate.of(2026, 4, day) }
        return db.withTransaction {
            val cb = createCashbook(names.cashbook, names.description, d(1), listOf(
                NewAccount(names.cash, AccountType.CASH, 1_000_000, d(1)),
                NewAccount(names.bank, AccountType.BANK, 5_000_000, d(1), bankName = "SBI"),
            ), isSample = true)
            val accs = db.accounts().forCashbook(cb)
            val cash = accs.first { it.type == AccountType.CASH.name }.id
            val bank = accs.first { it.type == AccountType.BANK.name }.id
            val cats = db.categories().getAll()
            fun cat(kind: CategoryKind, index: Int, en: String): Long? =
                cats.firstOrNull { it.kind == kind.name && it.name.equals(en, true) }?.id
                    ?: cats.filter { it.kind == kind.name && it.parentId == null }.getOrNull(index)?.id
            val base = now
            val entries = listOf(
                Txn(0, cb, TxnType.INCOME, d(2), 1_500_000, bank, categoryId = cat(CategoryKind.INCOME, 1, "Professional fees"), paymentMode = PaymentMode.UPI, description = names.t1),
                Txn(0, cb, TxnType.EXPENSE, d(3), 150_000, cash, categoryId = cat(CategoryKind.EXPENSE, 8, "Printing and stationery"), paymentMode = PaymentMode.CASH, description = names.t2),
                Txn(0, cb, TxnType.EXPENSE, d(4), 100_000, bank, categoryId = cat(CategoryKind.EXPENSE, 4, "Telephone and internet"), paymentMode = PaymentMode.BANK_TRANSFER, description = names.t3),
                Txn(0, cb, TxnType.TRANSFER, d(5), 500_000, bank, toAccountId = cash, paymentMode = PaymentMode.OTHER, description = names.t4),
            )
            entries.forEachIndexed { i, t -> db.transactions().insert(t.copy(createdAt = base + i, updatedAt = base + i).toEntity()) }
            cb
        }
    }

    data class SampleNames(val cashbook: String, val description: String, val cash: String, val bank: String,
                           val t1: String, val t2: String, val t3: String, val t4: String)

    suspend fun removeSampleData(): List<Long> {
        val ids = db.cashbooks().sampleIds()
        deleteCashbooks(ids)
        return ids
    }
}
