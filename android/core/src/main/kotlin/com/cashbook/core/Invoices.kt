package com.cashbook.core

import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** SALE = money owed to you (receivable). PURCHASE = money you owe (payable). */
enum class InvoiceKind { SALE, PURCHASE;
    /** The entry type that settles this kind of invoice. */
    val paymentType: TxnType get() = if (this == SALE) TxnType.INCOME else TxnType.EXPENSE
}

enum class InvoiceStatus { OPEN, PARTIAL, OVERDUE, PAID, CANCELLED }

/**
 * An invoice or bill is a *demand*, not a cash movement: it never changes an account balance.
 * Money only moves when a payment entry (income for SALE, expense for PURCHASE) is recorded and
 * linked to it through [Allocation]s. This keeps the cashbook on a cash basis while tracking
 * what is still owed.
 */
data class InvoiceInfo(
    val id: Long,
    val cashbookId: Long,
    val kind: InvoiceKind,
    val number: String,
    val partyId: Long,
    val issueDate: LocalDate,
    val dueDate: LocalDate,
    val amount: Long,
    val description: String = "",
    val notes: String = "",
    val cancelled: Boolean = false,
)

/** Part (or all) of a payment entry applied to an invoice. */
data class Allocation(val id: Long, val invoiceId: Long, val txnId: Long, val amount: Long)

data class InvoiceBalance(val invoice: InvoiceInfo, val paid: Long, val status: InvoiceStatus, val daysOverdue: Int) {
    val outstanding: Long get() = if (invoice.cancelled) 0 else (invoice.amount - paid).coerceAtLeast(0)
}

enum class AgeBucket { NOT_DUE, D0_30, D31_60, D61_90, D90_PLUS }

object Invoices {
    /**
     * Balances for [invoices]. Only allocations whose payment entry is live ([liveTxnIds]) count, so
     * moving a payment to the recycle bin re-opens the invoice and restoring it settles it again.
     */
    fun balances(invoices: List<InvoiceInfo>, allocations: List<Allocation>, liveTxnIds: Set<Long>, today: LocalDate): List<InvoiceBalance> {
        val paidBy = allocations.filter { it.txnId in liveTxnIds }.groupBy { it.invoiceId }.mapValues { (_, l) -> l.sumOf { it.amount } }
        return invoices.map { inv ->
            val paid = paidBy[inv.id] ?: 0L
            val overdueDays = ChronoUnit.DAYS.between(inv.dueDate, today).toInt().coerceAtLeast(0)
            val status = when {
                inv.cancelled -> InvoiceStatus.CANCELLED
                paid >= inv.amount -> InvoiceStatus.PAID
                today.isAfter(inv.dueDate) -> InvoiceStatus.OVERDUE
                paid > 0 -> InvoiceStatus.PARTIAL
                else -> InvoiceStatus.OPEN
            }
            InvoiceBalance(inv, paid, status, if (status == InvoiceStatus.OVERDUE) overdueDays else 0)
        }
    }

    fun bucket(b: InvoiceBalance): AgeBucket = when {
        b.daysOverdue <= 0 -> AgeBucket.NOT_DUE
        b.daysOverdue <= 30 -> AgeBucket.D0_30
        b.daysOverdue <= 60 -> AgeBucket.D31_60
        b.daysOverdue <= 90 -> AgeBucket.D61_90
        else -> AgeBucket.D90_PLUS
    }

    /** Amount of a payment entry not yet applied to any invoice (ignoring [exceptInvoice] when editing its allocation). */
    fun unallocated(txn: Txn, allocations: List<Allocation>, exceptInvoice: Long? = null): Long =
        txn.amount - allocations.filter { it.txnId == txn.id && it.invoiceId != exceptInvoice }.sumOf { it.amount }

    enum class AllocationError { WRONG_TYPE, OTHER_CASHBOOK, CANCELLED, NOT_POSITIVE, MORE_THAN_OUTSTANDING, MORE_THAN_PAYMENT }

    /** Checks that [amount] of [txn] may be applied to [balance]. Returns null when valid. */
    fun validateAllocation(balance: InvoiceBalance, txn: Txn, amount: Long, allocations: List<Allocation>): AllocationError? {
        val inv = balance.invoice
        val existing = allocations.filter { it.invoiceId == inv.id && it.txnId == txn.id }.sumOf { it.amount }
        return when {
            txn.type != inv.kind.paymentType -> AllocationError.WRONG_TYPE
            txn.cashbookId != inv.cashbookId -> AllocationError.OTHER_CASHBOOK
            inv.cancelled -> AllocationError.CANCELLED
            amount <= 0 -> AllocationError.NOT_POSITIVE
            amount > balance.outstanding + existing -> AllocationError.MORE_THAN_OUTSTANDING
            amount > unallocated(txn, allocations, exceptInvoice = inv.id) -> AllocationError.MORE_THAN_PAYMENT
            else -> null
        }
    }

    /**
     * Next number in the series for a financial year, e.g. "INV/26-27/001" or "BILL/26-27/014".
     * Looks at existing numbers with the same prefix and continues after the highest.
     */
    fun nextNumber(kind: InvoiceKind, existing: List<String>, date: LocalDate): String {
        val fy = FinancialYear.of(date)
        val yy = { y: Int -> (y % 100).toString().padStart(2, '0') }
        val prefix = (if (kind == InvoiceKind.SALE) "INV" else "BILL") + "/" + yy(fy.startYear) + "-" + yy(fy.startYear + 1) + "/"
        val max = existing.filter { it.startsWith(prefix) }.mapNotNull { it.removePrefix(prefix).toIntOrNull() }.maxOrNull() ?: 0
        return prefix + (max + 1).toString().padStart(3, '0')
    }
}
