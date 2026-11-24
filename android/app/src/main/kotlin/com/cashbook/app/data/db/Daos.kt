package com.cashbook.app.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface CashbookDao {
    @Query("SELECT * FROM cashbooks ORDER BY archived, name COLLATE NOCASE") fun observeAll(): Flow<List<CashbookEntity>>
    @Query("SELECT * FROM cashbooks") suspend fun getAll(): List<CashbookEntity>
    @Query("SELECT * FROM cashbooks ORDER BY archived, name COLLATE NOCASE") suspend fun getAllSorted(): List<CashbookEntity>
    @Query("SELECT * FROM cashbooks WHERE id = :id") suspend fun get(id: Long): CashbookEntity?
    @Insert suspend fun insert(e: CashbookEntity): Long
    @Insert suspend fun insertAll(e: List<CashbookEntity>)
    @Update suspend fun update(e: CashbookEntity)
    @Query("DELETE FROM cashbooks WHERE id = :id") suspend fun delete(id: Long)
    @Query("DELETE FROM cashbooks") suspend fun deleteAll()
    @Query("SELECT id FROM cashbooks WHERE is_sample = 1") suspend fun sampleIds(): List<Long>
}

@Dao
interface AccountDao {
    @Query("SELECT * FROM accounts ORDER BY sort_order, id") fun observeAll(): Flow<List<AccountEntity>>
    @Query("SELECT * FROM accounts") suspend fun getAll(): List<AccountEntity>
    @Query("SELECT * FROM accounts WHERE id = :id") suspend fun get(id: Long): AccountEntity?
    @Query("SELECT * FROM accounts ORDER BY sort_order, id") suspend fun getAllSorted(): List<AccountEntity>
    @Query("SELECT * FROM accounts WHERE cashbook_id = :cashbookId") suspend fun forCashbook(cashbookId: Long): List<AccountEntity>
    @Insert suspend fun insert(e: AccountEntity): Long
    @Insert suspend fun insertAll(e: List<AccountEntity>)
    @Update suspend fun update(e: AccountEntity)
    @Query("DELETE FROM accounts WHERE id = :id") suspend fun delete(id: Long)
}

@Dao
interface CategoryDao {
    @Query("SELECT * FROM categories ORDER BY kind, name COLLATE NOCASE") fun observeAll(): Flow<List<CategoryEntity>>
    @Query("SELECT * FROM categories") suspend fun getAll(): List<CategoryEntity>
    @Query("SELECT * FROM categories ORDER BY kind, name COLLATE NOCASE") suspend fun getAllSorted(): List<CategoryEntity>
    @Query("SELECT COUNT(*) FROM categories") suspend fun count(): Int
    @Query("SELECT * FROM categories WHERE id = :id") suspend fun get(id: Long): CategoryEntity?
    @Insert suspend fun insert(e: CategoryEntity): Long
    @Insert suspend fun insertAll(e: List<CategoryEntity>)
    @Update suspend fun update(e: CategoryEntity)
    @Query("DELETE FROM categories WHERE id = :id") suspend fun delete(id: Long)
    @Query("SELECT COUNT(*) FROM categories WHERE parent_id = :id") suspend fun childCount(id: Long): Int
    @Query("UPDATE categories SET parent_id = NULL WHERE parent_id = :id") suspend fun detachChildren(id: Long)
}

@Dao
interface PartyDao {
    @Query("SELECT * FROM parties ORDER BY archived, name COLLATE NOCASE") fun observeAll(): Flow<List<PartyEntity>>
    @Query("SELECT * FROM parties") suspend fun getAll(): List<PartyEntity>
    @Query("SELECT * FROM parties ORDER BY archived, name COLLATE NOCASE") suspend fun getAllSorted(): List<PartyEntity>
    @Insert suspend fun insert(e: PartyEntity): Long
    @Insert suspend fun insertAll(e: List<PartyEntity>)
    @Update suspend fun update(e: PartyEntity)
    @Query("DELETE FROM parties WHERE id = :id") suspend fun delete(id: Long)
}

