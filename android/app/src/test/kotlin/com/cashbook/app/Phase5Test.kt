package com.cashbook.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.AttachmentStore
import com.cashbook.app.data.LedgerRepository.InvoiceException
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.InvoicePdfWriter
import com.cashbook.app.ui.invoices.invoicePdfStrings
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.DateFormatOption
import com.cashbook.core.DocType
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.Ledger
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.PaymentMode
import com.cashbook.core.TxnType
import com.cashbook.core.backup.BusinessProfileDto
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.time.LocalDate

/** Credit/debit notes, refunds and invoice branding. */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class Phase5Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()
    private val items = listOf(
        InvoiceItem(description = "Laser printer", hsn = "8443", quantityMilli = 2000, unit = "Nos", rate = 1_500_000, gstBp = 1800),
        InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = 5000, unit = "Nos", rate = 250_000, gstBp = 1800),
    )

    private data class F(val cb: Long, val party: Long, val bank: Long, val inc: Long, val exp: Long)
    private fun fixture() = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        val s = d.snap { it.txns.size == 4 }
        F(cb, repo.saveParty(PartyEntity(name = "ABC Enterprises Pvt Ltd", type = "CUSTOMER", gstin = "27AAPFU0939F1ZV", createdAt = 0, updatedAt = 0, stateCode = "27")),
            s.accounts.first { it.type == AccountType.BANK }.id, s.categories.first { it.kind == CategoryKind.INCOME && it.name == "Sales" }.id,
            s.categories.first { it.kind == CategoryKind.EXPENSE && it.name == "Other expenses" }.id)
    }
    private suspend fun invoice(f: F) = repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, "INV/26-27/001", f.party, today, today.plusDays(30), 1,
        placeOfSupply = "27"), items, "27")                                                    // 2 × 15,000 + 5 × 2,500 = 42,500 + 18 % = 50,150
    private suspend fun note(f: F, ref: Long, type: DocType, lines: List<InvoiceItem>, number: String = "CN/26-27/001") =
        repo.saveInvoice(InvoiceInfo(0, f.cb, InvoiceKind.SALE, number, 0, today, today, 1, "Returned 1 toner", docType = type, refInvoiceId = ref), lines, "27")

    @Test fun creditNoteReducesOutstandingAndInheritsInvoiceDetails() = runBlocking {
        val f = fixture()
        val id = invoice(f)
        val cn = note(f, id, DocType.CREDIT_NOTE, listOf(items[1].copy(quantityMilli = 1000)))  // 2,500 + 18 % = 2,950
        val s = d.snap { it.invoices.size == 2 }
        val n = s.invoices.first { it.id == cn }
        assertEquals(f.party, n.partyId); assertEquals("27", n.placeOfSupply); assertEquals(295_000L, n.amount)
        val b = s.invoiceBalances(today).single()                                             // only the invoice is listed
        assertEquals(5_015_000L, b.invoice.amount)
        assertEquals(295_000L, b.credited)
        assertEquals(4_720_000L, b.outstanding)
        assertEquals(InvoiceStatus.PARTIAL, b.status)
        val dn = note(f, id, DocType.DEBIT_NOTE, listOf(InvoiceItem(description = "Freight", quantityMilli = 1000, rate = 50_000, gstBp = 1800)), "DN/26-27/001")
        assertEquals(4_779_000L, d.snap { it.invoices.size == 3 }.invoiceBalances(today).single().outstanding)
        assertEquals("CN/26-27/002", repo.nextInvoiceNumber(f.cb, InvoiceKind.SALE, today, DocType.CREDIT_NOTE))
        assertTrue(dn > 0)
    }

    @Test fun limitsAndProtection() = runBlocking {
        val f = fixture()
        val id = invoice(f)
        try { note(f, id, DocType.CREDIT_NOTE, items + items); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.NOTE_TOO_LARGE, e.reason) }
        val cn = note(f, id, DocType.CREDIT_NOTE, listOf(items[1]))
        try { repo.deleteInvoice(id); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.HAS_NOTES, e.reason) }
        try { repo.setInvoiceCancelled(id, true); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.HAS_NOTES, e.reason) }
        repo.deleteInvoice(cn)                                                                // notes themselves can be deleted
        assertEquals(5_015_000L, d.snap { it.invoices.size == 1 }.invoiceBalances(today).single().outstanding)
        // a note must point at a real invoice, not at another note
        val cn2 = note(f, id, DocType.CREDIT_NOTE, listOf(items[1]), "CN/2")
        try { note(f, cn2, DocType.CREDIT_NOTE, listOf(items[1]), "CN/3"); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.NOT_FOUND, e.reason) }
    }

    @Test fun creditAfterFullPaymentLeadsToRefund() = runBlocking {
        val f = fixture()
        val id = invoice(f)
        repo.recordPayment(id, f.bank, f.inc, 5_015_000, today, PaymentMode.UPI, "", "Paid in full")
        note(f, id, DocType.CREDIT_NOTE, listOf(items[1].copy(quantityMilli = 2000)))         // 5,900 credit
        var s = d.snap { it.invoices.size == 2 }
        var b = s.invoiceBalances(today).single()
        assertEquals(InvoiceStatus.REFUND_DUE, b.status)
        assertEquals(590_000L, b.refundDue)
        try { repo.recordPayment(id, f.bank, f.inc, 1, today, PaymentMode.UPI, "", ""); fail() } catch (e: InvoiceException) { }
        try { repo.recordRefund(id, f.bank, f.exp, 590_001, today, PaymentMode.UPI, "", ""); fail() } catch (e: InvoiceException) { }
        val refund = repo.recordRefund(id, f.bank, f.exp, 590_000, today, PaymentMode.UPI, "", "Refund")
        s = d.snap { it.allocations.size == 2 }
        b = s.invoiceBalances(today).single()
        assertEquals(InvoiceStatus.PAID, b.status)
        assertEquals(TxnType.EXPENSE, s.txns.first { it.id == refund }.type)
        // bank: 59,000 + 50,150 received − 5,900 refunded
        assertEquals(10_325_000L, Ledger.currentBalance(s.accountById[f.bank]!!, s.txns))
        // invoice amount can't be reduced below what remains paid
        try { repo.saveInvoice(s.invoices.first { it.id == id }, items.take(1), "27"); fail() } catch (e: InvoiceException) { assertEquals(InvoiceException.Reason.BELOW_PAID, e.reason) }
    }

    @Test fun backupCarriesNotesAndBrandingImages() = runBlocking {
        val f = fixture()
        val id = invoice(f)
        note(f, id, DocType.CREDIT_NOTE, listOf(items[1]))
        importBrand(AttachmentStore.Brand.LOGO, logoBitmap())
        d.snap { it.invoices.size == 2 }
        val file = File(context().cacheDir, "p5.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), includeAttachments = false).getOrThrow()  // branding goes anyway
        repo.deleteCashbooks(listOf(f.cb)); d.attachments.removeBrand(AttachmentStore.Brand.LOGO)
        d.snap { it.invoices.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        val s = d.snap { it.invoices.size == 2 }
        assertEquals(DocType.CREDIT_NOTE, s.invoices.first { it.refInvoiceId == id }.docType)
        assertTrue(d.attachments.brandFile(AttachmentStore.Brand.LOGO).exists())
    }

    private fun logoBitmap(): Bitmap = Bitmap.createBitmap(600, 200, Bitmap.Config.ARGB_8888).apply {
        val c = Canvas(this); val p = Paint(Paint.ANTI_ALIAS_FLAG)
        p.color = Color.rgb(0x1A, 0x2B, 0x5C); c.drawRoundRect(0f, 0f, 200f, 200f, 40f, 40f, p)
        p.color = Color.WHITE; p.textSize = 120f; p.isFakeBoldText = true; c.drawText("SA", 22f, 145f, p)
        p.color = Color.rgb(0x1A, 0x2B, 0x5C); p.textSize = 70f; c.drawText("Sharma", 230f, 95f, p); p.textSize = 48f; c.drawText("& Associates", 230f, 160f, p)
    }
    private fun signatureBitmap(): Bitmap = Bitmap.createBitmap(500, 150, Bitmap.Config.ARGB_8888).apply {
        val c = Canvas(this); val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(0x10, 0x30, 0x80); strokeWidth = 7f; style = Paint.Style.STROKE }
        val path = android.graphics.Path().apply { moveTo(20f, 110f); cubicTo(80f, 10f, 120f, 140f, 180f, 60f); cubicTo(220f, 10f, 260f, 130f, 320f, 70f); lineTo(480f, 80f) }
        c.drawPath(path, p)
    }
    private fun importBrand(b: AttachmentStore.Brand, bmp: Bitmap) {
        val f = File(context().cacheDir, "${b.name}.png"); f.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        d.attachments.importBrand(b, Uri.fromFile(f))
    }

    @Test fun creditNotePdfWithLogoAndSignature() = runBlocking {
        val f = fixture()
        importBrand(AttachmentStore.Brand.LOGO, logoBitmap()); importBrand(AttachmentStore.Brand.SIGNATURE, signatureBitmap())
        val seller = BusinessProfileDto(name = "Sharma & Associates", address = "201, Business Park, Andheri East, Mumbai 400069", gstin = "27AAPFU0939F1ZV",
            stateCode = "27", signatory = "R. Sharma", terms = "Credit adjusted against your next invoice unless refunded.")
        val id = invoice(f)
        val cn = note(f, id, DocType.CREDIT_NOTE, listOf(items[1].copy(quantityMilli = 1000)))
        val s = d.snap { it.invoices.size == 2 }
        val n = s.invoices.first { it.id == cn }; val inv = s.invoices.first { it.id == id }
        val w = InvoicePdfWriter(MoneyFormatter(), DateFormatOption.DD_MM_YYYY, invoicePdfStrings(context()))
        val branding = InvoicePdfWriter.Branding(d.attachments.brandBitmap(AttachmentStore.Brand.LOGO), d.attachments.brandBitmap(AttachmentStore.Brand.SIGNATURE))
        val pages = w.layout(InvoiceBalance(n, 0, InvoiceStatus.OPEN, 0), s.invoiceItems[cn]!!, seller, s.partyById[f.party], branding,
            InvoicePdfWriter.Reference(inv.number, inv.issueDate))
        assertEquals(1, pages.pages.size)
        val bmp = Bitmap.createBitmap(InvoicePdfWriter.WIDTH * 2, InvoicePdfWriter.HEIGHT * 2, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp); c.scale(2f, 2f); w.drawPage(c, pages, 0)
        File(File("build/screenshots").apply { mkdirs() }, "27_credit_note_pdf.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        assertTrue(d.attachments.brandBitmap(AttachmentStore.Brand.LOGO)!!.width <= 800)
    }
}
