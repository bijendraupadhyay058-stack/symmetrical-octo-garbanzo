package com.cashbook.core.backup

import kotlinx.serialization.Serializable

const val BACKUP_FORMAT_VERSION = 1

@Serializable
data class BackupManifest(
    val format: String = "cashbook-backup",
    val formatVersion: Int = BACKUP_FORMAT_VERSION,
    val appVersion: String,
    val createdAt: Long,
    val cashbooks: Int,
    val accounts: Int,
    val categories: Int,
    val parties: Int,
    val transactions: Int,
    val attachments: Int,
    val includesAttachments: Boolean,
    val recurring: Int = 0,
    val budgets: Int = 0,
    val invoices: Int = 0,
)

@Serializable
data class CashbookDto(
    val id: Long, val name: String, val description: String = "", val openingDate: Long, val currency: String = "INR",
    val createdAt: Long, val updatedAt: Long, val archived: Boolean = false, val isSample: Boolean = false, val isDefault: Boolean = false,
)

@Serializable
data class AccountDto(
    val id: Long, val cashbookId: Long, val name: String, val type: String, val openingBalance: Long, val openingDate: Long,
    val bankName: String = "", val last4: String = "", val description: String = "", val archived: Boolean = false,
    val sortOrder: Int = 0, val createdAt: Long, val updatedAt: Long,
)

@Serializable
data class CategoryDto(
    val id: Long, val kind: String, val name: String, val parentId: Long? = null, val icon: String = "category",
    val archived: Boolean = false, val createdAt: Long, val updatedAt: Long,
)

@Serializable
data class PartyDto(
    val id: Long, val name: String, val type: String, val mobile: String = "", val email: String = "", val address: String = "",
    val gstin: String = "", val notes: String = "", val archived: Boolean = false, val createdAt: Long, val updatedAt: Long,
    val stateCode: String = "",
)

@Serializable
data class TransactionDto(
    val id: Long, val cashbookId: Long, val type: String, val date: Long, val amount: Long, val accountId: Long,
    val toAccountId: Long? = null, val categoryId: Long? = null, val partyId: Long? = null, val paymentMode: String,
    val description: String = "", val reference: String = "", val notes: String = "", val tags: String = "",
    val createdAt: Long, val updatedAt: Long, val deletedAt: Long? = null, val recurringId: Long? = null,
)

@Serializable
data class AttachmentDto(
    val id: Long, val transactionId: Long, val fileName: String, val mimeType: String, val sizeBytes: Long,
    val storedName: String, val createdAt: Long,
)

@Serializable
data class RecurringDto(
    val id: Long, val cashbookId: Long, val type: String, val amount: Long, val accountId: Long, val toAccountId: Long? = null,
    val categoryId: Long? = null, val partyId: Long? = null, val paymentMode: String, val description: String = "", val reference: String = "",
    val notes: String = "", val tags: String = "", val frequency: String, val interval: Int = 1, val startDate: Long, val endDate: Long? = null,
    val nextIndex: Int = 0, val autoPost: Boolean = true, val active: Boolean = true, val createdAt: Long, val updatedAt: Long,
)

@Serializable
data class BudgetDto(val id: Long, val cashbookId: Long, val categoryId: Long, val monthlyAmount: Long, val createdAt: Long, val updatedAt: Long)

@Serializable
data class InvoiceDto(
    val id: Long, val cashbookId: Long, val kind: String, val number: String, val partyId: Long, val issueDate: Long, val dueDate: Long,
    val amount: Long, val description: String = "", val notes: String = "", val cancelled: Boolean = false, val createdAt: Long, val updatedAt: Long,
    val placeOfSupply: String = "", val roundOff: Boolean = true,
    val docType: String = "INVOICE", val refInvoiceId: Long? = null,
)

@Serializable
data class InvoiceItemDto(
    val id: Long, val invoiceId: Long, val position: Int, val description: String, val hsn: String = "", val quantityMilli: Long, val unit: String = "",
    val rate: Long, val discountBp: Int = 0, val gstBp: Int = 0, val itemId: Long? = null,
)

@Serializable
data class CatalogItemDto(
    val id: Long, val name: String, val kind: String = "GOODS", val hsn: String = "", val unit: String = "", val saleRate: Long = 0, val purchaseRate: Long = 0,
    val gstBp: Int = 0, val description: String = "", val openingStockMilli: Long = 0, val openingDate: Long, val reorderLevelMilli: Long = 0,
    val archived: Boolean = false, val createdAt: Long, val updatedAt: Long,
)

@Serializable
data class StockAdjustmentDto(val id: Long, val itemId: Long, val date: Long, val quantityMilli: Long, val reason: String = "", val createdAt: Long)

/** Seller details printed on invoices (from Settings › Business profile). */
@Serializable
data class BusinessProfileDto(
    val name: String = "", val address: String = "", val gstin: String = "", val stateCode: String = "", val phone: String = "", val email: String = "",
    val bankName: String = "", val accountName: String = "", val accountNumber: String = "", val ifsc: String = "", val upiId: String = "",
    val terms: String = "", val signatory: String = "",
)

@Serializable
data class AllocationDto(val id: Long, val invoiceId: Long, val transactionId: Long, val amount: Long, val createdAt: Long)

@Serializable
data class BackupData(
    val cashbooks: List<CashbookDto>,
    val accounts: List<AccountDto>,
    val categories: List<CategoryDto>,
    val parties: List<PartyDto>,
    val transactions: List<TransactionDto>,
    val attachments: List<AttachmentDto>,
    // Added in app 1.1 (database v2). Defaults keep 1.0 backups restorable.
    val recurring: List<RecurringDto> = emptyList(),
    val budgets: List<BudgetDto> = emptyList(),
    // Added in app 1.2 (database v3).
    val invoices: List<InvoiceDto> = emptyList(),
    val allocations: List<AllocationDto> = emptyList(),
    // Added in app 1.3 (database v4).
    val invoiceItems: List<InvoiceItemDto> = emptyList(),
    val businessProfile: BusinessProfileDto? = null,
    // Added in app 1.5 (database v6).
    val catalog: List<CatalogItemDto> = emptyList(),
    val stockAdjustments: List<StockAdjustmentDto> = emptyList(),
)
