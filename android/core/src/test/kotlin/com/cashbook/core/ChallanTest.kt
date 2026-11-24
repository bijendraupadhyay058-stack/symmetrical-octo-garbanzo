package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class ChallanTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)
    private val toner = CatalogItem(1, "Toner", ItemKind.GOODS, "8443", "Nos", saleRate = 250_000, gstBp = 1800, openingStockMilli = 20_000, openingDate = d(4, 1))
    private fun dc(id: Long, date: LocalDate, converted: Long? = null, cancelled: Boolean = false, party: Long = 9) =
        InvoiceInfo(id, 1, InvoiceKind.SALE, "DC/$id", party, date, date, 500_000, docType = DocType.CHALLAN, convertedInvoiceId = converted, cancelled = cancelled)
    private fun line(qty: Long) = InvoiceItem(description = "Toner", quantityMilli = qty, rate = 250_000, gstBp = 1800, itemId = 1)

    @Test fun stockLeavesOnTheChallanAndOnlyOnce() {
        val inv = InvoiceInfo(10, 1, InvoiceKind.SALE, "INV/1", 9, d(4, 30), d(5, 15), 1_180_000)
        val docs = listOf(dc(1, d(4, 5), converted = 10), dc(2, d(4, 12), converted = 10), dc(3, d(4, 20)), dc(4, d(4, 22), cancelled = true), inv)
        val items = mapOf(1L to listOf(line(2_000)), 2L to listOf(line(3_000)), 3L to listOf(line(1_000)), 4L to listOf(line(9_000)),
            10L to listOf(line(2_000), line(3_000)))
        val moves = Stock.moves(docs, items, emptyList())
        assertEquals(listOf(d(4, 5), d(4, 12), d(4, 20)), moves.map { it.date })         // the invoice and cancelled challan don't move stock
        assertEquals(20_000L - 2_000 - 3_000, Stock.onHand(toner, moves, d(4, 15)))
        assertEquals(14_000L, Stock.onHand(toner, moves, d(5, 31)))
        // a normal invoice (not billed from challans) still moves stock
        assertEquals(1, Stock.moves(listOf(inv), items, emptyList()).count { it.quantityMilli == -2_000L })
    }

    @Test fun challansOweNothingAndNeverExpire() {
        assertTrue(Invoices.balances(listOf(dc(1, d(4, 5))), emptyList(), emptyMap<Long, TxnType>(), d(4, 6)).isEmpty())
        assertEquals(QuoteStatus.OPEN, Quotations.status(dc(1, d(4, 5)), d(12, 31)))
        assertEquals(QuoteStatus.CONVERTED, Quotations.status(dc(1, d(4, 5), converted = 10), d(4, 6)))
        assertEquals(QuoteStatus.DECLINED, Quotations.status(dc(1, d(4, 5), cancelled = true), d(4, 6)))
        assertEquals(0, DocType.CHALLAN.sign)
        assertTrue(DocType.CHALLAN.isOffBook && !DocType.CHALLAN.isNote)
        assertEquals("DC/26-27/003", Invoices.nextNumber(InvoiceKind.SALE, listOf("DC/26-27/002", "INV/26-27/009"), d(5, 1), DocType.CHALLAN))
        assertEquals(listOf(1L, 2L), Quotations.sourcesOf(10, listOf(dc(2, d(4, 12), converted = 10), dc(1, d(4, 5), converted = 10), dc(3, d(4, 20)))).map { it.id })
    }

    @Test fun challansBilledTogether() {
        assertNull(Quotations.validateChallans(listOf(dc(1, d(4, 5)), dc(2, d(4, 6)))))
        assertEquals(Quotations.ChallanError.EMPTY, Quotations.validateChallans(emptyList()))
        assertEquals(Quotations.ChallanError.ALREADY_BILLED, Quotations.validateChallans(listOf(dc(1, d(4, 5), converted = 7))))
        assertEquals(Quotations.ChallanError.CANCELLED, Quotations.validateChallans(listOf(dc(1, d(4, 5), cancelled = true))))
        assertEquals(Quotations.ChallanError.MIXED_PARTIES, Quotations.validateChallans(listOf(dc(1, d(4, 5)), dc(2, d(4, 6), party = 8))))
        assertEquals(Quotations.ChallanError.NOT_A_CHALLAN, Quotations.validateChallans(listOf(dc(1, d(4, 5)).copy(docType = DocType.QUOTATION))))
    }

    @Test fun reportsIgnoreChallans() {
        val items = mapOf(1L to listOf(line(2_000)))
        assertTrue(Stock.itemSales(listOf(dc(1, d(4, 5))), items, mapOf(1L to toner), "27", DateRange(d(4, 1), d(4, 30))).isEmpty())
        val r = ReportEngine(ReportInput(ReportType.PARTY_STATEMENT, "Office", accounts = SampleScenario.accounts, categories = emptyMap(),
            parties = mapOf(9L to PartyInfo(9, "ABC")), txns = emptyList(), range = DateRange(d(4, 1), d(4, 30)), generatedAt = "now",
            invoices = listOf(dc(1, d(4, 5))), invoiceItems = items)).build()
        assertTrue(r.tables.all { it.rows.isEmpty() })
    }
}
