package com.cashbook.app.data

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.room.withTransaction
import com.cashbook.app.BuildConfig
import com.cashbook.app.data.db.AccountEntity
import com.cashbook.app.data.db.AppDatabase
import com.cashbook.app.data.db.AttachmentEntity
import com.cashbook.app.data.db.BackupHistoryEntity
import com.cashbook.app.data.db.BudgetEntity
import com.cashbook.app.data.db.AllocationEntity
import com.cashbook.app.data.db.InvoiceEntity
import com.cashbook.app.data.db.InvoiceItemEntity
import com.cashbook.app.data.db.RecurringEntity
import com.cashbook.app.data.db.CashbookEntity
import com.cashbook.app.data.db.CategoryEntity
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.data.db.TransactionEntity
import com.cashbook.core.backup.AccountDto
import com.cashbook.core.backup.AttachmentDto
import com.cashbook.core.backup.AttachmentSource
import com.cashbook.core.backup.BackupCodec
import com.cashbook.core.backup.BackupData
import com.cashbook.core.backup.BackupException
import com.cashbook.core.backup.BackupManifest
import com.cashbook.core.backup.BudgetDto
import com.cashbook.core.backup.AllocationDto
import com.cashbook.core.backup.InvoiceDto
import com.cashbook.core.backup.InvoiceItemDto
import com.cashbook.core.backup.RecurringDto
import com.cashbook.core.backup.CashbookDto
import com.cashbook.core.backup.CategoryDto
import com.cashbook.core.backup.DecodedBackup
import com.cashbook.core.backup.PartyDto
import com.cashbook.core.backup.TransactionDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.first
import java.io.File

/**
 * Creates and restores encrypted backups through the Storage Access Framework, so the user can
 * save to the device, an SD card or any cloud provider that appears in the Android file picker.
 */
