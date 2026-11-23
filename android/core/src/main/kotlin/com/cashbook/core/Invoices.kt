package com.cashbook.core

import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** SALE = money owed to you (receivable). PURCHASE = money you owe (payable). */
enum class InvoiceKind { SALE, PURCHASE;
    /** The entry type that settles this kind of invoice. */
    val paymentType: TxnType get() = if (this == SALE) TxnType.INCOME else TxnType.EXPENSE
}

enum class InvoiceStatus { OPEN, PARTIAL, OVERDUE, PAID, REFUND_DUE, CANCELLED }

/**
 * INVOICE = sales invoice / purchase bill. CREDIT_NOTE lowers what is owed on the referenced invoice
 * (return, discount, overcharge); DEBIT_NOTE raises it (extra charge). Notes are never cash movements.
 */
enum class DocType { INVOICE, CREDIT_NOTE, DEBIT_NOTE;
    /** +1 when the document adds to the amount owed, −1 when it reduces it. */
    val sign: Int get() = if (this == CREDIT_NOTE) -1 else 1
}

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
    /** GST state code where the supply is made; decides CGST+SGST (same state) vs IGST. */
    val placeOfSupply: String = "",
    val roundOff: Boolean = true,
    val docType: DocType = DocType.INVOICE,
    /** For credit/debit notes: the invoice or bill being adjusted. */
    val refInvoiceId: Long? = null,
)

/** Part (or all) of a payment entry applied to an invoice. */
data class Allocation(val id: Long, val invoiceId: Long, val txnId: Long, val amount: Long)

/**
 * Position of one invoice. [paid] is payments minus refunds; [credited]/[debited] come from its notes.
 * Net amount owed = amount + debited − credited. When more was paid than is now owed, [refundDue] > 0.
 */
data class InvoiceBalance(val invoice: InvoiceInfo, val paid: Long, val status: InvoiceStatus, val daysOverdue: Int,
                          val credited: Long = 0, val debited: Long = 0) {
    val net: Long get() = if (invoice.cancelled) 0 else invoice.amount + debited - credited
    val outstanding: Long get() = if (invoice.cancelled) 0 else (net - paid).coerceAtLeast(0)
    val refundDue: Long get() = if (invoice.cancelled) 0 else (paid - net).coerceAtLeast(0)
}

enum class AgeBucket { NOT_DUE, D0_30, D31_60, D61_90, D90_PLUS }

object Invoices {
    /**
     * Balances for [invoices]. Only allocations whose payment entry is live ([liveTxnIds]) count, so
     * moving a payment to the recycle bin re-opens the invoice and restoring it settles it again.
     */
    /** Compatibility overload: every live allocation counts as a payment (no refunds). */
    fun balances(invoices: List<InvoiceInfo>, allocations: List<Allocation>, liveTxnIds: Set<Long>, today: LocalDate): List<InvoiceBalance> =
        balances(invoices, allocations, invoices.flatMap { inv -> allocations.filter { it.invoiceId == inv.id && it.txnId in liveTxnIds }
            .map { it.txnId to inv.kind.paymentType } }.toMap(), today)

    /**
     * Balances of the INVOICE documents in [docs] (notes are folded into their invoice). Allocations count
     * only when their entry is live ([liveTxnTypes]); an entry of the payment type pays, one of the opposite
     * type (a refund) reduces what was paid. Cancelled notes are ignored.
     */
    fun balances(docs: List<InvoiceInfo>, allocations: List<Allocation>, liveTxnTypes: Map<Long, TxnType>, today: LocalDate): List<InvoiceBalance> {
        val notes = docs.filter { it.docType != DocType.INVOICE && !it.cancelled && it.refInvoiceId != null }.groupBy { it.refInvoiceId!! }
        val byInvoice = allocations.groupBy { it.invoiceId }
        return docs.filter { it.docType == DocType.INVOICE }.map { inv ->
            val paid = byInvoice[inv.id].orEmpty().sumOf { a ->
                when (liveTxnTypes[a.txnId]) { null -> 0L; inv.kind.paymentType -> a.amount; else -> -a.amount }
            }
            val credited = notes[inv.id].orEmpty().filter { it.docType == DocType.CREDIT_NOTE }.sumOf { it.amount }
            val debited = notes[inv.id].orEmpty().filter { it.docType == DocType.DEBIT_NOTE }.sumOf { it.amount }
            val net = inv.amount + debited - credited
            val overdueDays = ChronoUnit.DAYS.between(inv.dueDate, today).toInt().coerceAtLeast(0)
            val status = when {
                inv.cancelled -> InvoiceStatus.CANCELLED
                paid > net -> InvoiceStatus.REFUND_DUE
                paid >= net -> InvoiceStatus.PAID
                today.isAfter(inv.dueDate) -> InvoiceStatus.OVERDUE
                paid > 0 || credited > 0 -> InvoiceStatus.PARTIAL
                else -> InvoiceStatus.OPEN
            }
            InvoiceBalance(inv, paid, status, if (status == InvoiceStatus.OVERDUE) overdueDays else 0, credited, debited)
        }
    }

