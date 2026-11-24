package com.cashbook.app

import androidx.room.withTransaction
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.db.AllocationEntity
import com.cashbook.app.data.db.CatalogItemEntity
import com.cashbook.app.data.db.InvoiceEntity
import com.cashbook.app.data.db.InvoiceItemEntity
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.data.db.TransactionEntity
import com.cashbook.app.ui.invoices.overdueCustomers
import com.cashbook.core.DateRange
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceKind
import com.cashbook.core.Ledger
import com.cashbook.core.ReportEngine
import com.cashbook.core.ReportInput
import com.cashbook.core.ReportType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate

/**
 * A busy shop after a few years: 30,000 entries, 300 parties, 5,000 invoices with 10,000 lines and 3,000 payment
 * links, 200 products. Checks the whole-ledger snapshot and the main screens' calculations stay quick.
 */
@RunWith(AndroidJUnit4::class)
class ScaleTest {
    private val d = deps()
    private fun ms(start: Long) = (System.nanoTime() - start) / 1_000_000

    @Test fun largeLedgerStaysResponsive(): Unit = runBlocking {
        val cb = d.ledger.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val acc = s.accounts.filter { it.cashbookId == cb }.map { it.id }
        val income = s.categories.first { it.kind == com.cashbook.core.CategoryKind.INCOME }.id
        val expense = s.categories.first { it.kind == com.cashbook.core.CategoryKind.EXPENSE }.id
        val today = LocalDate.now(); val start = today.minusDays(1095)
        val db = d.db
        val seedStart = System.nanoTime()
        db.withTransaction {
            db.parties().insertAll((1..300).map { PartyEntity(id = 10_000L + it, name = "Party $it", type = if (it % 3 == 0) "SUPPLIER" else "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27") })
            db.catalog().insertAll((1..200).map { CatalogItemEntity(20_000L + it, "Item $it", "GOODS", "8443", "Nos", 10_000, 7_000, 1800, "", 500_000, start.toEpochDay(), 10_000, false, 0, 0) })
            db.transactions().insertAll((1..30_000).map { i ->
                val inc = i % 2 == 0
                TransactionEntity(id = 100_000L + i, cashbookId = cb, type = if (inc) "INCOME" else "EXPENSE", date = start.plusDays((i % 1095).toLong()).toEpochDay(),
                    amount = 10_000L + i % 5000, accountId = acc[i % acc.size], categoryId = if (inc) income else expense, partyId = 10_001L + i % 300,
                    paymentMode = "UPI", description = "Entry $i", createdAt = 0, updatedAt = 0)
            })
            db.invoices().insertAll((1..5_000).map { i ->
                val issue = start.plusDays((i % 1080).toLong())
                InvoiceEntity(id = 200_000L + i, cashbookId = cb, kind = if (i % 4 == 0) "PURCHASE" else "SALE", number = "INV/$i", partyId = 10_001L + i % 300,
                    issueDate = issue.toEpochDay(), dueDate = issue.plusDays(15).toEpochDay(), amount = 23_600, createdAt = 0, updatedAt = 0, placeOfSupply = "27")
            })
            db.invoices().insertItems((1..5_000).flatMap { i -> (0..1).map { p ->
                InvoiceItemEntity(invoiceId = 200_000L + i, position = p, description = "Item", quantityMilli = 1_000, rate = 10_000, gstBp = 1800, itemId = 20_001L + (i + p) % 200) } })
            db.invoices().insertAllocations((1..3_000).map { i -> AllocationEntity(invoiceId = 200_000L + i * 1L, transactionId = 100_000L + i * 2L, amount = 10_000, createdAt = 0) })
        }
        val seed = ms(seedStart)

        var t = System.nanoTime()
        s = d.snap(60_000) { it.txns.size > 30_000 && it.invoices.size == 5_000 }
        val firstLoad = ms(t)

        // one edit → full snapshot reload (what every save costs the UI)
        t = System.nanoTime()
        d.ledger.saveInvoice(InvoiceInfo(0, cb, InvoiceKind.SALE, "INV/NEW", 10_001, today, today.plusDays(15), 11_800))
        s = d.snap(60_000) { it.invoices.size == 5_001 }
        val reload = ms(t)

        t = System.nanoTime(); val balances = s.invoiceBalances(); val bal1 = ms(t)
        t = System.nanoTime(); repeat(10) { s.invoiceBalances() }; val bal10 = ms(t)
        t = System.nanoTime(); s.accounts.forEach { Ledger.balanceAsOf(it, s.txns, today) }; val accBal = ms(t)
        t = System.nanoTime(); val stock = s.catalog.map { s.onHand(it) }; val stockMs = ms(t)
        t = System.nanoTime(); val overdue = overdueCustomers(s, setOf(cb), today); val overdueMs = ms(t)
        fun report(type: ReportType) = ReportEngine(ReportInput(type, "Office", accounts = s.accounts, categories = s.categoryById, parties = s.partyById,
            txns = s.txns, range = DateRange(today.minusYears(1), today), generatedAt = "now", invoices = s.invoices, allocations = s.allocations,
            invoiceItems = s.invoiceItems, sellerState = "27", catalog = s.catalog, adjustments = s.stockAdjustments)).build()
        val reportMs = ReportType.entries.associateWith { type -> System.nanoTime().let { t0 -> report(type); ms(t0) } }

        println("SCALE seed=${seed}ms firstLoad=${firstLoad}ms reloadAfterEdit=${reload}ms invoiceBalances=${bal1}ms (x10 ${bal10}ms) " +
            "accountBalances=${accBal}ms stock(200)=${stockMs}ms overdue=${overdueMs}ms reports=$reportMs")
        assertEquals(5_001, balances.size)
        assertEquals(200, stock.size)
        assertTrue(overdue.isNotEmpty())
        // generous bounds: these are regressions guards for the JVM test runner, not phone timings
        assertTrue("reload took ${reload}ms", reload < 15_000)
        assertTrue("invoice balances took ${bal1}ms", bal1 < 3_000)
        assertTrue("reports took $reportMs", reportMs.values.all { it < 10_000 })
    }
}
