package com.cashbook.app.data.db

import com.cashbook.core.AccountInfo
import com.cashbook.core.BudgetInfo
import com.cashbook.core.Frequency
import com.cashbook.core.RecurringRule
import com.cashbook.core.AccountType
import com.cashbook.core.CashbookInfo
import com.cashbook.core.CategoryInfo
import com.cashbook.core.CategoryKind
import com.cashbook.core.PartyInfo
import com.cashbook.core.PartyType
import com.cashbook.core.PaymentMode
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import java.time.LocalDate

private inline fun <reified T : Enum<T>> enumOr(name: String, default: T): T =
    runCatching { enumValueOf<T>(name) }.getOrDefault(default)

fun CashbookEntity.toInfo() = CashbookInfo(id, name, description, LocalDate.ofEpochDay(openingDate), currency, archived, isSample, createdAt)

fun AccountEntity.toInfo() = AccountInfo(id, cashbookId, name, enumOr(type, AccountType.OTHER), openingBalance,
    LocalDate.ofEpochDay(openingDate), bankName, last4, description, archived)

fun CategoryEntity.toInfo() = CategoryInfo(id, enumOr(kind, CategoryKind.EXPENSE), name, parentId, icon, archived)

fun PartyEntity.toInfo() = PartyInfo(id, name, enumOr(type, PartyType.OTHER), mobile, email, address, gstin, notes, archived)

fun TransactionEntity.toTxn() = Txn(id, cashbookId, enumOr(type, TxnType.EXPENSE), LocalDate.ofEpochDay(date), amount, accountId,
    toAccountId, categoryId, partyId, enumOr(paymentMode, PaymentMode.OTHER), description, reference, notes, tags, createdAt, updatedAt, deletedAt, recurringId)

fun Txn.toEntity() = TransactionEntity(id, cashbookId, type.name, date.toEpochDay(), amount, accountId, toAccountId, categoryId,
    partyId, paymentMode.name, description.trim(), reference.trim(), notes.trim(), tags.trim(), createdAt, updatedAt, deletedAt, recurringId)

fun RecurringEntity.toRule() = RecurringRule(id, cashbookId, enumOr(type, TxnType.EXPENSE), amount, accountId, toAccountId, categoryId, partyId,
    enumOr(paymentMode, PaymentMode.OTHER), description, reference, notes, tags, enumOr(frequency, Frequency.MONTHLY), interval,
    LocalDate.ofEpochDay(startDate), endDate?.let { LocalDate.ofEpochDay(it) }, nextIndex, autoPost, active)

fun RecurringRule.toEntity(createdAt: Long, updatedAt: Long) = RecurringEntity(id, cashbookId, type.name, amount, accountId,
    if (type == TxnType.TRANSFER) toAccountId else null, if (type == TxnType.TRANSFER) null else categoryId,
    if (type == TxnType.TRANSFER) null else partyId, paymentMode.name, description.trim(), reference.trim(), notes.trim(), tags.trim(),
    frequency.name, interval.coerceAtLeast(1), startDate.toEpochDay(), endDate?.toEpochDay(), nextIndex, autoPost, active, createdAt, updatedAt)

fun BudgetEntity.toInfo() = BudgetInfo(id, cashbookId, categoryId, monthlyAmount)