@Dao
interface TransactionDao {
    @Query("UPDATE transactions SET cleared_on = :date WHERE id = :id") suspend fun setCleared(id: Long, date: Long?)
    @Query("UPDATE transactions SET to_cleared_on = :date WHERE id = :id") suspend fun setToCleared(id: Long, date: Long?)
    @Query("SELECT * FROM transactions WHERE deleted_at IS NULL") fun observeLive(): Flow<List<TransactionEntity>>
    @Query("SELECT * FROM transactions WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC") fun observeDeleted(): Flow<List<TransactionEntity>>
    @Query("SELECT * FROM transactions WHERE deleted_at IS NULL") suspend fun getLive(): List<TransactionEntity>
    @Query("SELECT * FROM transactions WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC") suspend fun getDeleted(): List<TransactionEntity>
    @Query("SELECT * FROM transactions") suspend fun getAll(): List<TransactionEntity>
    @Query("SELECT * FROM transactions WHERE id = :id") suspend fun get(id: Long): TransactionEntity?
    @Insert suspend fun insert(e: TransactionEntity): Long
    @Insert suspend fun insertAll(e: List<TransactionEntity>)
    @Update suspend fun update(e: TransactionEntity)
    @Query("UPDATE transactions SET deleted_at = :at WHERE id = :id") suspend fun softDelete(id: Long, at: Long)
    @Query("UPDATE transactions SET deleted_at = NULL WHERE id = :id") suspend fun restore(id: Long)
    @Query("DELETE FROM transactions WHERE id = :id") suspend fun deletePermanently(id: Long)
    @Query("SELECT id FROM transactions WHERE deleted_at IS NOT NULL AND deleted_at < :before") suspend fun deletedBefore(before: Long): List<Long>
    @Query("SELECT id FROM transactions WHERE deleted_at IS NOT NULL") suspend fun allDeletedIds(): List<Long>
    @Query("SELECT COUNT(*) FROM transactions WHERE cashbook_id = :cashbookId") suspend fun countForCashbook(cashbookId: Long): Int
    @Query("SELECT COUNT(*) FROM transactions WHERE account_id = :accountId OR to_account_id = :accountId") suspend fun countForAccount(accountId: Long): Int
    @Query("SELECT COUNT(*) FROM transactions WHERE category_id = :categoryId") suspend fun countForCategory(categoryId: Long): Int
    @Query("SELECT COUNT(*) FROM transactions WHERE party_id = :partyId") suspend fun countForParty(partyId: Long): Int
    @Query("UPDATE transactions SET category_id = :to, updated_at = :at WHERE category_id = :from") suspend fun reassignCategory(from: Long, to: Long, at: Long)
    @Query("SELECT id FROM transactions WHERE cashbook_id IN (:cashbookIds)") suspend fun idsForCashbooks(cashbookIds: List<Long>): List<Long>
    @Query("SELECT COUNT(*) FROM transactions WHERE recurring_id = :ruleId AND date = :date") suspend fun countForRuleOn(ruleId: Long, date: Long): Int
}

@Dao
interface AttachmentDao {
    @Query("SELECT transaction_id, COUNT(*) AS count FROM attachments GROUP BY transaction_id") fun observeCounts(): Flow<List<AttachmentCount>>
    @Query("SELECT transaction_id, COUNT(*) AS count FROM attachments GROUP BY transaction_id") suspend fun getCounts(): List<AttachmentCount>
    @Query("SELECT * FROM attachments WHERE transaction_id = :txnId ORDER BY id") fun observeFor(txnId: Long): Flow<List<AttachmentEntity>>
    @Query("SELECT * FROM attachments WHERE transaction_id = :txnId ORDER BY id") suspend fun getFor(txnId: Long): List<AttachmentEntity>
    @Query("SELECT * FROM attachments WHERE transaction_id IN (:txnIds)") suspend fun getForMany(txnIds: List<Long>): List<AttachmentEntity>
    @Query("SELECT * FROM attachments") suspend fun getAll(): List<AttachmentEntity>
    @Insert suspend fun insert(e: AttachmentEntity): Long
    @Insert suspend fun insertAll(e: List<AttachmentEntity>)
    @Query("DELETE FROM attachments WHERE id = :id") suspend fun delete(id: Long)
}

@Dao
interface BackupHistoryDao {
    @Query("SELECT * FROM backup_history ORDER BY created_at DESC LIMIT 20") fun observeRecent(): Flow<List<BackupHistoryEntity>>
    @Insert suspend fun insert(e: BackupHistoryEntity): Long
}

@Dao
interface MaintenanceDao {
    @Query("DELETE FROM attachments") suspend fun clearAttachments()
    @Query("DELETE FROM transactions") suspend fun clearTransactions()
    @Query("DELETE FROM accounts") suspend fun clearAccounts()
    @Query("DELETE FROM cashbooks") suspend fun clearCashbooks()
    @Query("DELETE FROM parties") suspend fun clearParties()
    @Query("DELETE FROM categories") suspend fun clearCategories()
}

