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
    /** GST state code (v4). */
    @ColumnInfo(name = "state_code", defaultValue = "") val stateCode: String = "",
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
    /** Bank reconciliation (v9): date each side was cleared against a statement. */
    @ColumnInfo(name = "cleared_on") val clearedOn: Long? = null,
    @ColumnInfo(name = "to_cleared_on") val toClearedOn: Long? = null,
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
    indices = [Index(value = ["cashbook_id", "kind", "doc_type", "number"], unique = true), Index("party_id"), Index("due_date"), Index("ref_invoice_id")],
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
    /** GST place of supply (state code) — v4. */
    @ColumnInfo(name = "place_of_supply", defaultValue = "") val placeOfSupply: String = "",
    @ColumnInfo(name = "round_off", defaultValue = "1") val roundOff: Boolean = true,
    /** INVOICE, CREDIT_NOTE or DEBIT_NOTE (v5). */
    @ColumnInfo(name = "doc_type", defaultValue = "INVOICE") val docType: String = "INVOICE",
    /** Original invoice for a credit/debit note (v5; enforced in the repository). */
    @ColumnInfo(name = "ref_invoice_id") val refInvoiceId: Long? = null,
    /** For a QUOTATION: the invoice it became (v7; cleared in the repository when that invoice is deleted). */
    @ColumnInfo(name = "converted_invoice_id") val convertedInvoiceId: Long? = null,
    /** Transport details (v8). */
    @ColumnInfo(name = "vehicle_no", defaultValue = "") val vehicleNo: String = "",
    @ColumnInfo(name = "transporter", defaultValue = "") val transporter: String = "",
    @ColumnInfo(name = "lr_no", defaultValue = "") val lrNo: String = "",
    @ColumnInfo(name = "eway_bill_no", defaultValue = "") val ewayBillNo: String = "",
    /** The recurring schedule that created this invoice (v8; cleared when the schedule is deleted). */
    @ColumnInfo(name = "schedule_id") val scheduleId: Long? = null,
)

/** Recurring sales invoice (v8): the TEMPLATE document [templateId] is copied into an invoice on every scheduled date. */
@Entity(
    tableName = "invoice_schedules",
    foreignKeys = [ForeignKey(entity = InvoiceEntity::class, parentColumns = ["id"], childColumns = ["template_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index(value = ["template_id"], unique = true)],
)
data class InvoiceScheduleEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "template_id") val templateId: Long,
    val frequency: String,
    val interval: Int = 1,
    @ColumnInfo(name = "start_date") val startDate: Long,
    @ColumnInfo(name = "end_date") val endDate: Long? = null,
    @ColumnInfo(name = "next_index") val nextIndex: Int = 0,
    @ColumnInfo(name = "due_days") val dueDays: Int = 15,
    val active: Boolean = true,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

/** Invoice line (v4). Quantity in thousandths, rate in paise, discount and GST in basis points. */
@Entity(
    tableName = "invoice_items",
    foreignKeys = [ForeignKey(entity = InvoiceEntity::class, parentColumns = ["id"], childColumns = ["invoice_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("invoice_id"), Index("item_id")],
)
data class InvoiceItemEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "invoice_id") val invoiceId: Long,
    val position: Int,
    val description: String,
    val hsn: String = "",
    @ColumnInfo(name = "quantity_milli") val quantityMilli: Long,
    val unit: String = "",
    val rate: Long,
    @ColumnInfo(name = "discount_bp") val discountBp: Int = 0,
    @ColumnInfo(name = "gst_bp") val gstBp: Int = 0,
    /** Saved product/service (v6; no FK — items in use are archived, not deleted). */
    @ColumnInfo(name = "item_id") val itemId: Long? = null,
)

/** A finished bank reconciliation (v9). */
@Entity(
    tableName = "reconciliations",
    foreignKeys = [ForeignKey(entity = AccountEntity::class, parentColumns = ["id"], childColumns = ["account_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("account_id")],
)
data class ReconciliationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "account_id") val accountId: Long,
    @ColumnInfo(name = "statement_date") val statementDate: Long,
    @ColumnInfo(name = "statement_balance") val statementBalance: Long,
    val entries: Int,
    @ColumnInfo(name = "created_at") val createdAt: Long,
)

/** A cash count by denomination (v9). The adjustment entry has no FK: it can be deleted on its own. */
@Entity(
    tableName = "cash_counts",
    foreignKeys = [ForeignKey(entity = AccountEntity::class, parentColumns = ["id"], childColumns = ["account_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("account_id")],
)
data class CashCountEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "account_id") val accountId: Long,
    val date: Long,
    val counted: Long,
    val book: Long,
    val denominations: String,
    @ColumnInfo(name = "adjustment_txn_id") val adjustmentTxnId: Long? = null,
    val note: String = "",
    @ColumnInfo(name = "created_at") val createdAt: Long,
)

/** Saved product or service (v6). Quantities in thousandths, rates in paise, GST in basis points. */
@Entity(tableName = "catalog_items")
data class CatalogItemEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val kind: String,
    val hsn: String = "",
    val unit: String = "",
    @ColumnInfo(name = "sale_rate") val saleRate: Long = 0,
    @ColumnInfo(name = "purchase_rate") val purchaseRate: Long = 0,
    @ColumnInfo(name = "gst_bp") val gstBp: Int = 0,
    val description: String = "",
    @ColumnInfo(name = "opening_stock_milli") val openingStockMilli: Long = 0,
    @ColumnInfo(name = "opening_date") val openingDate: Long,
    @ColumnInfo(name = "reorder_level_milli") val reorderLevelMilli: Long = 0,
    val archived: Boolean = false,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

/** Manual stock change (v6). */
@Entity(
    tableName = "stock_adjustments",
    foreignKeys = [ForeignKey(entity = CatalogItemEntity::class, parentColumns = ["id"], childColumns = ["item_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("item_id")],
)
data class StockAdjustmentEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "item_id") val itemId: Long,
    val date: Long,
    @ColumnInfo(name = "quantity_milli") val quantityMilli: Long,
    val reason: String = "",
    @ColumnInfo(name = "created_at") val createdAt: Long,
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
