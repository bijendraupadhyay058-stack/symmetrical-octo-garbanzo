package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class StockTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)
    private val toner = CatalogItem(1, "Toner cartridge", ItemKind.GOODS, "8443", "Nos", saleRate = 250_000, purchaseRate = 180_000, gstBp = 1800,
        openingStockMilli = 10_000, openingDate = d(4, 1), reorderLevelMilli = 5_000)
    private val audit = CatalogItem(2, "Audit", ItemKind.SERVICE, "998221", "Nos", saleRate = 5_000_000)
    private fun doc(id: Long, kind: InvoiceKind, type: DocType, date: LocalDate, cancelled: Boolean = false) =
        InvoiceInfo(id, 1, kind, "D$id", 9, date, date, 1, cancelled = cancelled, docType = type, placeOfSupply = "27")
    private fun line(item: CatalogItem, qty: Long, rate: Long = item.saleRate) = InvoiceItem(description = item.name, quantityMilli = qty, rate = rate, gstBp = item.gstBp, itemId = item.id)

    private val docs = listOf(
        doc(1, InvoiceKind.PURCHASE, DocType.INVOICE, d(4, 5)),        // +20 toner
        doc(2, InvoiceKind.SALE, DocType.INVOICE, d(4, 10)),           // −12 toner, audit service
        doc(3, InvoiceKind.SALE, DocType.CREDIT_NOTE, d(4, 12)),       // +2 returned
        doc(4, InvoiceKind.PURCHASE, DocType.CREDIT_NOTE, d(4, 15)),   // −3 back to supplier
        doc(5, InvoiceKind.SALE, DocType.DEBIT_NOTE, d(4, 16)),        // price only: no stock
        doc(6, InvoiceKind.SALE, DocType.INVOICE, d(4, 18), cancelled = true),
        doc(7, InvoiceKind.SALE, DocType.INVOICE, d(5, 2)),            // −4 in May
    )
    private val items = mapOf(
        1L to listOf(line(toner, 20_000, 180_000)),
        2L to listOf(line(toner, 12_000), line(audit, 1_000)),
        3L to listOf(line(toner, 2_000)),
        4L to listOf(line(toner, 3_000, 180_000)),
        5L to listOf(line(toner, 1_000, 10_000)),
        6L to listOf(line(toner, 50_000)),
        7L to listOf(line(toner, 4_000), InvoiceItem(description = "Courier charges", quantityMilli = 1000, rate = 10_000, gstBp = 1800)),
    )
    private val adj = listOf(StockAdjustment(1, 1, d(4, 20), -1_000, "Damaged"))

    @Test fun stockFollowsDocumentsAndAdjustments() {
        val moves = Stock.moves(docs, items, adj)
        assertEquals(10_000L + 20_000 - 12_000 + 2_000 - 3_000 - 1_000, Stock.onHand(toner, moves, d(4, 30)))   // 16
        assertEquals(12_000L, Stock.onHand(toner, moves, d(5, 31)))
        assertEquals(0L, Stock.onHand(toner, moves, d(3, 31)))                                               // before opening date
        val april = Stock.summary(listOf(toner, audit), moves, DateRange(d(4, 1), d(4, 30))).single()      // services aren't stocked
        assertEquals(0L, april.opening)
        assertEquals(30_000L + 2_000, april.inward)        // opening 10 introduced + 20 bought + 2 returned
        assertEquals(15_000L, april.outward)               // 12 sold + 3 returned to supplier
        assertEquals(-1_000L, april.adjusted)
        assertEquals(16_000L, april.closing)
        assertEquals(2_880_000L, april.value)              // 16 × 1,800
        assertFalse(april.low)
        val may = Stock.summary(listOf(toner), moves, DateRange(d(5, 1), d(5, 31))).single()
        assertEquals(16_000L, may.opening); assertEquals(12_000L, may.closing); assertFalse(may.low)
        assertTrue(Stock.summary(listOf(toner.copy(reorderLevelMilli = 12_000)), moves, DateRange(d(5, 1), d(5, 31))).single().low)
    }

    @Test fun itemSalesNetOfCreditNotes() {
        val sales = Stock.itemSales(docs, items, listOf(toner, audit).associateBy { it.id }, "27", DateRange(d(4, 1), d(5, 31)))
        val t = sales.first { it.itemId == 1L }
        assertEquals(14_000L, t.quantityMilli)                         // 12 + 4 − 2 returned (debit note and cancelled ignored)
        assertEquals(3_500_000L, t.taxable)                            // 14 × 2,500
        assertEquals(630_000L, t.tax)
        assertEquals(5_000_000L, sales.first { it.itemId == 2L }.taxable)
        assertEquals("Courier charges", sales.first { it.itemId == null }.name)
        assertEquals(2L, sales.first().itemId)                         // sorted by value
    }

    @Test fun stockReport() {
        val doc = ReportEngine(ReportInput(ReportType.STOCK_SUMMARY, "Shop", accounts = SampleScenario.accounts, categories = emptyMap(), parties = emptyMap(),
            txns = emptyList(), range = DateRange(d(4, 1), d(4, 30)), generatedAt = "now", invoices = docs, invoiceItems = items,
            catalog = listOf(toner, audit), adjustments = adj)).build()
        assertEquals(Cell.Amount(2_880_000), doc.summary[1].value)
        assertEquals(Cell.Text("16"), doc.tables[0].rows[0].cells[6])
    }
}
