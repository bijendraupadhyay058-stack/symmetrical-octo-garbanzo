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
)

@Serializable
data class TransactionDto(
    val id: Long, val cashbookId: Long, val type: String, val date: Long, val amount: Long, val accountId: Long,
    val toAccountId: Long? = null, val categoryId: Long? = null, val partyId: Long? = null, val paymentMode: String,
    val description: String = "", val reference: String = "", val notes: String = "", val tags: String = "",
    val createdAt: Long, val updatedAt: Long, val deletedAt: Long? = null,
)

@Serializable
data class AttachmentDto(
    val id: Long, val transactionId: Long, val fileName: String, val mimeType: String, val sizeBytes: Long,
    val storedName: String, val createdAt: Long,
)

@Serializable
data class BackupData(
    val cashbooks: List<CashbookDto>,
    val accounts: List<AccountDto>,
    val categories: List<CategoryDto>,
    val parties: List<PartyDto>,
    val transactions: List<TransactionDto>,
    val attachments: List<AttachmentDto>,
)
