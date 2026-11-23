package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class StatementTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)
    private val acc = SampleScenario.cash.id
    private val customer = PartyInfo(9, "ABC Enterprises"); private val supplier = PartyInfo(8, "Office Mart")
    private val inv1 = InvoiceInfo(1, 1, InvoiceKind.SALE, "INV/1", 9, d(3, 10), d(3, 25), 1_000_000)
    private val inv2 = InvoiceInfo(2, 1, InvoiceKind.SALE, "INV/2", 9, d(4, 5), d(4, 20), 500_000)
    private val cn = InvoiceInfo(3, 1, InvoiceKind.SALE, "CN/1", 9, d(4, 8), d(4, 8), 100_000, docType = DocType.CREDIT_NOTE, refInvoiceId = 2)
    private val bill = InvoiceInfo(4, 1, InvoiceKind.PURCHASE, "BILL/1", 8, d(4, 3), d(4, 18), 200_000)
    private val cancelled = InvoiceInfo(5, 1, InvoiceKind.SALE, "INV/3", 9, d(4, 6), d(4, 21), 900_000, cancelled = true)
    private val quote = InvoiceInfo(6, 1, InvoiceKind.SALE, "QT/1", 9, d(4, 7), d(4, 21), 700_000, docType = DocType.QUOTATION)
    private val txns = listOf(
        Txn(10, 1, TxnType.INCOME, d(3, 20), 400_000, acc, partyId = 9),                                         // before the period
        Txn(11, 1, TxnType.INCOME, d(4, 10), 300_000, acc, partyId = 9, paymentMode = PaymentMode.UPI, reference = "UTR123"),
        Txn(12, 1, TxnType.EXPENSE, d(4, 4), 200_000, acc, partyId = 8, paymentMode = PaymentMode.BANK_TRANSFER),
        Txn(13, 1, TxnType.INCOME, d(4, 12), 50_000, acc, partyId = 9),                                          // not linked to an invoice
    )
    private val allocs = listOf(Allocation(1, 1, 10, 400_000), Allocation(2, 1, 11, 300_000), Allocation(3, 4, 12, 200_000),
        Allocation(4, 2, 99, 100_000))                                                                             // entry 99 is in the recycle bin

    private fun doc(parties: Set<Long> = emptySet()) = ReportEngine(ReportInput(ReportType.PARTY_STATEMENT, "Office", accounts = SampleScenario.accounts,
        categories = emptyMap(), parties = mapOf(9L to customer, 8L to supplier), txns = txns, range = DateRange(d(4, 1), d(4, 30)), generatedAt = "now",
        invoices = listOf(inv1, inv2, cn, bill, cancelled, quote), allocations = allocs, filter = TxnFilter(partyIds = parties))).build()

    @Test fun customerStatementRunsFromOpeningToClosing() {
        val r = doc(setOf(9))
        val rows = r.tables[0].rows
        assertEquals(Cell.Text("ABC Enterprises"), rows[0].cells[0])
        assertEquals(listOf(Cell.Day(d(4, 1)), Cell.Text("Opening balance"), Cell.Empty, Cell.Empty, Cell.Amount(600_000)), rows[1].cells)   // 10,000 − 4,000
        assertEquals(listOf(Cell.Day(d(4, 5)), Cell.Text("Invoice INV/2"), Cell.Amount(500_000), Cell.Empty, Cell.Amount(1_100_000)), rows[2].cells)
        assertEquals(listOf(Cell.Day(d(4, 8)), Cell.Text("Credit note CN/1"), Cell.Empty, Cell.Amount(100_000), Cell.Amount(1_000_000)), rows[3].cells)
        assertEquals(listOf(Cell.Day(d(4, 10)), Cell.Text("Received – UPI (INV/1) · UTR123"), Cell.Empty, Cell.Amount(300_000), Cell.Amount(700_000)), rows[4].cells)
        // closing = outstanding (INV/1 3,000 + INV/2 4,000); the cancelled invoice, quotation and binned payment don't count
        assertEquals(listOf(Cell.Day(d(4, 30)), Cell.Text("Closing balance"), Cell.Amount(500_000), Cell.Amount(400_000), Cell.Amount(700_000)), rows[5].cells)
        assertEquals(RowStyle.SUBTOTAL, rows[5].style)
        assertEquals(6, rows.size)
        assertTrue(r.tables[1].rows.isEmpty())                                  // supplier filtered out
        assertEquals(Cell.Amount(700_000), r.summary.first { it.label.startsWith("Receivable") }.value)
        assertEquals(Cell.Amount(50_000), r.summary.first { it.label == "Receipts not linked to invoices" }.value)
        val outstanding = Invoices.balances(listOf(inv1, inv2, cn), allocs, txns.associate { it.id to it.type }, d(4, 30)).sumOf { it.outstanding }
        assertEquals(700_000L, outstanding)
    }

    @Test fun supplierSideUsesCreditForBills() {
        val rows = doc().tables[1].rows
        assertEquals(Cell.Text("Office Mart"), rows[0].cells[0])
        assertEquals(listOf(Cell.Day(d(4, 3)), Cell.Text("Bill BILL/1"), Cell.Empty, Cell.Amount(200_000), Cell.Amount(200_000)), rows[2].cells)
        assertEquals(listOf(Cell.Day(d(4, 4)), Cell.Text("Paid – Bank transfer (BILL/1)"), Cell.Amount(200_000), Cell.Empty, Cell.Amount(0)), rows[3].cells)
        assertEquals(Cell.Amount(0), rows.last().cells[4])
    }

    @Test fun whatsappNumbers() {
        assertEquals("919876543210", Reminders.whatsappNumber("98765 43210"))
        assertEquals("919876543210", Reminders.whatsappNumber("+91-98765-43210"))
        assertEquals("919876543210", Reminders.whatsappNumber("098765 43210"))
        assertEquals("919876543210", Reminders.whatsappNumber("91 9876543210"))
        assertEquals("447700900123", Reminders.whatsappNumber("+44 7700 900123"))
        assertEquals("971501234567", Reminders.whatsappNumber("00971 50 123 4567"))
        listOf("", "12345", "022 2345 6789", "5876543210", "+0 123456789").forEach { assertNull(it, Reminders.whatsappNumber(it)) }
        assertEquals("https://wa.me/919876543210?text=Invoice%20INV%2F1%0ADue%3A%20%E2%82%B91", Reminders.whatsappLink("919876543210", "Invoice INV/1\nDue: ₹1"))
    }

    @Test fun purchaseOrderNumbering() {
        assertEquals("PO/26-27/001", Invoices.nextNumber(InvoiceKind.PURCHASE, listOf("QT/26-27/004"), d(5, 1), DocType.QUOTATION))
        assertEquals("QT/26-27/005", Invoices.nextNumber(InvoiceKind.SALE, listOf("QT/26-27/004"), d(5, 1), DocType.QUOTATION))
    }
}
