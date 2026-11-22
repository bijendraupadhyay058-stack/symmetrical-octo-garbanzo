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
        assertEquals(Invoices.AllocationError.WRONG_TYPE, Invoices.validateAllocation(bal, pay2.copy(type = TxnType.EXPENSE), 1, allocs))
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
}
