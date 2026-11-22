package com.cashbook.app.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/*
 * Room schema. Amounts are INTEGER paise; dates are epoch days (LocalDate.toEpochDay());
 * timestamps are epoch milliseconds. Enum columns store the enum name from :core.
 */

@Entity(tableName = "cashbooks")
data class CashbookEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val description: String = "",
    @ColumnInfo(name = "opening_date") val openingDate: Long,
    val currency: String = "INR",
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
    val archived: Boolean = false,
    @ColumnInfo(name = "is_sample") val isSample: Boolean = false,
)

@Entity(
    tableName = "accounts",
    foreignKeys = [ForeignKey(entity = CashbookEntity::class, parentColumns = ["id"], childColumns = ["cashbook_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("cashbook_id")],
)
data class AccountEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "cashbook_id") val cashbookId: Long,
    val name: String,
    val type: String,
    @ColumnInfo(name = "opening_balance") val openingBalance: Long,
    @ColumnInfo(name = "opening_date") val openingDate: Long,
    @ColumnInfo(name = "bank_name") val bankName: String = "",
    val last4: String = "",
    val description: String = "",
    val archived: Boolean = false,
    @ColumnInfo(name = "sort_order") val sortOrder: Int = 0,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

@Entity(tableName = "categories", indices = [Index("parent_id")])
data class CategoryEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val kind: String,
    val name: String,
    @ColumnInfo(name = "parent_id") val parentId: Long? = null,
    val icon: String = "category",
    val archived: Boolean = false,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

@Entity(tableName = "parties")
data class PartyEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val type: String,
    val mobile: String = "",
    val email: String = "",
    val address: String = "",
    val gstin: String = "",
    val notes: String = "",
    val archived: Boolean = false,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

/**
 * One row per entry. Transfers are a single row (account_id = source, to_account_id =
 * destination) so both sides are always edited, deleted and restored together.
 * `deleted_at` non-null = in the recycle bin.
 */
@Entity(
    tableName = "transactions",
    foreignKeys = [
        ForeignKey(entity = CashbookEntity::class, parentColumns = ["id"], childColumns = ["cashbook_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = AccountEntity::class, parentColumns = ["id"], childColumns = ["account_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = AccountEntity::class, parentColumns = ["id"], childColumns = ["to_account_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = CategoryEntity::class, parentColumns = ["id"], childColumns = ["category_id"], onDelete = ForeignKey.RESTRICT),
        ForeignKey(entity = PartyEntity::class, parentColumns = ["id"], childColumns = ["party_id"], onDelete = ForeignKey.RESTRICT),
    ],
    indices = [Index("cashbook_id"), Index("account_id"), Index("to_account_id"), Index("category_id"), Index("party_id"), Index("date"), Index("deleted_at"),
        Index("recurring_id")],
)
data class TransactionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "cashbook_id") val cashbookId: Long,
    val type: String,
    val date: Long,
    val amount: Long,
    @ColumnInfo(name = "account_id") val accountId: Long,
    @ColumnInfo(name = "to_account_id") val toAccountId: Long? = null,
    @ColumnInfo(name = "category_id") val categoryId: Long? = null,
    @ColumnInfo(name = "party_id") val partyId: Long? = null,
    @ColumnInfo(name = "payment_mode") val paymentMode: String,
    val description: String = "",
    val reference: String = "",
    val notes: String = "",
    val tags: String = "",
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
    @ColumnInfo(name = "deleted_at") val deletedAt: Long? = null,
    /** Recurring rule that created this entry (v2). No FK: entries outlive deleted rules. */
    @ColumnInfo(name = "recurring_id") val recurringId: Long? = null,
)

/** Schedule that creates entries automatically or on confirmation (v2). */
@Entity(
    tableName = "recurring",
    foreignKeys = [
        ForeignKey(entity = CashbookEntity::class, parentColumns = ["id"], childColumns = ["cashbook_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = AccountEntity::class, parentColumns = ["id"], childColumns = ["account_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = AccountEntity::class, parentColumns = ["id"], childColumns = ["to_account_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = CategoryEntity::class, parentColumns = ["id"], childColumns = ["category_id"], onDelete = ForeignKey.RESTRICT),
        ForeignKey(entity = PartyEntity::class, parentColumns = ["id"], childColumns = ["party_id"], onDelete = ForeignKey.RESTRICT),
    ],
    indices = [Index("cashbook_id"), Index("account_id"), Index("to_account_id"), Index("category_id"), Index("party_id")],
)
data class RecurringEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "cashbook_id") val cashbookId: Long,
    val type: String,
    val amount: Long,
    @ColumnInfo(name = "account_id") val accountId: Long,
    @ColumnInfo(name = "to_account_id") val toAccountId: Long? = null,
    @ColumnInfo(name = "category_id") val categoryId: Long? = null,
    @ColumnInfo(name = "party_id") val partyId: Long? = null,
    @ColumnInfo(name = "payment_mode") val paymentMode: String,
    val description: String = "",
    val reference: String = "",
    val notes: String = "",
    val tags: String = "",
    val frequency: String,
    val interval: Int = 1,
    @ColumnInfo(name = "start_date") val startDate: Long,
    @ColumnInfo(name = "end_date") val endDate: Long? = null,
    @ColumnInfo(name = "next_index") val nextIndex: Int = 0,
    @ColumnInfo(name = "auto_post") val autoPost: Boolean = true,
    val active: Boolean = true,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

/** Monthly limit for an expense category in a cashbook (v2). */
@Entity(
    tableName = "budgets",
    foreignKeys = [
        ForeignKey(entity = CashbookEntity::class, parentColumns = ["id"], childColumns = ["cashbook_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = CategoryEntity::class, parentColumns = ["id"], childColumns = ["category_id"], onDelete = ForeignKey.CASCADE),
    ],
    indices = [Index(value = ["cashbook_id", "category_id"], unique = true), Index("category_id")],
)
data class BudgetEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "cashbook_id") val cashbookId: Long,
    @ColumnInfo(name = "category_id") val categoryId: Long,
    @ColumnInfo(name = "monthly_amount") val monthlyAmount: Long,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

/** Sales invoice (receivable) or purchase bill (payable) — v3. Never changes account balances by itself. */
@Entity(
    tableName = "invoices",
    foreignKeys = [
        ForeignKey(entity = CashbookEntity::class, parentColumns = ["id"], childColumns = ["cashbook_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = PartyEntity::class, parentColumns = ["id"], childColumns = ["party_id"], onDelete = ForeignKey.RESTRICT),
    ],
    indices = [Index(value = ["cashbook_id", "kind", "number"], unique = true), Index("party_id"), Index("due_date")],
)
data class InvoiceEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "cashbook_id") val cashbookId: Long,
    val kind: String,
    val number: String,
    @ColumnInfo(name = "party_id") val partyId: Long,
    @ColumnInfo(name = "issue_date") val issueDate: Long,
    @ColumnInfo(name = "due_date") val dueDate: Long,
    val amount: Long,
    val description: String = "",
    val notes: String = "",
    val cancelled: Boolean = false,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

/** Part of a payment entry applied to an invoice — v3. Deleting either side removes the link. */
@Entity(
    tableName = "allocations",
    foreignKeys = [
        ForeignKey(entity = InvoiceEntity::class, parentColumns = ["id"], childColumns = ["invoice_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(entity = TransactionEntity::class, parentColumns = ["id"], childColumns = ["transaction_id"], onDelete = ForeignKey.CASCADE),
    ],
    indices = [Index(value = ["invoice_id", "transaction_id"], unique = true), Index("transaction_id")],
)
data class AllocationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "invoice_id") val invoiceId: Long,
    @ColumnInfo(name = "transaction_id") val transactionId: Long,
    val amount: Long,
    @ColumnInfo(name = "created_at") val createdAt: Long,
)

@Entity(
    tableName = "attachments",
    foreignKeys = [ForeignKey(entity = TransactionEntity::class, parentColumns = ["id"], childColumns = ["transaction_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("transaction_id")],
)
data class AttachmentEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "transaction_id") val transactionId: Long,
    @ColumnInfo(name = "file_name") val fileName: String,
    @ColumnInfo(name = "mime_type") val mimeType: String,
    @ColumnInfo(name = "size_bytes") val sizeBytes: Long,
    /** File name inside the app's private `attachments/` folder. */
    @ColumnInfo(name = "stored_name") val storedName: String,
    @ColumnInfo(name = "created_at") val createdAt: Long,
)

@Entity(tableName = "backup_history")
data class BackupHistoryEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    val kind: String, // BACKUP or RESTORE
    @ColumnInfo(name = "file_name") val fileName: String,
    @ColumnInfo(name = "includes_attachments") val includesAttachments: Boolean,
    @ColumnInfo(name = "size_bytes") val sizeBytes: Long,
    val success: Boolean,
    val message: String = "",
)

data class AttachmentCount(@ColumnInfo(name = "transaction_id") val transactionId: Long, val count: Int)
