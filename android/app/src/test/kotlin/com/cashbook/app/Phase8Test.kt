package com.cashbook.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.InvoicePdfWriter
import com.cashbook.app.ui.components.UiFormat
import com.cashbook.app.ui.invoices.invoicePdfStrings
import com.cashbook.app.ui.invoices.reminderText
import com.cashbook.app.ui.reports.reportLabels
import com.cashbook.core.CatalogItem
import com.cashbook.core.CategoryKind
import com.cashbook.core.Cell
import com.cashbook.core.DateFormatOption
import com.cashbook.core.DateRange
import com.cashbook.core.DocType
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.ItemKind
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.PaymentMode
import com.cashbook.core.QuoteStatus
import com.cashbook.core.Quotations
import com.cashbook.core.ReportEngine
import com.cashbook.core.ReportInput
import com.cashbook.core.ReportType
import com.cashbook.core.TxnFilter
import com.cashbook.core.backup.BusinessProfileDto
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Purchase orders converted to bills, the statement of account, and payment reminders. */
@RunWith(AndroidJUnit4::class)
class Phase8Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    private data class F(val cb: Long, val customer: Long, val supplier: Long, val toner: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", mobile = "98765 43210", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveParty(PartyEntity(name = "Office Mart", type = "SUPPLIER", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveCatalogItem(CatalogItem(0, "Toner cartridge", ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 2_000, openingDate = today.minusDays(30), reorderLevelMilli = 3_000)))
    }
    private fun toner(f: F, qty: Long, rate: Long) = InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = qty, unit = "Nos", rate = rate, gstBp = 1800, itemId = f.toner)

    @Test fun purchaseOrderConvertsToBill(): Unit = runBlocking {
        val f = fixture()
        val number = repo.nextInvoiceNumber(f.cb, InvoiceKind.PURCHASE, today, DocType.QUOTATION)
        assertTrue(number, number.startsWith("PO/"))
        val po = repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.PURCHASE, number, f.supplier, today, today.plusDays(7), 1, placeOfSupply = "27",
            docType = DocType.QUOTATION), listOf(toner(f, 10_000, 180_000)), "27")
        var s = d.snap { it.quotations.size == 1 }
        assertEquals(InvoiceKind.PURCHASE, s.quotations.single().kind)
        assertEquals(2_124_000L, s.quotations.single().amount)                                      // 10 × 1,800 + 18 %
        assertTrue(s.invoiceBalances().isEmpty())
        assertEquals(2_000L, s.onHand(s.catalogById[f.toner]!!))                                      // nothing received yet

        val bill = repo.convertQuotation(po, today, 15, "27")
        s = d.snap { it.invoices.isNotEmpty() }
        val b = s.invoiceBalances().single()
        assertEquals(bill, b.invoice.id)
        assertEquals(InvoiceKind.PURCHASE, b.invoice.kind)
        assertTrue(b.invoice.number.startsWith("BILL/"))
        assertEquals(2_124_000L, b.outstanding)
        assertEquals(12_000L, s.onHand(s.catalogById[f.toner]!!))                                     // stock comes in with the bill
        assertEquals(QuoteStatus.CONVERTED, Quotations.status(s.quotations.single(), today))

        // the PO prints as a PURCHASE ORDER addressed to the supplier, without a UPI QR
        val w = InvoicePdfWriter(MoneyFormatter(), DateFormatOption.DD_MM_YYYY, invoicePdfStrings(context()))
        val pages = w.layout(InvoiceBalance(s.quotations.single(), 0, InvoiceStatus.OPEN, 0), s.invoiceItems[po]!!,
            BusinessProfileDto(name = "Sharma & Associates", stateCode = "27", upiId = "sharma@oksbi"), s.partyById[f.supplier])
        assertEquals(null, pages.upiLink)
        val bmp = Bitmap.createBitmap(InvoicePdfWriter.WIDTH * 2, InvoicePdfWriter.HEIGHT * 2, Bitmap.Config.ARGB_8888)
        Canvas(bmp).apply { scale(2f, 2f); w.drawPage(this, pages, 0) }
        File(File("build/screenshots").apply { mkdirs() }, "41_purchase_order_pdf.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }

        // purchase orders survive a backup round trip with their link
        val file = File(context().cacheDir, "p8.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb)); d.snap { it.quotations.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        assertEquals(bill, d.snap { it.quotations.size == 1 }.quotations.single().convertedInvoiceId)
    }

    @Test fun statementAgreesWithOutstanding(): Unit = runBlocking {
        val f = fixture()
        val inv1 = repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/1", f.customer, today.minusDays(40), today.minusDays(25), 1_000_000))
        val inv2 = repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/2", f.customer, today.minusDays(5), today.plusDays(10), 500_000))
        var s = d.snap { it.invoices.size == 2 }
        val acc = s.accounts.first { it.cashbookId == f.cb }.id
        val cat = s.categories.first { it.kind == CategoryKind.INCOME }.id
        repo.recordPayment(inv1, acc, cat, 400_000, today.minusDays(30), PaymentMode.CASH, "", "Part payment")
        repo.recordPayment(inv1, acc, cat, 100_000, today.minusDays(2), PaymentMode.UPI, "UTR9", "Part payment")
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "CN/1", f.customer, today.minusDays(1), today.minusDays(1), 50_000,
            docType = DocType.CREDIT_NOTE, refInvoiceId = inv2))
        s = d.snap { it.allocations.size == 2 && it.invoices.size == 3 }
        val r = ReportEngine(ReportInput(ReportType.PARTY_STATEMENT, "Office", accounts = s.accounts, categories = s.categoryById, parties = s.partyById,
            txns = s.txns, range = DateRange(today.minusDays(10), today), generatedAt = "now", labels = reportLabels(context()),
            invoices = s.invoices, allocations = s.allocations, filter = TxnFilter(partyIds = setOf(f.customer)))).build()
        val rows = r.tables[0].rows
        assertEquals(Cell.Amount(600_000), rows[1].cells[4])                                           // opening: 10,000 − 4,000
        assertEquals(Cell.Amount(950_000), rows.last().cells[4])                                       // + 5,000 − 500 − 1,000
        assertEquals(s.invoiceBalances().filter { it.invoice.partyId == f.customer }.sumOf { it.outstanding }, 950_000L)
        assertEquals(listOf("Invoice INV/2", "Received – UPI (INV/1) · UTR9", "Credit note CN/1"),
            rows.drop(2).dropLast(1).map { (it.cells[1] as Cell.Text).value })
    }

    @Test fun reminderMessage(): Unit = runBlocking {
        val f = fixture()
        val inv = repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/26-27/007", f.customer, LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 16), 1_180_000))
        val s = d.snap { it.invoices.isNotEmpty() }
        val b = s.invoiceBalances().single { it.invoice.id == inv }
        val seller = BusinessProfileDto(name = "Sharma & Associates", upiId = "sharma.assoc@oksbi")
        val overdue = reminderText(context(), b, s, UiFormat(), seller, today = LocalDate.of(2026, 4, 26))
        assertEquals("""Dear ABC Enterprises,

This is a friendly reminder that invoice INV/26-27/007 dated 01-04-2026 for ₹11,800.00 was due on 16-04-2026 (10 days ago).
Balance due: ₹11,800.00
Pay by UPI: sharma.assoc@oksbi

Please ignore this message if you have already paid.
Thank you,
Sharma & Associates""", overdue)
        val due = reminderText(context(), b, s, UiFormat(), BusinessProfileDto(), today = LocalDate.of(2026, 4, 10))
        assertTrue(due.contains("is due on 16-04-2026."))
        assertFalse(due.contains("UPI"))
        assertEquals("919876543210", com.cashbook.core.Reminders.whatsappNumber(s.partyById[f.customer]!!.mobile))
    }
}
