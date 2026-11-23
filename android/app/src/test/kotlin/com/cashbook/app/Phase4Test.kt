package com.cashbook.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.LedgerRepository.InvoiceException
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.InvoicePdfWriter
import com.cashbook.app.ui.invoices.invoicePdfStrings
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.DateFormatOption
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceKind
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.PaymentMode
import com.cashbook.core.backup.BusinessProfileDto
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.time.LocalDate

/** Itemised GST invoices, business profile and the tax-invoice PDF. */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class Phase4Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.of(2026, 11, 23)
    private val seller = BusinessProfileDto(name = "Sharma & Associates", address = "201, Business Park, Andheri East\nMumbai 400069", gstin = "27AAPFU0939F1ZV",
        stateCode = "27", phone = "+91 98200 00000", email = "accounts@example.com", bankName = "State Bank of India", accountName = "Sharma & Associates",
        accountNumber = "000012345678", ifsc = "SBIN0000001", upiId = "sharma@sbi", terms = "Payment within 30 days. Interest @18% p.a. on overdue amounts.",
        signatory = "R. Sharma")
    private val items = listOf(
        InvoiceItem(description = "Statutory audit for FY 2025-26", hsn = "998221", quantityMilli = 1000, unit = "Nos", rate = 5_000_000, gstBp = 1800),
        InvoiceItem(description = "GST return filing (monthly)", hsn = "998231", quantityMilli = 12_000, unit = "Month", rate = 250_000, discountBp = 1000, gstBp = 1800),
        InvoiceItem(description = "Printed annual report copies", hsn = "4901", quantityMilli = 2500, unit = "Kg", rate = 12_345, gstBp = 500),
    )

    private data class F(val cb: Long, val party: Long, val otherState: Long, val bank: Long, val cat: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        val s = d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises Pvt Ltd", type = "CLIENT", address = "12 MG Road, Pune 411001", gstin = "27AAPFU0939F1ZV",
            createdAt = 0, updatedAt = 0, stateCode = "27")),
            repo.saveParty(PartyEntity(name = "Bengaluru Tech LLP", type = "CLIENT", gstin = "29AAGCB7383J1Z4", createdAt = 0, updatedAt = 0, stateCode = "29")),
            s.accounts.first { it.type == AccountType.BANK }.id, s.categories.first { it.kind == CategoryKind.INCOME }.id)
    }
    private fun inv(f: F, party: Long, pos: String, number: String) = InvoiceInfo(0, f.cb, InvoiceKind.SALE, number, party, today, today.plusDays(30), 1,
        "Professional services", placeOfSupply = pos)

    @Test fun itemsDecideTheAmountForBothSupplyTypes() = runBlocking {
        val f = fixture()
        val intra = repo.saveInvoice(inv(f, f.party, "27", "INV/26-27/001"), items, "27")
        val inter = repo.saveInvoice(inv(f, f.otherState, "29", "INV/26-27/002"), items, "27")
        val s = d.snap { it.invoiceItems.size == 2 }
        // 50,000 + (12 × 2,500 − 10 %) 27,000 + (2.5 × 123.45) 308.63 = taxable 77,308.63
        // GST: 18 % of 77,000 = 13,860; 5 % of 308.63 = 15.43 IGST, or 7.72 + 7.72 CGST/SGST → rounded to the rupee
        assertEquals(9_118_400L, s.invoices.first { it.id == intra }.amount)   // 91,184.07 → 91,184.00
        assertEquals(9_118_400L, s.invoices.first { it.id == inter }.amount)   // 91,184.06 → 91,184.00
        assertEquals(3, s.invoiceItems[intra]!!.size)
        assertEquals("GST return filing (monthly)", s.invoiceItems[intra]!![1].description)
    }

    @Test fun editingReplacesItemsAndSimpleModeClearsThem() = runBlocking {
        val f = fixture()
        val id = repo.saveInvoice(inv(f, f.party, "27", "INV/1"), items, "27")
        val saved = d.snap { it.invoiceItems[id]?.size == 3 }.invoices.first { it.id == id }
        repo.saveInvoice(saved, items.take(1), "27")
        assertEquals(5_900_000L, d.snap { it.invoiceItems[id]?.size == 1 }.invoices.first { it.id == id }.amount)
        repo.saveInvoice(saved.copy(amount = 1_000_000), emptyList(), "27")
        val s = d.snap { it.invoiceItems[id] == null }
        assertEquals(1_000_000L, s.invoices.first { it.id == id }.amount)
    }

    @Test fun itemsCannotGoBelowPaidOrZero() = runBlocking {
        val f = fixture()
        val id = repo.saveInvoice(inv(f, f.party, "27", "INV/1"), items, "27")
        repo.recordPayment(id, f.bank, f.cat, 6_000_000, today, PaymentMode.UPI, "", "")
        val saved = d.snap { it.allocations.size == 1 }.invoices.first { it.id == id }
        try { repo.saveInvoice(saved, items.take(1), "27"); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.BELOW_PAID, e.reason) }
        try { repo.saveInvoice(inv(f, f.party, "27", "INV/2"), listOf(items[0].copy(rate = 0)), "27"); fail() }
        catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.INVALID_AMOUNT, e.reason) }
    }

    @Test fun backupIncludesItemsPartyStateAndBusinessProfile() = runBlocking {
        val f = fixture()
        d.settings.updateBusinessProfile(seller)
        val id = repo.saveInvoice(inv(f, f.otherState, "29", "INV/1"), items, "27")
        d.snap { it.invoiceItems.isNotEmpty() }
        val file = File(context().cacheDir, "p4.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb))
        d.settings.updateBusinessProfile(BusinessProfileDto())
        d.snap { it.invoices.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        val s = d.snap { it.invoiceItems[id]?.size == 3 }
        assertEquals("29", s.partyById[f.otherState]!!.stateCode)
        assertEquals("29", s.invoices.single().placeOfSupply)
        assertEquals(seller, d.settings.businessProfile.first())
    }

    private fun renderPages(name: String, b: com.cashbook.core.InvoiceBalance, lines: List<InvoiceItem>, buyer: com.cashbook.core.PartyInfo?): Int {
        val w = InvoicePdfWriter(MoneyFormatter(), DateFormatOption.DD_MM_YYYY, invoicePdfStrings(context()))
        val pages = w.layout(b, lines, seller, buyer)
        val dir = File("build/screenshots").apply { mkdirs() }
        pages.pages.indices.forEach { i ->
            val scale = 2f
            val bmp = Bitmap.createBitmap((InvoicePdfWriter.WIDTH * scale).toInt(), (InvoicePdfWriter.HEIGHT * scale).toInt(), Bitmap.Config.ARGB_8888)
            val c = Canvas(bmp); c.scale(scale, scale)
            w.drawPage(c, pages, i)
            File(dir, "${name}_p${i + 1}.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
        // Android's native PdfDocument isn't available on the JVM test runner; the same layout and drawing code
        // is rendered to images above, and w.write() (PdfDocument wrapper) is checked on a device.
        return pages.pages.size
    }

    @Test fun taxInvoicePdf() = runBlocking {
        val f = fixture()
        d.settings.updateBusinessProfile(seller)
        val id = repo.saveInvoice(inv(f, f.party, "27", "INV/26-27/001"), items, "27")
        repo.recordPayment(id, f.bank, f.cat, 2_000_000, today, PaymentMode.UPI, "", "")
        val s = d.snap { it.allocations.isNotEmpty() }
        val b = s.invoiceBalances(today).single()
        assertEquals(1, renderPages("22_invoice_pdf", b, s.invoiceItems[id]!!, s.partyById[f.party]))
        // inter-state and a long invoice that needs a second page with repeated headings
        val many = (1..45).map { items[it % 3].copy(description = "Line $it — " + items[it % 3].description) }
        val id2 = repo.saveInvoice(inv(f, f.otherState, "29", "INV/26-27/002"), many, "27")
        val s2 = d.snap { it.invoiceItems[id2]?.size == 45 }
        assertTrue(renderPages("23_invoice_pdf_long", s2.invoiceBalances(today).first { it.invoice.id == id2 }, many, s2.partyById[f.otherState]) >= 2)
    }
}