class BackupManager(
    private val context: Context,
    private val db: AppDatabase,
    private val store: AttachmentStore,
    private val settings: SettingsRepository,
) {
    private val stagingDir get() = File(context.filesDir, "restore_staging")

    suspend fun createBackup(uri: Uri, password: CharArray, includeAttachments: Boolean): Result<Long> = withContext(Dispatchers.IO) {
        val name = displayName(uri)
        try {
            val data = exportData(includeAttachments)
            val manifest = BackupManifest(
                appVersion = BuildConfig.VERSION_NAME, createdAt = System.currentTimeMillis(),
                cashbooks = data.cashbooks.size, accounts = data.accounts.size, categories = data.categories.size,
                parties = data.parties.size, transactions = data.transactions.size, attachments = data.attachments.size,
                includesAttachments = includeAttachments, recurring = data.recurring.size, budgets = data.budgets.size, invoices = data.invoices.size,
            )
            val sources = data.attachments.map { a -> AttachmentSource(a.storedName) { store.file(a.storedName).takeIf { it.exists() }?.inputStream() } }
            val out = context.contentResolver.openOutputStream(uri, "wt") ?: error("Cannot open destination")
            BackupCodec.write(out, password, manifest, data, sources)
            val size = querySize(uri)
            db.backups().insert(BackupHistoryEntity(createdAt = manifest.createdAt, kind = "BACKUP", fileName = name,
                includesAttachments = includeAttachments, sizeBytes = size, success = true))
            settings.update { it.copy(lastBackupAt = manifest.createdAt) }
            Result.success(size)
        } catch (e: Throwable) {
            runCatching { DocumentsContract.deleteDocument(context.contentResolver, uri) }
            db.backups().insert(BackupHistoryEntity(createdAt = System.currentTimeMillis(), kind = "BACKUP", fileName = name,
                includesAttachments = includeAttachments, sizeBytes = 0, success = false, message = e.javaClass.simpleName))
            Result.failure(e)
        } finally {
            password.fill(' ')
        }
    }

    /**
     * Step 1 of a restore: decrypt, authenticate and validate the whole file and stage its
     * attachments. Nothing in the current data is touched.
     */
    suspend fun inspect(uri: Uri, password: CharArray): Result<DecodedBackup> = withContext(Dispatchers.IO) {
        stagingDir.deleteRecursively(); stagingDir.mkdirs()
        try {
            val input = context.contentResolver.openInputStream(uri) ?: throw BackupException(BackupException.Reason.NOT_A_BACKUP)
            val decoded = input.use { s ->
                BackupCodec.read(s.buffered(), password) { name, stream -> File(stagingDir, name).outputStream().use { stream.copyTo(it) } }
            }
            Result.success(decoded)
        } catch (e: Throwable) {
            stagingDir.deleteRecursively()
            Result.failure(e)
        } finally {
            password.fill(' ')
        }
    }

    fun discardStaging() { stagingDir.deleteRecursively() }

    /**
     * Step 2: replace all data inside one database transaction. If anything fails the transaction
     * rolls back, so the existing data is preserved. Attachment files are swapped only after the
     * database commit succeeds.
     */
    suspend fun restore(backup: DecodedBackup, fileName: String): Result<Unit> = withContext(Dispatchers.IO) {
        val d = backup.data
        try {
            db.withTransaction {
                // children first
                db.invoices().clearItems(); db.invoices().clearAllocations(); db.invoices().clear(); db.budgets().clear(); db.recurring().clear()
                db.maintenance().apply {
                    clearAttachments(); clearTransactions(); clearAccounts(); clearCashbooks(); clearParties(); clearCategories()
                }
                db.cashbooks().insertAll(d.cashbooks.map { CashbookEntity(it.id, it.name, it.description, it.openingDate, it.currency, it.createdAt, it.updatedAt, it.archived, it.isSample) })
                // parents before sub-categories (parent_id has no FK, but keep order tidy)
                db.categories().insertAll(d.categories.sortedBy { if (it.parentId == null) 0 else 1 }.map {
                    CategoryEntity(it.id, it.kind, it.name, it.parentId, it.icon, it.archived, it.createdAt, it.updatedAt) })
                db.parties().insertAll(d.parties.map { PartyEntity(it.id, it.name, it.type, it.mobile, it.email, it.address, it.gstin, it.notes, it.archived, it.createdAt, it.updatedAt, it.stateCode) })
                db.accounts().insertAll(d.accounts.map { AccountEntity(it.id, it.cashbookId, it.name, it.type, it.openingBalance, it.openingDate, it.bankName, it.last4, it.description, it.archived, it.sortOrder, it.createdAt, it.updatedAt) })
                db.transactions().insertAll(d.transactions.map { TransactionEntity(it.id, it.cashbookId, it.type, it.date, it.amount, it.accountId, it.toAccountId, it.categoryId, it.partyId, it.paymentMode, it.description, it.reference, it.notes, it.tags, it.createdAt, it.updatedAt, it.deletedAt, it.recurringId) })
                db.recurring().insertAll(d.recurring.map { RecurringEntity(it.id, it.cashbookId, it.type, it.amount, it.accountId, it.toAccountId, it.categoryId,
                    it.partyId, it.paymentMode, it.description, it.reference, it.notes, it.tags, it.frequency, it.interval, it.startDate, it.endDate,
                    it.nextIndex, it.autoPost, it.active, it.createdAt, it.updatedAt) })
                db.budgets().insertAll(d.budgets.map { BudgetEntity(it.id, it.cashbookId, it.categoryId, it.monthlyAmount, it.createdAt, it.updatedAt) })
                db.invoices().insertAll(d.invoices.map { InvoiceEntity(it.id, it.cashbookId, it.kind, it.number, it.partyId, it.issueDate, it.dueDate, it.amount,
                    it.description, it.notes, it.cancelled, it.createdAt, it.updatedAt, it.placeOfSupply, it.roundOff) })
                db.invoices().insertItems(d.invoiceItems.map { InvoiceItemEntity(it.id, it.invoiceId, it.position, it.description, it.hsn, it.quantityMilli, it.unit,
                    it.rate, it.discountBp, it.gstBp) })
                db.invoices().insertAllocations(d.allocations.map { AllocationEntity(it.id, it.invoiceId, it.transactionId, it.amount, it.createdAt) })
                // Only keep attachment rows whose file was actually in the backup
                db.attachments().insertAll(d.attachments.filter { it.storedName in backup.attachmentFiles }.map {
                    AttachmentEntity(it.id, it.transactionId, it.fileName, it.mimeType, it.sizeBytes, it.storedName, it.createdAt) })
            }
        } catch (e: Throwable) {
            stagingDir.deleteRecursively()
            db.backups().insert(BackupHistoryEntity(createdAt = System.currentTimeMillis(), kind = "RESTORE", fileName = fileName,
                includesAttachments = backup.manifest.includesAttachments, sizeBytes = 0, success = false, message = e.javaClass.simpleName))
            return@withContext Result.failure(e)
        }
        // Swap attachment folders
        val current = store.dir
        val old = File(context.filesDir, "attachments_old")
        old.deleteRecursively()
        current.renameTo(old)
        if (!stagingDir.renameTo(File(context.filesDir, "attachments"))) {
            File(context.filesDir, "attachments").mkdirs()
            stagingDir.listFiles()?.forEach { it.copyTo(File(context.filesDir, "attachments/${it.name}"), overwrite = true) }
            stagingDir.deleteRecursively()
        }
        old.deleteRecursively()
        val firstCb = d.cashbooks.firstOrNull { !it.archived }?.id ?: d.cashbooks.firstOrNull()?.id ?: 0
        d.businessProfile?.let { settings.updateBusinessProfile(it) }
        settings.update { s ->
            val ids = d.cashbooks.map { it.id }.toSet()
            s.copy(
                onboarded = true,
                defaultCashbookId = if (s.defaultCashbookId in ids) s.defaultCashbookId else firstCb,
                currentCashbookId = if (s.currentCashbookId in ids || s.currentCashbookId == AppSettings.ALL_CASHBOOKS) s.currentCashbookId else firstCb,
                defaultAccountId = if (d.accounts.any { it.id == s.defaultAccountId }) s.defaultAccountId else 0,
            )
        }
        db.backups().insert(BackupHistoryEntity(createdAt = System.currentTimeMillis(), kind = "RESTORE", fileName = fileName,
            includesAttachments = backup.manifest.includesAttachments, sizeBytes = 0, success = true))
        Result.success(Unit)
    }

    private suspend fun exportData(includeAttachments: Boolean): BackupData = BackupData(
        cashbooks = db.cashbooks().getAll().map { CashbookDto(it.id, it.name, it.description, it.openingDate, it.currency, it.createdAt, it.updatedAt, it.archived, it.isSample) },
        accounts = db.accounts().getAll().map { AccountDto(it.id, it.cashbookId, it.name, it.type, it.openingBalance, it.openingDate, it.bankName, it.last4, it.description, it.archived, it.sortOrder, it.createdAt, it.updatedAt) },
        categories = db.categories().getAll().map { CategoryDto(it.id, it.kind, it.name, it.parentId, it.icon, it.archived, it.createdAt, it.updatedAt) },
        parties = db.parties().getAll().map { PartyDto(it.id, it.name, it.type, it.mobile, it.email, it.address, it.gstin, it.notes, it.archived, it.createdAt, it.updatedAt, it.stateCode) },
        transactions = db.transactions().getAll().map { TransactionDto(it.id, it.cashbookId, it.type, it.date, it.amount, it.accountId, it.toAccountId, it.categoryId, it.partyId, it.paymentMode, it.description, it.reference, it.notes, it.tags, it.createdAt, it.updatedAt, it.deletedAt, it.recurringId) },
        recurring = db.recurring().getAll().map { RecurringDto(it.id, it.cashbookId, it.type, it.amount, it.accountId, it.toAccountId, it.categoryId, it.partyId,
            it.paymentMode, it.description, it.reference, it.notes, it.tags, it.frequency, it.interval, it.startDate, it.endDate, it.nextIndex, it.autoPost,
            it.active, it.createdAt, it.updatedAt) },
        budgets = db.budgets().getAll().map { BudgetDto(it.id, it.cashbookId, it.categoryId, it.monthlyAmount, it.createdAt, it.updatedAt) },
        invoices = db.invoices().getAll().map { InvoiceDto(it.id, it.cashbookId, it.kind, it.number, it.partyId, it.issueDate, it.dueDate, it.amount,
            it.description, it.notes, it.cancelled, it.createdAt, it.updatedAt, it.placeOfSupply, it.roundOff) },
        invoiceItems = db.invoices().items().map { InvoiceItemDto(it.id, it.invoiceId, it.position, it.description, it.hsn, it.quantityMilli, it.unit, it.rate,
            it.discountBp, it.gstBp) },
        businessProfile = settings.businessProfile.first(),
        allocations = db.invoices().allocations().map { AllocationDto(it.id, it.invoiceId, it.transactionId, it.amount, it.createdAt) },
        attachments = if (!includeAttachments) emptyList() else db.attachments().getAll().map { AttachmentDto(it.id, it.transactionId, it.fileName, it.mimeType, it.sizeBytes, it.storedName, it.createdAt) },
    )

    fun displayName(uri: Uri): String =
        runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull() ?: uri.lastPathSegment ?: "backup"

    private fun querySize(uri: Uri): Long = runCatching {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else 0L
        }
    }.getOrNull() ?: 0L
}
