package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

class InvoicesTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)
    private val inv = InvoiceInfo(1, 1, InvoiceKind.SALE, "INV/26-27/001", partyId = 9, issueDate = d(4, 1), dueDate = d(4, 30), amount = 1_000_000)
    private val pay1 = Txn(10, 1, TxnType.INCOME, d(4, 10), 400_000, 2, partyId = 9)
    private val pay2 = Txn(11, 1, TxnType.INCOME, d(5, 5), 800_000, 2, partyId = 9)
    private val allocs = listOf(Allocation(1, 1, 10, 400_000), Allocation(2, 1, 11, 600_000))

    @Test fun statusFollowsPaymentsAndDueDate() {
        fun st(live: Set<Long>, today: LocalDate) = Invoices.balances(listOf(inv), allocs, live, today).single()
        assertEquals(InvoiceStatus.OPEN, st(emptySet(), d(4, 5)).status)
        assertEquals(InvoiceStatus.PARTIAL, st(setOf(10), d(4, 15)).status)
        st(setOf(10), d(5, 20)).let { assertEquals(InvoiceStatus.OVERDUE, it.status); assertEquals(20, it.daysOverdue); assertEquals(600_000L, it.outstanding) }
        st(setOf(10, 11), d(5, 20)).let { assertEquals(InvoiceStatus.PAID, it.status); assertEquals(0L, it.outstanding) }
        // payment moved to the recycle bin re-opens the invoice
        assertEquals(600_000L, st(setOf(10), d(5, 20)).outstanding)
        assertEquals(InvoiceStatus.CANCELLED, Invoices.balances(listOf(inv.copy(cancelled = true)), allocs, emptySet(), d(6, 1)).single().status)
    }

    @Test fun ageingBuckets() {
        fun bucket(days: Long) = Invoices.bucket(Invoices.balances(listOf(inv), emptyList(), emptySet(), inv.dueDate.plusDays(days)).single())
        assertEquals(AgeBucket.NOT_DUE, bucket(0))
        assertEquals(AgeBucket.D0_30, bucket(30))
        assertEquals(AgeBucket.D31_60, bucket(31))
        assertEquals(AgeBucket.D61_90, bucket(90))
        assertEquals(AgeBucket.D90_PLUS, bucket(91))
    }

    @Test fun allocationRules() {
        val bal = Invoices.balances(listOf(inv), allocs.take(1), setOf(10), d(4, 15)).single() // 6,00,000 outstanding
        assertNull(Invoices.validateAllocation(bal, pay2, 600_000, allocs.take(1)))
        assertEquals(Invoices.AllocationError.MORE_THAN_OUTSTANDING, Invoices.validateAllocation(bal, pay2, 700_000, allocs.take(1)))
        // pay1 already fully applied to another invoice (#5): nothing left for this one
        val elsewhere = listOf(Allocation(9, 5, 10, 400_000))
        assertEquals(Invoices.AllocationError.MORE_THAN_PAYMENT, Invoices.validateAllocation(bal, pay1, 100_000, elsewhere))
        // amounts are the new total for this invoice+payment pair, so re-applying the same payment is fine
        assertNull(Invoices.validateAllocation(bal, pay1, 400_000, allocs.take(1)))
        assertEquals(Invoices.AllocationError.WRONG_TYPE, Invoices.validateAllocation(bal, pay2.copy(type = TxnType.TRANSFER), 1, allocs))  // an expense would be a refund
        assertEquals(Invoices.AllocationError.OTHER_CASHBOOK, Invoices.validateAllocation(bal, pay2.copy(cashbookId = 2), 1, allocs))
        assertEquals(Invoices.AllocationError.NOT_POSITIVE, Invoices.validateAllocation(bal, pay2, 0, allocs))
        assertEquals(200_000L, Invoices.unallocated(pay2, allocs))
    }

    @Test fun numberingPerFinancialYear() {
        assertEquals("INV/26-27/001", Invoices.nextNumber(InvoiceKind.SALE, emptyList(), d(4, 1)))
        assertEquals("INV/26-27/013", Invoices.nextNumber(InvoiceKind.SALE, listOf("INV/26-27/012", "INV/25-26/099", "X-5"), d(9, 1)))
        assertEquals("BILL/25-26/001", Invoices.nextNumber(InvoiceKind.PURCHASE, listOf("INV/25-26/004"), LocalDate.of(2026, 3, 31)))
    }

    @Test fun outstandingReportAsAtPeriodEnd() {
        val party = PartyInfo(9, "ABC Enterprises")
        val bill = InvoiceInfo(2, 1, InvoiceKind.PURCHASE, "BILL/26-27/001", 9, d(4, 2), d(4, 20), 300_000)
        fun doc(end: LocalDate) = ReportEngine(ReportInput(ReportType.OUTSTANDING, "Office", accounts = SampleScenario.accounts, categories = emptyMap(),
            parties = mapOf(9L to party), txns = listOf(pay1, pay2), range = DateRange(d(4, 1), end), generatedAt = "now",
            invoices = listOf(inv, bill), allocations = allocs)).build()
        val april = doc(d(4, 30)) // only pay1 counted
        assertEquals(Cell.Amount(600_000), april.summary[0].value)
        assertEquals(Cell.Amount(300_000), april.summary[1].value)
        val june = doc(d(6, 30))   // both payments counted: invoice settled, bill 71 days overdue
        assertEquals(Cell.Amount(0), june.summary[0].value)
        val ageing = june.tables[0]
        assertEquals(Cell.Amount(300_000), ageing.rows[3].cells[2]) // 61–90 days, payables
        assertEquals(0, june.exportTable.rows.size)
    }

    @Test fun creditAndDebitNotesAdjustWhatIsOwed() {
        val cn = inv.copy(id = 2, number = "CN/26-27/001", docType = DocType.CREDIT_NOTE, refInvoiceId = 1, amount = 200_000, issueDate = d(4, 12))
        val dn = inv.copy(id = 3, number = "DN/26-27/001", docType = DocType.DEBIT_NOTE, refInvoiceId = 1, amount = 50_000, issueDate = d(4, 13))
        val types = mapOf(10L to TxnType.INCOME)
        val b = Invoices.balances(listOf(inv, cn, dn), allocs.take(1), types, d(4, 15)).single()   // notes are folded into the invoice
        assertEquals(850_000L, b.net)                      // 10,000 − 2,000 + 500
        assertEquals(450_000L, b.outstanding)              // 8,500 − 4,000 paid
        assertEquals(InvoiceStatus.PARTIAL, b.status)
        // cancelled notes don't count
        assertEquals(1_050_000L, Invoices.balances(listOf(inv, cn.copy(cancelled = true), dn), emptyList(), emptyMap(), d(4, 15)).single().net)
    }

    @Test fun creditAfterFullPaymentMeansRefundDueAndRefundSettlesIt() {
        val cn = inv.copy(id = 2, number = "CN/1", docType = DocType.CREDIT_NOTE, refInvoiceId = 1, amount = 300_000)
        val paidFull = listOf(Allocation(1, 1, 10, 1_000_000))
        val payTypes = mapOf(10L to TxnType.INCOME)
        val b = Invoices.balances(listOf(inv, cn), paidFull, payTypes, d(4, 15)).single()
        assertEquals(InvoiceStatus.REFUND_DUE, b.status)
        assertEquals(300_000L, b.refundDue)
        assertEquals(0L, b.outstanding)
        // a refund is an entry of the opposite type (expense for a sales invoice)
        val refund = Txn(20, 1, TxnType.EXPENSE, d(4, 16), 300_000, 2, partyId = 9)
        assertNull(Invoices.validateAllocation(b, refund, 300_000, paidFull))
        assertEquals(Invoices.AllocationError.MORE_THAN_REFUND_DUE, Invoices.validateAllocation(b, refund, 300_001, paidFull))
        val after = Invoices.balances(listOf(inv, cn), paidFull + Allocation(2, 1, 20, 300_000), payTypes + (20L to TxnType.EXPENSE), d(4, 16)).single()
        assertEquals(InvoiceStatus.PAID, after.status)
        assertEquals(700_000L, after.paid)
        // with nothing to refund, a refund entry can't be applied
        val open = Invoices.balances(listOf(inv), emptyList(), emptyMap(), d(4, 15)).single()
        assertEquals(Invoices.AllocationError.MORE_THAN_REFUND_DUE, Invoices.validateAllocation(open, refund, 1, emptyList()))
    }

    @Test fun noteLimitsAndNumbering() {
        val cn = inv.copy(id = 2, number = "CN/1", docType = DocType.CREDIT_NOTE, refInvoiceId = 1, amount = 600_000)
        assertNull(Invoices.validateNote(inv, listOf(inv, cn), DocType.CREDIT_NOTE, 400_000))
        assertEquals(Invoices.NoteError.MORE_THAN_INVOICED, Invoices.validateNote(inv, listOf(inv, cn), DocType.CREDIT_NOTE, 400_001))
        assertNull(Invoices.validateNote(inv, listOf(inv, cn), DocType.CREDIT_NOTE, 1_000_000, editingNoteId = 2))  // editing replaces itself
        assertNull(Invoices.validateNote(inv, listOf(inv, cn), DocType.DEBIT_NOTE, 5_000_000))
        assertEquals(Invoices.NoteError.NOT_AN_INVOICE, Invoices.validateNote(cn, listOf(inv, cn), DocType.CREDIT_NOTE, 1))
        assertEquals("CN/26-27/001", Invoices.nextNumber(InvoiceKind.SALE, listOf("INV/26-27/004"), d(5, 1), DocType.CREDIT_NOTE))
        assertEquals("DN/26-27/003", Invoices.nextNumber(InvoiceKind.SALE, listOf("DN/26-27/002"), d(5, 1), DocType.DEBIT_NOTE))
    }

    @Test fun gstSummarySubtractsCreditNotes() {
        val one = listOf(InvoiceItem(description = "Service", quantityMilli = 1000, rate = 1_000_000, gstBp = 1800))
        val invoice = inv.copy(placeOfSupply = "27")
        val cn = invoice.copy(id = 2, number = "CN/1", docType = DocType.CREDIT_NOTE, refInvoiceId = 1, issueDate = d(4, 20))
        val doc = ReportEngine(ReportInput(ReportType.GST_SUMMARY, "Office", accounts = SampleScenario.accounts, categories = emptyMap(), parties = emptyMap(),
            txns = emptyList(), range = DateRange(d(4, 1), d(4, 30)), generatedAt = "now", invoices = listOf(invoice, cn),
            invoiceItems = mapOf(1L to one, 2L to one.map { it.copy(rate = 250_000) }), sellerState = "27")).build()
        assertEquals(Cell.Amount(180_000 - 45_000), doc.summary[0].value)   // 18 % of 10,000 minus 18 % of 2,500
    }
}
