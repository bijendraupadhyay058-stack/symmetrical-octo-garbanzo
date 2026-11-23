package com.cashbook.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.LedgerRepository.InvoiceException
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.InvoicePdfWriter
import com.cashbook.app.ui.invoices.invoicePdfStrings
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
import com.cashbook.core.PaymentMode
import com.cashbook.core.QuoteStatus
import com.cashbook.core.Quotations
import com.cashbook.core.Upi
import com.cashbook.core.backup.BusinessProfileDto
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Quotations (estimates) converted to invoices, and the UPI payment QR on invoices. */
@RunWith(AndroidJUnit4::class)
class Phase7Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()
    private val seller = BusinessProfileDto(name = "Sharma & Associates", address = "201, Business Park, Andheri East, Mumbai 400069", gstin = "27AAPFU0939F1ZV",
        stateCode = "27", bankName = "State Bank of India, Andheri East branch", accountName = "Sharma & Associates", accountNumber = "30012345678",
        ifsc = "SBIN0001234", upiId = "sharma.assoc@oksbi", signatory = "R. Sharma", terms = "Payment within 15 days.")

    private data class F(val cb: Long, val customer: Long, val toner: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveCatalogItem(CatalogItem(0, "Toner cartridge", ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 10_000, openingDate = today.minusDays(30), reorderLevelMilli = 2_000)))
    }
    private fun lines(f: F) = listOf(InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = 2_000, unit = "Nos", rate = 250_000, gstBp = 1800, itemId = f.toner),
        InvoiceItem(description = "Installation", hsn = "998719", quantityMilli = 1_000, unit = "Job", rate = 50_000, gstBp = 1800))
    private suspend fun quote(f: F, number: String = "QT/1", kind: InvoiceKind = InvoiceKind.SALE) = repo.saveInvoice(
        InvoiceInfo(0, f.cb, kind, number, f.customer, today, today.plusDays(15), 1, "Toner supply", placeOfSupply = "27", docType = DocType.QUOTATION), lines(f), "27")

    @Test fun quotationConvertsToInvoice(): Unit = runBlocking {
        val f = fixture()
        assertEquals("QT/" , repo.nextInvoiceNumber(f.cb, InvoiceKind.SALE, today, DocType.QUOTATION).take(3))
        val q = quote(f, kind = InvoiceKind.PURCHASE)                                             // always a sale
        var s = d.snap { it.quotations.size == 1 }
        val qi = s.quotations.single()
        assertEquals(InvoiceKind.SALE, qi.kind)
        assertEquals(649_000L, qi.amount)                                                     // (5,000 + 500) + 18 % GST
        // an offer only: no receivable, no stock movement, not in the invoice list or reports
        assertTrue(s.invoices.isEmpty() && s.invoiceBalances().isEmpty())
        assertEquals(10_000L, s.onHand(s.catalogById[f.toner]!!))
        assertEquals(qi, s.doc(q))
        // a quotation can't take payments or notes
        try { repo.recordPayment(q, s.accounts.first().id, s.categories.first().id, 1_000, today, PaymentMode.CASH, "", ""); fail() }
        catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.NOT_FOUND, e.reason) }
        try { repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "CN/1", f.customer, today, today, 1_000, docType = DocType.CREDIT_NOTE, refInvoiceId = q)); fail() }
        catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.NOT_FOUND, e.reason) }

        val inv = repo.convertQuotation(q, today, 15, "27")
        s = d.snap { it.invoices.size == 1 && it.quotations.single().convertedInvoiceId == inv }
        val i = s.invoices.single()
        assertEquals(DocType.INVOICE, i.docType); assertEquals(InvoiceKind.SALE, i.kind)
        assertTrue(i.number.startsWith("INV/"))
        assertEquals(today.plusDays(15), i.dueDate)
        assertEquals(649_000L, i.amount); assertEquals("Toner supply", i.description); assertEquals(f.customer, i.partyId)
        assertEquals(listOf(f.toner, null), s.invoiceItems[inv]!!.map { it.itemId })
        assertEquals(649_000L, s.invoiceBalances().single().outstanding)
        assertEquals(8_000L, s.onHand(s.catalogById[f.toner]!!))                                 // stock moves with the invoice
        assertEquals(QuoteStatus.CONVERTED, Quotations.status(s.quotations.single(), today))
        assertEquals(q, Quotations.sourceOf(inv, s.quotations)?.id)
        try { repo.convertQuotation(q, today); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.ALREADY_CONVERTED, e.reason) }

        // deleting the invoice re-opens the quotation; it can be converted again
        repo.deleteInvoice(inv)
        s = d.snap { it.invoices.isEmpty() }
        assertNull(s.quotations.single().convertedInvoiceId)
        assertEquals(QuoteStatus.OPEN, Quotations.status(s.quotations.single(), today))
        repo.convertQuotation(q, today)
        d.snap { it.invoices.size == 1 }
    }

    @Test fun declinedAndExpiredQuotations(): Unit = runBlocking {
        val f = fixture()
        val q = quote(f)
        repo.setInvoiceCancelled(q, true)
        var s = d.snap { it.quotations.single().cancelled }
        assertEquals(QuoteStatus.DECLINED, Quotations.status(s.quotations.single(), today))
        try { repo.convertQuotation(q, today); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.DECLINED, e.reason) }
        repo.setInvoiceCancelled(q, false)
        s = d.snap { !it.quotations.single().cancelled }
        assertEquals(QuoteStatus.EXPIRED, Quotations.status(s.quotations.single(), today.plusDays(16)))
        // its own number series: "QT/1" can coexist with an invoice numbered "QT/1"
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "QT/1", f.customer, today, today, 1_000))
        try { quote(f, "qt/1"); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.DUPLICATE_NUMBER, e.reason) }
        repo.deleteInvoice(q)
        d.snap { it.quotations.isEmpty() && it.invoices.size == 1 }
    }

    @Test fun backupKeepsQuotationsAndLinks(): Unit = runBlocking {
        val f = fixture()
        val q = quote(f); val inv = repo.convertQuotation(q, today, 15, "27"); quote(f, "QT/2")
        d.snap { it.quotations.size == 2 && it.invoices.size == 1 }
        val file = File(context().cacheDir, "p7.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb))
        d.snap { it.quotations.isEmpty() && it.invoices.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        val s = d.snap { it.quotations.size == 2 }
        assertEquals(inv, s.quotations.first { it.id == q }.convertedInvoiceId)
        assertEquals(2, s.invoiceItems[q]!!.size)
        assertEquals(1, s.invoices.size)
        assertEquals(8_000L, s.onHand(s.catalogById[f.toner]!!))                                 // the open QT/2 doesn't reserve stock
    }

    @Test fun invoicePdfCarriesScannableUpiQr(): Unit = runBlocking {
        val f = fixture()
        val q = quote(f)
        val inv = repo.convertQuotation(q, today, 15, "27")
        val s = d.snap { it.invoices.size == 1 }
        val b = s.invoiceBalances().single()
        val w = InvoicePdfWriter(MoneyFormatter(), DateFormatOption.DD_MM_YYYY, invoicePdfStrings(context()))
        val pages = w.layout(b, s.invoiceItems[inv]!!, seller, s.partyById[f.customer])
        val expected = Upi.payUri("sharma.assoc@oksbi", "Sharma & Associates", 649_000, b.invoice.number)
        assertEquals(expected, pages.upiLink)
        assertEquals(1, pages.pages.size)
        val bmp = Bitmap.createBitmap(InvoicePdfWriter.WIDTH * 2, InvoicePdfWriter.HEIGHT * 2, Bitmap.Config.ARGB_8888)
        Canvas(bmp).apply { scale(2f, 2f); w.drawPage(this, pages, 0) }
        File(File("build/screenshots").apply { mkdirs() }, "35_invoice_pdf_upi_qr.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        // read the QR back from the rendered page, as a phone camera would
        val px = IntArray(bmp.width * bmp.height).also { bmp.getPixels(it, 0, bmp.width, 0, 0, bmp.width, bmp.height) }
        val decoded = QRCodeReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(bmp.width, bmp.height, px))), mapOf(DecodeHintType.TRY_HARDER to true))
        assertEquals(expected, decoded.text)

        // no QR once paid, on quotations, or without a valid UPI ID
        repo.recordPayment(inv, s.accounts.first { it.cashbookId == f.cb }.id, s.categories.first { it.kind == com.cashbook.core.CategoryKind.INCOME }.id,
            649_000, today, PaymentMode.UPI, "", "")
        val paid = d.snap { it.invoiceBalances().single().outstanding == 0L }
        assertNull(w.layout(paid.invoiceBalances().single(), paid.invoiceItems[inv]!!, seller, null).upiLink)
        val qi = paid.quotations.single()
        val qp = w.layout(InvoiceBalance(qi, 0, InvoiceStatus.OPEN, 0), paid.invoiceItems[q]!!, seller, paid.partyById[f.customer])
        assertNull(qp.upiLink)
        val qb = Bitmap.createBitmap(InvoicePdfWriter.WIDTH * 2, InvoicePdfWriter.HEIGHT * 2, Bitmap.Config.ARGB_8888)
        Canvas(qb).apply { scale(2f, 2f); w.drawPage(this, qp, 0) }
        File("build/screenshots", "36_quotation_pdf.png").outputStream().use { qb.compress(Bitmap.CompressFormat.PNG, 100, it) }
        val unpaid = InvoiceBalance(b.invoice, 0, InvoiceStatus.OPEN, 0)
        assertNull(w.layout(unpaid, emptyList(), seller.copy(upiId = "not a upi id"), null).upiLink)
    }
}