    enum class NoteError { NOT_AN_INVOICE, MORE_THAN_INVOICED, NOT_POSITIVE }

    /** A credit note can't take the invoice below zero: credits ≤ amount + debits (other notes, excluding [editingNoteId]). */
    fun validateNote(original: InvoiceInfo, docs: List<InvoiceInfo>, type: DocType, amount: Long, editingNoteId: Long = 0): NoteError? {
        if (original.docType != DocType.INVOICE || type == DocType.INVOICE) return NoteError.NOT_AN_INVOICE
        if (amount <= 0) return NoteError.NOT_POSITIVE
        val others = docs.filter { it.refInvoiceId == original.id && it.id != editingNoteId && !it.cancelled }
        val credits = others.filter { it.docType == DocType.CREDIT_NOTE }.sumOf { it.amount } + if (type == DocType.CREDIT_NOTE) amount else 0
        val debits = others.filter { it.docType == DocType.DEBIT_NOTE }.sumOf { it.amount } + if (type == DocType.DEBIT_NOTE) amount else 0
        return if (credits > original.amount + debits) NoteError.MORE_THAN_INVOICED else null
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

    enum class AllocationError { WRONG_TYPE, OTHER_CASHBOOK, CANCELLED, NOT_POSITIVE, MORE_THAN_OUTSTANDING, MORE_THAN_PAYMENT, MORE_THAN_REFUND_DUE }

    /** Checks that [amount] of [txn] may be applied to [balance]. Returns null when valid. */
    fun validateAllocation(balance: InvoiceBalance, txn: Txn, amount: Long, allocations: List<Allocation>): AllocationError? {
        val inv = balance.invoice
        val existing = allocations.filter { it.invoiceId == inv.id && it.txnId == txn.id }.sumOf { it.amount }
        val isRefund = txn.type != inv.kind.paymentType && txn.type != TxnType.TRANSFER
        return when {
            txn.type != inv.kind.paymentType && !isRefund -> AllocationError.WRONG_TYPE
            txn.cashbookId != inv.cashbookId -> AllocationError.OTHER_CASHBOOK
            inv.cancelled -> AllocationError.CANCELLED
            amount <= 0 -> AllocationError.NOT_POSITIVE
            // a refund (money back to the customer / from the supplier) only settles a refund due
            isRefund && amount > balance.refundDue + existing -> AllocationError.MORE_THAN_REFUND_DUE
            !isRefund && amount > balance.outstanding + existing -> AllocationError.MORE_THAN_OUTSTANDING
            amount > unallocated(txn, allocations, exceptInvoice = inv.id) -> AllocationError.MORE_THAN_PAYMENT
            else -> null
        }
    }

    /**
     * Next number in the series for a financial year, e.g. "INV/26-27/001" or "BILL/26-27/014".
     * Looks at existing numbers with the same prefix and continues after the highest.
     */
    fun nextNumber(kind: InvoiceKind, existing: List<String>, date: LocalDate, docType: DocType = DocType.INVOICE): String {
        val fy = FinancialYear.of(date)
        val yy = { y: Int -> (y % 100).toString().padStart(2, '0') }
        val series = when (docType) {
            DocType.INVOICE -> if (kind == InvoiceKind.SALE) "INV" else "BILL"
            DocType.CREDIT_NOTE -> if (kind == InvoiceKind.SALE) "CN" else "CN-IN"
            DocType.DEBIT_NOTE -> if (kind == InvoiceKind.SALE) "DN" else "DN-IN"
        }
        val prefix = series + "/" + yy(fy.startYear) + "-" + yy(fy.startYear + 1) + "/"
        val max = existing.filter { it.startsWith(prefix) }.mapNotNull { it.removePrefix(prefix).toIntOrNull() }.maxOrNull() ?: 0
        return prefix + (max + 1).toString().padStart(3, '0')
    }
}
