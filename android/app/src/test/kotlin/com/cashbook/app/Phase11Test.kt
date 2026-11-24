package com.cashbook.app

import android.content.Intent
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.components.UiFormat
import com.cashbook.app.ui.invoices.pdfCaption
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceKind
import com.cashbook.core.Reminders
import com.cashbook.core.backup.BusinessProfileDto
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import java.time.LocalDate

/** Sending document PDFs into a WhatsApp chat, and the snapshot's cached calculations. */
@RunWith(AndroidJUnit4::class)
class Phase11Test {
    private val d = deps()
    private val repo = d.ledger

    @Test fun pdfGoesStraightToTheCustomersChat(): Unit = runBlocking {
        val uri = Exporter.writeShareable(context(), "INV_test.pdf") { it.write("%PDF-1.4".toByteArray()) }
        val number = Reminders.whatsappNumber("98765 43210")!!
        assertTrue(Exporter.sendToWhatsApp(context(), uri, Exporter.MIME_PDF, number, "Invoice INV/1"))
        val sent: Intent = shadowOf(app()).nextStartedActivity
        assertEquals(Intent.ACTION_SEND, sent.action)
        assertEquals("com.whatsapp", sent.`package`)
        assertEquals("919876543210@s.whatsapp.net", sent.getStringExtra("jid"))
        assertEquals(uri, sent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
        assertEquals("Invoice INV/1", sent.getStringExtra(Intent.EXTRA_TEXT))
        assertTrue(sent.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
    }

    @Test fun captionAndCachedBalances(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        d.snap { it.txns.size == 4 }
        val p = repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", mobile = "98765 43210", createdAt = 0, updatedAt = 0))
        val inv = repo.saveInvoice(InvoiceInfo(0, cb, InvoiceKind.SALE, "INV/26-27/007", p, LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 16), 1_180_000))
        val s = d.snap { it.invoices.isNotEmpty() }
        val b = s.invoiceBalances().single { it.invoice.id == inv }
        assertEquals("""Invoice INV/26-27/007 · ₹11,800.00
Balance due: ₹11,800.00 · Due 16-04-2026
Pay by UPI: sharma.assoc@oksbi
— Sharma & Associates""", pdfCaption(context(), "Invoice", b, UiFormat(), BusinessProfileDto(name = "Sharma & Associates", upiId = "sharma.assoc@oksbi")))
        assertEquals("Quotation QT/1 · ₹11,800.00", pdfCaption(context(), "Quotation",
            b.copy(invoice = b.invoice.copy(number = "QT/1", docType = com.cashbook.core.DocType.QUOTATION)), UiFormat(), BusinessProfileDto()))
        // the same snapshot answers repeated questions from its cache
        assertSame(s.invoiceBalances(LocalDate.of(2026, 5, 1)), s.invoiceBalances(LocalDate.of(2026, 5, 1)))
        assertTrue(s.notesOf(inv).isEmpty())
    }
}
