package com.cashbook.core

import java.time.LocalDate

enum class TxnType { INCOME, EXPENSE, TRANSFER }

/** How the money moved. This is *not* the account: a UPI payment still belongs to a bank account. */
enum class PaymentMode { CASH, UPI, BANK_TRANSFER, CARD, CHEQUE, OTHER }

enum class AccountType { CASH, BANK, WALLET, OTHER }

enum class CategoryKind { INCOME, EXPENSE }

enum class PartyType { CUSTOMER, SUPPLIER, EMPLOYEE, SERVICE_PROVIDER, CLIENT, OTHER }

data class CashbookInfo(
    val id: Long,
    val name: String,
    val description: String = "",
    val openingDate: LocalDate,
    val currency: String = "INR",
    val archived: Boolean = false,
    val isSample: Boolean = false,
    val createdAt: Long = 0,
)

data class AccountInfo(
    val id: Long,
    val cashbookId: Long,
    val name: String,
    val type: AccountType,
    val openingBalance: Long,
    val openingDate: LocalDate,
    val bankName: String = "",
    val last4: String = "",
    val description: String = "",
    val archived: Boolean = false,
)

data class CategoryInfo(
    val id: Long,
    val kind: CategoryKind,
    val name: String,
    val parentId: Long? = null,
    val icon: String = "category",
    val archived: Boolean = false,
)

data class PartyInfo(
    val id: Long,
    val name: String,
    val type: PartyType = PartyType.OTHER,
    val mobile: String = "",
    val email: String = "",
    val address: String = "",
    val gstin: String = "",
    val notes: String = "",
    val archived: Boolean = false,
)

/**
 * A single ledger entry. A transfer is stored as ONE row (source = [accountId],
 * destination = [toAccountId]) so that its two sides can never get out of sync when
 * it is edited, deleted or restored.
 */
data class Txn(
    val id: Long,
    val cashbookId: Long,
    val type: TxnType,
    val date: LocalDate,
    val amount: Long,
    val accountId: Long,
    val toAccountId: Long? = null,
    val categoryId: Long? = null,
    val partyId: Long? = null,
    val paymentMode: PaymentMode = PaymentMode.CASH,
    val description: String = "",
    val reference: String = "",
    val notes: String = "",
    val tags: String = "",
    val createdAt: Long = 0,
    val updatedAt: Long = 0,
    val deletedAt: Long? = null,
) {
    val tagList: List<String> get() = tags.split(',').map { it.trim() }.filter { it.isNotEmpty() }
}

/** Consistent ordering for entries sharing a date: date, then entry time, then id. */
val TxnChronological: Comparator<Txn> = compareBy<Txn>({ it.date }, { it.createdAt }, { it.id })