@Dao
interface RecurringDao {
    @Query("SELECT * FROM recurring ORDER BY active DESC, id") suspend fun getAll(): List<RecurringEntity>
    @Query("SELECT * FROM recurring WHERE id = :id") suspend fun get(id: Long): RecurringEntity?
    @Insert suspend fun insert(e: RecurringEntity): Long
    @Insert suspend fun insertAll(e: List<RecurringEntity>)
    @Update suspend fun update(e: RecurringEntity)
    @Query("DELETE FROM recurring WHERE id = :id") suspend fun delete(id: Long)
    @Query("UPDATE recurring SET next_index = :next, updated_at = :at WHERE id = :id") suspend fun setNextIndex(id: Long, next: Int, at: Long)
    @Query("SELECT COUNT(*) FROM recurring WHERE account_id = :accountId OR to_account_id = :accountId") suspend fun countForAccount(accountId: Long): Int
    @Query("SELECT COUNT(*) FROM recurring WHERE category_id = :categoryId") suspend fun countForCategory(categoryId: Long): Int
    @Query("SELECT COUNT(*) FROM recurring WHERE party_id = :partyId") suspend fun countForParty(partyId: Long): Int
    @Query("UPDATE recurring SET category_id = :to, updated_at = :at WHERE category_id = :from") suspend fun reassignCategory(from: Long, to: Long, at: Long)
    @Query("DELETE FROM recurring") suspend fun clear()
}

@Dao
interface CatalogDao {
    @Query("SELECT * FROM catalog_items ORDER BY archived, name COLLATE NOCASE") suspend fun getAll(): List<CatalogItemEntity>
    @Query("SELECT * FROM catalog_items WHERE id = :id") suspend fun get(id: Long): CatalogItemEntity?
    @Query("SELECT COUNT(*) FROM catalog_items WHERE name = :name COLLATE NOCASE AND id != :exceptId") suspend fun countName(name: String, exceptId: Long): Int
    @Insert suspend fun insert(e: CatalogItemEntity): Long
    @Insert suspend fun insertAll(e: List<CatalogItemEntity>)
    @Update suspend fun update(e: CatalogItemEntity)
    @Query("DELETE FROM catalog_items WHERE id = :id") suspend fun delete(id: Long)
    @Query("DELETE FROM catalog_items") suspend fun clear()
    @Query("SELECT COUNT(*) FROM invoice_items WHERE item_id = :id") suspend fun countLines(id: Long): Int

    @Query("SELECT * FROM stock_adjustments ORDER BY date, id") suspend fun adjustments(): List<StockAdjustmentEntity>
    @Insert suspend fun insertAdjustment(e: StockAdjustmentEntity): Long
    @Insert suspend fun insertAdjustments(e: List<StockAdjustmentEntity>)
    @Query("DELETE FROM stock_adjustments WHERE id = :id") suspend fun deleteAdjustment(id: Long)
    @Query("DELETE FROM stock_adjustments") suspend fun clearAdjustments()
}

@Dao
interface BudgetDao {
    @Query("SELECT * FROM budgets") suspend fun getAll(): List<BudgetEntity>
    @Query("SELECT * FROM budgets WHERE cashbook_id = :cashbookId AND category_id = :categoryId") suspend fun find(cashbookId: Long, categoryId: Long): BudgetEntity?
    @Insert suspend fun insert(e: BudgetEntity): Long
    @Insert suspend fun insertAll(e: List<BudgetEntity>)
    @Update suspend fun update(e: BudgetEntity)
    @Query("DELETE FROM budgets WHERE id = :id") suspend fun delete(id: Long)
    @Query("DELETE FROM budgets") suspend fun clear()
}

@Dao
interface ReconcileDao {
    @Query("SELECT * FROM reconciliations ORDER BY statement_date DESC, id DESC") suspend fun reconciliations(): List<ReconciliationEntity>
    @Insert suspend fun insert(e: ReconciliationEntity): Long
    @Insert suspend fun insertAll(e: List<ReconciliationEntity>)
    @Query("DELETE FROM reconciliations") suspend fun clear()
    @Query("SELECT * FROM cash_counts ORDER BY date DESC, id DESC") suspend fun cashCounts(): List<CashCountEntity>
    @Insert suspend fun insertCount(e: CashCountEntity): Long
    @Insert suspend fun insertCounts(e: List<CashCountEntity>)
    @Query("DELETE FROM cash_counts WHERE id = :id") suspend fun deleteCount(id: Long)
    @Query("DELETE FROM cash_counts") suspend fun clearCounts()
}

