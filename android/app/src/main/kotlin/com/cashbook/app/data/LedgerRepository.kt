package com.cashbook.app.data

import androidx.room.withTransaction
import com.cashbook.app.data.db.AccountEntity
import com.cashbook.app.data.db.AppDatabase
import com.cashbook.app.data.db.AttachmentEntity
import com.cashbook.app.data.db.CashbookEntity
import com.cashbook.app.data.db.CategoryEntity
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.data.db.toEntity
import com.cashbook.app.data.db.toInfo
import com.cashbook.app.data.db.toTxn
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.PaymentMode
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
        .createFlow("cashbooks", "accounts", "categories", "parties", "transactions", "attachments", emitInitialState = true)
        .mapLatest { readSnapshot() }
        .flowOn(Dispatchers.IO)
        .stateIn(scope, SharingStarted.Eagerly, Snapshot())

    private suspend fun readSnapshot(): Snapshot = db.withTransaction {
        Snapshot(
            loaded = true,
            cashbooks = db.cashbooks().getAllSorted().map { it.toInfo() },
            accounts = db.accounts().getAllSorted().map { it.toInfo() },
            categories = db.categories().getAllSorted().map { it.toInfo() },
            parties = db.parties().getAllSorted().map { it.toInfo() },
            txns = db.transactions().getLive().map { it.toTxn() },
            deleted = db.transactions().getDeleted().map { it.toTxn() },
            attachmentCounts = db.attachments().getCounts().associate { it.transactionId to it.count },
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
        if (db.transactions().countForAccount(id) > 0) return false
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

    suspend fun categoryUsage(id: Long) = db.transactions().countForCategory(id)

    /** Deletes a category. Entries that use it must first be moved to [reassignTo]. */
    suspend fun deleteCategory(id: Long, reassignTo: Long?): Boolean = db.withTransaction {
        val used = db.transactions().countForCategory(id)
        if (used > 0) {
            if (reassignTo == null || reassignTo == id) return@withTransaction false
            db.transactions().reassignCategory(id, reassignTo, now)
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

    suspend fun partyUsage(id: Long) = db.transactions().countForParty(id)

    suspend fun deleteParty(id: Long): Boolean {
        if (db.transactions().countForParty(id) > 0) return false
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
