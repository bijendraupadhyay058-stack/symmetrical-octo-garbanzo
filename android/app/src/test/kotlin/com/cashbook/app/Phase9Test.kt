package com.cashbook.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.LedgerRepository.InvoiceException
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.InvoicePdfWriter
import com.cashbook.app.ui.components.UiFormat
import com.cashbook.app.ui.invoices.customerReminderText
import com.cashbook.app.ui.invoices.invoicePdfStrings
import com.cashbook.app.ui.invoices.overdueCustomers
import com.cashbook.core.CatalogItem
import com.cashbook.core.DateFormatOption
import com.cashbook.core.DocType
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.ItemKind
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.QuoteStatus
import com.cashbook.core.Quotations
import com.cashbook.core.backup.BusinessProfileDto
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Delivery challans billed together in one invoice, and overdue collections. */
@RunWith(AndroidJUnit4::class)
class Phase9Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    private data class F(val cb: Long, val customer: Long, val other: Long, val toner: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", mobile = "98765 43210", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveParty(PartyEntity(name = "Metro Traders", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveCatalogItem(CatalogItem(0, "Toner cartridge", ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 20_000, openingDate = today.minusDays(60), reorderLevelMilli = 3_000)))
    }
    private fun toner(f: F, qty: Long) = InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = qty, unit = "Nos", rate = 250_000, gstBp = 1800, itemId = f.toner)
    private suspend fun challan(f: F, number: String, date: LocalDate, qty: Long, party: Long = f.customer) = repo.saveInvoice(
        InvoiceInfo(0, f.cb, InvoiceKind.PURCHASE, number, party, date, date.plusDays(30), 1, placeOfSupply = "27", docType = DocType.CHALLAN),
        listOf(toner(f, qty)), "27")

    @Test fun challansBilledTogether(): Unit = runBlocking {
        val f = fixture()
        assertTrue(repo.nextInvoiceNumber(f.cb, InvoiceKind.SALE, today, DocType.CHALLAN).startsWith("DC/"))
        val c1 = challan(f, "DC/1", today.minusDays(10), 2_000)
        val c2 = challan(f, "DC/2", today.minusDays(3), 3_000)
        val other = challan(f, "DC/3", today.minusDays(2), 1_000, party = f.other)
        var s = d.snap { it.challans.size == 3 }
        val ch = s.challans.first { it.id == c1 }
        assertEquals(InvoiceKind.SALE, ch.kind); assertEquals(ch.issueDate, ch.dueDate)               // forced: a sale, no due date
        assertEquals(590_000L, ch.amount)
        assertTrue(s.invoiceBalances().isEmpty())                                                      // nothing owed yet
        assertEquals(14_000L, s.onHand(s.catalogById[f.toner]!!))                                      // 20 − 2 − 3 − 1: stock went out
        assertEquals(18_000L, com.cashbook.core.Stock.onHand(s.catalogById[f.toner]!!, s.stockMoves, today.minusDays(5)))   // only DC/1 by then

        try { repo.convertChallans(listOf(c1, other), today); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.MIXED_PARTIES, e.reason) }
        val inv = repo.convertChallans(listOf(c2, c1), today, 15, "27", "Against delivery challans: DC/1, DC/2")
        s = d.snap { it.invoices.size == 1 && it.challans.count { c -> c.convertedInvoiceId == inv } == 2 }
        val i = s.invoices.single()
        assertEquals(DocType.INVOICE, i.docType); assertTrue(i.number.startsWith("INV/"))
        assertEquals(1_475_000L, i.amount)                                                            // 5 × 2,500 + 18 %
        assertEquals("Against delivery challans: DC/1, DC/2", i.description)
        assertEquals(listOf(2_000L, 3_000L), s.invoiceItems[inv]!!.map { it.quantityMilli })           // challan order
        assertEquals(14_000L, s.onHand(s.catalogById[f.toner]!!))                                      // billing doesn't move stock again
        assertEquals(listOf(c1, c2), s.sourcesOf(inv).map { it.id })
        assertEquals(1_475_000L, s.invoiceBalances().single().outstanding)
        try { repo.convertChallans(listOf(c1), today); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.ALREADY_CONVERTED, e.reason) }

        // deleting the invoice re-opens both challans; stock is unchanged (still out on the challans)
        repo.deleteInvoice(inv)
        s = d.snap { it.invoices.isEmpty() }
        assertTrue(s.challans.filter { it.partyId == f.customer }.all { it.convertedInvoiceId == null })
        assertEquals(14_000L, s.onHand(s.catalogById[f.toner]!!))
        // a cancelled challan returns its stock and can't be billed
        repo.setInvoiceCancelled(other, true)
        s = d.snap { it.challans.first { c -> c.id == other }.cancelled }
        assertEquals(15_000L, s.onHand(s.catalogById[f.toner]!!))
        assertEquals(QuoteStatus.DECLINED, Quotations.status(s.challans.first { it.id == other }, today))
        try { repo.convertChallans(listOf(other), today); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.DECLINED, e.reason) }
    }

    @Test fun backupKeepsChallansAndPdf(): Unit = runBlocking {
        val f = fixture()
        val c1 = challan(f, "DC/1", today.minusDays(4), 2_000); val c2 = challan(f, "DC/2", today.minusDays(1), 1_000)
        val inv = repo.convertChallans(listOf(c1), today, 15, "27")
        d.snap { it.invoices.size == 1 && it.challans.size == 2 }
        val file = File(context().cacheDir, "p9.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb)); d.snap { it.challans.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        val s = d.snap { it.challans.size == 2 }
        assertEquals(inv, s.challans.first { it.id == c1 }.convertedInvoiceId)
        assertNull(s.challans.first { it.id == c2 }.convertedInvoiceId)
        assertEquals(17_000L, s.onHand(s.catalogById[f.toner]!!))

        val w = InvoicePdfWriter(MoneyFormatter(), DateFormatOption.DD_MM_YYYY, invoicePdfStrings(context()))
        val pages = w.layout(InvoiceBalance(s.challans.first { it.id == c2 }, 0, InvoiceStatus.OPEN, 0), s.invoiceItems[c2]!!,
            BusinessProfileDto(name = "Sharma & Associates", stateCode = "27", upiId = "sharma@oksbi"), s.partyById[f.customer])
        assertNull(pages.upiLink)                                                                      // no payment QR on a challan
        val bmp = Bitmap.createBitmap(InvoicePdfWriter.WIDTH * 2, InvoicePdfWriter.HEIGHT * 2, Bitmap.Config.ARGB_8888)
        Canvas(bmp).apply { scale(2f, 2f); w.drawPage(this, pages, 0) }
        File(File("build/screenshots").apply { mkdirs() }, "47_delivery_challan_pdf.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test fun overdueCollections(): Unit = runBlocking {
        val f = fixture()
        val now = LocalDate.of(2026, 5, 31)
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/1", f.customer, LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 16), 1_180_000))
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/2", f.customer, LocalDate.of(2026, 5, 2), LocalDate.of(2026, 5, 17), 590_000))
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/3", f.other, LocalDate.of(2026, 5, 10), LocalDate.of(2026, 5, 25), 2_000_000))
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/4", f.other, LocalDate.of(2026, 5, 20), LocalDate.of(2026, 6, 4), 100_000))   // not yet due
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.PURCHASE, "BILL/1", f.other, LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 16), 50_000))  // a bill isn't collected
        val s = d.snap { it.invoices.size == 5 }
        val list = overdueCustomers(s, setOf(f.cb), now)
        assertEquals(listOf("Metro Traders", "ABC Enterprises"), list.map { it.name })                 // largest first
        assertEquals(2_000_000L, list[0].total)
        val abc = list[1]
        assertEquals(listOf("INV/1", "INV/2"), abc.invoices.map { it.invoice.number })                 // most overdue first
        assertEquals(45, abc.oldestDays)
        assertEquals("""Dear ABC Enterprises,

This is a friendly reminder that the following invoices are overdue:
• INV/1 dated 01-04-2026 — ₹11,800.00 (due 16-04-2026, 45 days ago)
• INV/2 dated 02-05-2026 — ₹5,900.00 (due 17-05-2026, 14 days ago)
Total due: ₹17,700.00
Pay by UPI: sharma.assoc@oksbi

Please ignore this message if you have already paid.
Thank you,
Sharma & Associates""", customerReminderText(context(), abc, UiFormat(), BusinessProfileDto(name = "Sharma & Associates", upiId = "sharma.assoc@oksbi")))
    }
}
