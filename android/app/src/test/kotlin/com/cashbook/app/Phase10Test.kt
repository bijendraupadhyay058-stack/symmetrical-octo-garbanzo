package com.cashbook.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.InvoicePdfWriter
import com.cashbook.app.ui.invoices.invoicePdfStrings
import com.cashbook.core.CatalogItem
import com.cashbook.core.DateFormatOption
import com.cashbook.core.DocType
import com.cashbook.core.Frequency
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceSchedule
import com.cashbook.core.ItemKind
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.Transport
import com.cashbook.core.backup.BusinessProfileDto
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate
import java.util.Locale

/** Recurring sales invoices and transport details. */
@RunWith(AndroidJUnit4::class)
class Phase10Test {
    private val d = deps()
    private val repo = d.ledger

    private data class F(val cb: Long, val customer: Long, val toner: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveCatalogItem(CatalogItem(0, "Toner cartridge", ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 20_000, openingDate = LocalDate.of(2026, 1, 1))))
    }
    private val retainer = InvoiceItem(description = "Accounting retainer", hsn = "998221", quantityMilli = 1_000, unit = "Month", rate = 1_000_000, gstBp = 1800)
    private suspend fun template(f: F, start: LocalDate, end: LocalDate? = null) = repo.saveSchedule(
        InvoiceInfo(0, f.cb, InvoiceKind.SALE, "", f.customer, start, start, 1, "Retainer for {month}", "Period {period}", placeOfSupply = "27"),
        listOf(retainer), "27", InvoiceSchedule(0, 0, Frequency.MONTHLY, 1, start, end, dueDays = 7))

    @Test fun createsInvoicesOnScheduleOnce(): Unit = runBlocking {
        val f = fixture()
        val sid = template(f, LocalDate.of(2026, 1, 31))
        var s = d.snap { it.schedules.size == 1 && it.templates.size == 1 }
        val t = s.templates.single()
        assertEquals(DocType.TEMPLATE, t.docType); assertTrue(t.number.startsWith("REC/"))
        assertEquals(1_180_000L, t.amount)
        assertTrue(s.invoiceBalances().isEmpty())                                                    // a template owes nothing

        assertEquals(3, repo.postDueInvoiceSchedules(LocalDate.of(2026, 3, 31), DateFormatOption.DD_MM_YYYY, Locale.ENGLISH))
        s = d.snap { it.invoices.size == 3 }
        val invs = s.invoices.sortedBy { it.issueDate }
        assertEquals(listOf(LocalDate.of(2026, 1, 31), LocalDate.of(2026, 2, 28), LocalDate.of(2026, 3, 31)), invs.map { it.issueDate })   // no drift
        assertEquals(LocalDate.of(2026, 3, 7), invs[1].dueDate)
        assertEquals("Retainer for February 2026", invs[1].description)
        assertEquals("Period 28-02-2026 – 30-03-2026", invs[1].notes)
        assertEquals(listOf("INV/25-26/001", "INV/25-26/002", "INV/25-26/003"), invs.map { it.number })
        assertTrue(invs.all { it.scheduleId == sid && it.amount == 1_180_000L && s.invoiceItems[it.id]!!.single().description == "Accounting retainer" })
        assertEquals(0, repo.postDueInvoiceSchedules(LocalDate.of(2026, 3, 31)))                    // nothing twice
        assertEquals(LocalDate.of(2026, 4, 30), d.snap { true }.schedules.single().nextDate)

        // pausing skips the dates while paused; resuming continues from today
        repo.setScheduleActive(sid, false)
        assertEquals(0, repo.postDueInvoiceSchedules(LocalDate.of(2026, 6, 15)))
        repo.setScheduleActive(sid, true, today = LocalDate.of(2026, 6, 15))
        assertEquals(LocalDate.of(2026, 6, 30), d.snap { it.schedules.single().active }.schedules.single().nextDate)
        assertEquals(1, repo.postDueInvoiceSchedules(LocalDate.of(2026, 7, 1)))

        // deleting the schedule keeps its invoices as normal invoices
        repo.deleteSchedule(sid)
        s = d.snap { it.schedules.isEmpty() && it.templates.isEmpty() }
        assertEquals(4, s.invoices.size)
        assertTrue(s.invoices.all { it.scheduleId == null })
    }

    @Test fun endDateAndEditing(): Unit = runBlocking {
        val f = fixture()
        val sid = template(f, LocalDate.of(2026, 4, 1), end = LocalDate.of(2026, 5, 15))
        assertEquals(2, repo.postDueInvoiceSchedules(LocalDate.of(2026, 12, 31)))
        var s = d.snap { it.invoices.size == 2 }
        assertTrue(s.schedules.single().finished)
        // editing the template changes future invoices, not the ones already made
        val t = s.templates.single()
        repo.saveSchedule(t.copy(description = "New text"), listOf(retainer.copy(rate = 1_500_000)), "27",
            InvoiceSchedule(0, t.id, Frequency.MONTHLY, 1, LocalDate.of(2026, 4, 1), LocalDate.of(2026, 8, 15), dueDays = 7))
        s = d.snap { it.templates.single().description == "New text" }
        assertEquals(sid, s.schedules.single().id)
        assertEquals(2, s.schedules.single().nextIndex)                                              // dates already invoiced are kept
        assertEquals(3, repo.postDueInvoiceSchedules(LocalDate.of(2026, 12, 31)))                   // Jun, Jul, Aug
        s = d.snap { it.invoices.size == 5 }
        assertEquals(1_770_000L, s.invoices.maxBy { it.issueDate }.amount)
        assertEquals(2, s.invoices.count { it.amount == 1_180_000L })
    }

    @Test fun transportOnChallansInvoicesPdfAndBackup(): Unit = runBlocking {
        val f = fixture()
        val today = LocalDate.now()
        val c = repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "DC/1", f.customer, today, today, 1, placeOfSupply = "27", docType = DocType.CHALLAN,
            transport = Transport(" mh 12-ab 1234", "VRL Logistics", "LR-5521", "3810 0123 4567")),
            listOf(InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = 2_000, unit = "Nos", rate = 250_000, gstBp = 1800, itemId = f.toner)), "27")
        var s = d.snap { it.challans.isNotEmpty() }
        assertEquals(Transport("MH12AB1234", "VRL Logistics", "LR-5521", "381001234567"), s.challans.single().transport)
        val inv = repo.convertChallans(listOf(c), today, 15, "27")                                  // one challan → transport copied
        s = d.snap { it.invoices.isNotEmpty() }
        assertEquals("MH12AB1234", s.invoices.single { it.id == inv }.transport.vehicleNo)

        val w = InvoicePdfWriter(MoneyFormatter(), DateFormatOption.DD_MM_YYYY, invoicePdfStrings(context()))
        val pages = w.layout(s.invoiceBalances().single(), s.invoiceItems[inv]!!, BusinessProfileDto(name = "Sharma & Associates", stateCode = "27"), s.partyById[f.customer])
        val bmp = Bitmap.createBitmap(InvoicePdfWriter.WIDTH * 2, InvoicePdfWriter.HEIGHT * 2, Bitmap.Config.ARGB_8888)
        Canvas(bmp).apply { scale(2f, 2f); w.drawPage(this, pages, 0) }
        File(File("build/screenshots").apply { mkdirs() }, "53_invoice_pdf_transport.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }

        // a schedule, its template, its invoices and the transport all survive a backup
        val sid = template(f, today.minusMonths(1))
        repo.postDueInvoiceSchedules(today)
        s = d.snap { it.invoices.count { i -> i.scheduleId == sid } == 2 }
        val file = File(context().cacheDir, "p10.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb)); d.snap { it.invoices.isEmpty() && it.schedules.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        s = d.snap { it.schedules.size == 1 }
        assertEquals(2, s.schedules.single().nextIndex)
        assertEquals(2, s.invoices.count { it.scheduleId == sid })
        assertEquals("381001234567", s.challans.single().transport.ewayBillNo)
        assertEquals(0, repo.postDueInvoiceSchedules(today))                                        // nothing re-created after restore
        assertTrue(s.templates.single().transport.isEmpty)
        assertNull(s.templates.single().scheduleId)
    }
}