@Dao
interface InvoiceDao {
    @Query("SELECT * FROM invoices ORDER BY due_date, id") suspend fun getAll(): List<InvoiceEntity>
    @Query("SELECT * FROM invoices WHERE id = :id") suspend fun get(id: Long): InvoiceEntity?
    @Query("SELECT number FROM invoices WHERE cashbook_id = :cashbookId AND kind = :kind") suspend fun numbers(cashbookId: Long, kind: String): List<String>
    @Query("SELECT COUNT(*) FROM invoices WHERE cashbook_id = :cashbookId AND kind = :kind AND doc_type = :docType AND number = :number COLLATE NOCASE AND id != :exceptId")
    suspend fun countNumber(cashbookId: Long, kind: String, docType: String, number: String, exceptId: Long): Int
    @Query("SELECT number FROM invoices WHERE cashbook_id = :cashbookId AND kind = :kind AND doc_type = :docType") suspend fun numbersOf(cashbookId: Long, kind: String, docType: String): List<String>
    @Query("SELECT COUNT(*) FROM invoices WHERE ref_invoice_id = :invoiceId AND doc_type IN ('CREDIT_NOTE', 'DEBIT_NOTE')") suspend fun countNotes(invoiceId: Long): Int
    @Query("UPDATE invoices SET converted_invoice_id = :invoiceId, updated_at = :now WHERE id = :quoteId") suspend fun linkQuote(quoteId: Long, invoiceId: Long, now: Long)
    /** Re-opens quotations whose invoice is being deleted. */
    @Query("UPDATE invoices SET converted_invoice_id = NULL WHERE converted_invoice_id = :invoiceId") suspend fun unlinkQuotes(invoiceId: Long)
    @Query("SELECT COUNT(*) FROM invoices WHERE party_id = :partyId") suspend fun countForParty(partyId: Long): Int
    @Insert suspend fun insert(e: InvoiceEntity): Long
    @Insert suspend fun insertAll(e: List<InvoiceEntity>)
    @Update suspend fun update(e: InvoiceEntity)
    @Query("DELETE FROM invoices WHERE id = :id") suspend fun delete(id: Long)
    @Query("DELETE FROM invoices") suspend fun clear()

    @Query("SELECT * FROM allocations") suspend fun allocations(): List<AllocationEntity>
    @Query("SELECT * FROM allocations WHERE invoice_id = :invoiceId") suspend fun allocationsFor(invoiceId: Long): List<AllocationEntity>
    @Query("SELECT * FROM allocations WHERE invoice_id = :invoiceId AND transaction_id = :txnId") suspend fun allocation(invoiceId: Long, txnId: Long): AllocationEntity?
    @Insert suspend fun insertAllocation(e: AllocationEntity): Long
    @Insert suspend fun insertAllocations(e: List<AllocationEntity>)
    @Query("UPDATE allocations SET amount = :amount WHERE id = :id") suspend fun updateAllocation(id: Long, amount: Long)
    @Query("DELETE FROM allocations WHERE id = :id") suspend fun deleteAllocation(id: Long)
    @Query("DELETE FROM allocations WHERE transaction_id = :txnId") suspend fun deleteAllocationsForTxn(txnId: Long)
    @Query("DELETE FROM allocations") suspend fun clearAllocations()

    @Query("SELECT COUNT(*) FROM invoices WHERE schedule_id = :scheduleId AND issue_date = :date") suspend fun countForScheduleOn(scheduleId: Long, date: Long): Int
    @Query("UPDATE invoices SET schedule_id = NULL WHERE schedule_id = :scheduleId") suspend fun unlinkSchedule(scheduleId: Long)

    @Query("SELECT * FROM invoice_schedules ORDER BY id") suspend fun schedules(): List<InvoiceScheduleEntity>
    @Query("SELECT * FROM invoice_schedules WHERE id = :id") suspend fun schedule(id: Long): InvoiceScheduleEntity?
    @Query("SELECT * FROM invoice_schedules WHERE template_id = :templateId") suspend fun scheduleForTemplate(templateId: Long): InvoiceScheduleEntity?
    @Insert suspend fun insertSchedule(e: InvoiceScheduleEntity): Long
    @Insert suspend fun insertSchedules(e: List<InvoiceScheduleEntity>)
    @Update suspend fun updateSchedule(e: InvoiceScheduleEntity)
    @Query("UPDATE invoice_schedules SET next_index = :next, updated_at = :now WHERE id = :id") suspend fun setScheduleNext(id: Long, next: Int, now: Long)
    @Query("DELETE FROM invoice_schedules") suspend fun clearSchedules()

    @Query("SELECT * FROM invoice_items ORDER BY invoice_id, position") suspend fun items(): List<InvoiceItemEntity>
    @Insert suspend fun insertItems(e: List<InvoiceItemEntity>)
    @Query("DELETE FROM invoice_items WHERE invoice_id = :invoiceId") suspend fun deleteItems(invoiceId: Long)
    @Query("DELETE FROM invoice_items") suspend fun clearItems()
}
