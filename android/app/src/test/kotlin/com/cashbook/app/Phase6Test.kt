package com.cashbook.app

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.LedgerRepository.CatalogException
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.core.CatalogItem
import com.cashbook.core.DateRange
import com.cashbook.core.DocType
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceKind
import com.cashbook.core.ItemKind
import com.cashbook.core.Stock
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Saved products/services and stock worked out from invoices, bills, notes and adjustments. */
@RunWith(AndroidJUnit4::class)
class Phase6Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    private data class F(val cb: Long, val customer: Long, val supplier: Long, val toner: Long, val audit: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveParty(PartyEntity(name = "Office Mart", type = "SUPPLIER", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveCatalogItem(CatalogItem(0, "Toner cartridge", ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 10_000, openingDate = today.minusDays(30), reorderLevelMilli = 8_000)),
            repo.saveCatalogItem(CatalogItem(0, "Audit fees", ItemKind.SERVICE, "998221", "Nos", 5_000_000, 0, 1800)))
    }
    private fun line(id: Long, qty: Long, rate: Long) = InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = qty, unit = "Nos", rate = rate, gstBp = 1800, itemId = id)
    private suspend fun doc(f: F, kind: InvoiceKind, number: String, lines: List<InvoiceItem>, type: DocType = DocType.INVOICE, ref: Long? = null) =
        repo.saveInvoice(InvoiceInfo(0, f.cb, kind, number, if (kind == InvoiceKind.SALE) f.customer else f.supplier, today, today.plusDays(15), 1,
            placeOfSupply = "27", docType = type, refInvoiceId = ref), lines, "27")

    @Test fun stockFromBillsSalesNotesAndAdjustments() = runBlocking {
        val f = fixture()
        doc(f, InvoiceKind.PURCHASE, "BILL/1", listOf(line(f.toner, 20_000, 180_000)))          // +20
        val sale = doc(f, InvoiceKind.SALE, "INV/1", listOf(line(f.toner, 12_000, 250_000),
            InvoiceItem(description = "Audit fees", quantityMilli = 1000, rate = 5_000_000, gstBp = 1800, itemId = f.audit)))   // −12
        doc(f, InvoiceKind.SALE, "CN/1", listOf(line(f.toner, 2_000, 250_000)), DocType.CREDIT_NOTE, sale)                    // +2 returned
        repo.addStockAdjustment(f.toner, today, -1_000, "Damaged")                                                              // −1
        val s = d.snap { it.stockAdjustments.size == 1 && it.invoices.size == 3 }
        val toner = s.catalogById[f.toner]!!
        assertEquals(19_000L, s.onHand(toner))                                                    // 10 + 20 − 12 + 2 − 1
        assertEquals(1L, s.invoiceItems[sale]!!.count { it.itemId == f.toner }.toLong())          // link survives save/load
        val line = Stock.summary(s.catalog, s.stockMoves, DateRange(today, today)).single()       // services aren't stocked
        assertEquals(19_000L, line.closing)
        assertEquals(3_420_000L, line.value)                                                       // 19 × 1,800
        val sales = Stock.itemSales(s.invoices, s.invoiceItems, s.catalogById, "27", DateRange(today, today))
        assertEquals(10_000L, sales.first { it.itemId == f.toner }.quantityMilli)                  // 12 sold − 2 returned
        // removing the adjustment and cancelling nothing else restores stock
        repo.deleteStockAdjustment(s.stockAdjustments.single().id)
        assertEquals(20_000L, d.snap { it.stockAdjustments.isEmpty() }.let { it.onHand(it.catalogById[f.toner]!!) })
    }

    @Test fun namesUniqueAndUsedItemsCannotBeDeleted() = runBlocking {
        val f = fixture()
        try { repo.saveCatalogItem(CatalogItem(0, "toner CARTRIDGE")); fail() } catch (e: CatalogException) { assertEquals(CatalogException.Reason.DUPLICATE_NAME, e.reason) }
        doc(f, InvoiceKind.SALE, "INV/1", listOf(line(f.toner, 1_000, 250_000)))
        try { repo.deleteCatalogItem(f.toner); fail() } catch (e: CatalogException) { assertEquals(CatalogException.Reason.IN_USE, e.reason) }
        repo.setCatalogItemArchived(f.toner, true)
        repo.deleteCatalogItem(f.audit)                                                             // unused: can be deleted
        val s = d.snap { it.catalog.size == 1 }
        assertTrue(s.catalog.single().archived)
    }

    @Test fun backupCarriesCatalogueAdjustmentsAndLinks() = runBlocking {
        val f = fixture()
        val inv = doc(f, InvoiceKind.SALE, "INV/1", listOf(line(f.toner, 3_000, 250_000)))
        repo.addStockAdjustment(f.toner, today, 5_000, "Counted")
        d.snap { it.stockAdjustments.isNotEmpty() && it.invoices.isNotEmpty() }
        val file = File(context().cacheDir, "p6.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb)); repo.deleteStockAdjustment(d.snap { true }.stockAdjustments.single().id)
        d.snap { it.invoices.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        val s = d.snap { it.catalog.size == 2 && it.stockAdjustments.size == 1 }
        assertEquals(f.toner, s.invoiceItems[inv]!!.single().itemId)
        assertEquals(12_000L, s.onHand(s.catalogById[f.toner]!!))                                   // 10 − 3 + 5
    }
}
