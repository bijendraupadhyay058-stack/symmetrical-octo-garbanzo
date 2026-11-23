package com.cashbook.core

import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class QuotationUpiTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)
    private val toner = CatalogItem(1, "Toner", ItemKind.GOODS, "8443", "Nos", saleRate = 250_000, gstBp = 1800, openingStockMilli = 10_000, openingDate = d(4, 1))
    private val quote = InvoiceInfo(1, 1, InvoiceKind.SALE, "QT/26-27/001", 9, d(5, 1), d(5, 15), 590_000, docType = DocType.QUOTATION, placeOfSupply = "27")

    @Test fun quotationStatus() {
        assertEquals(QuoteStatus.OPEN, Quotations.status(quote, d(5, 15)))
        assertEquals(QuoteStatus.EXPIRED, Quotations.status(quote, d(5, 16)))
        assertEquals(QuoteStatus.DECLINED, Quotations.status(quote.copy(cancelled = true), d(5, 2)))
        // converted wins over expiry
        assertEquals(QuoteStatus.CONVERTED, Quotations.status(quote.copy(convertedInvoiceId = 7), d(6, 30)))
        assertEquals(quote.copy(convertedInvoiceId = 7), Quotations.sourceOf(7, listOf(quote.copy(convertedInvoiceId = 7))))
        assertNull(Quotations.sourceOf(8, listOf(quote.copy(convertedInvoiceId = 7))))
    }

    @Test fun quotationNumbering() {
        assertEquals("QT/26-27/001", Invoices.nextNumber(InvoiceKind.SALE, listOf("INV/26-27/004"), d(5, 1), DocType.QUOTATION))
        assertEquals("QT/26-27/003", Invoices.nextNumber(InvoiceKind.SALE, listOf("QT/26-27/002", "QT/25-26/009"), d(5, 1), DocType.QUOTATION))
        assertEquals("INV/26-27/005", Invoices.nextNumber(InvoiceKind.SALE, listOf("INV/26-27/004", "QT/26-27/009"), d(5, 1)))
    }

    @Test fun quotationsOweNothingAndDontMoveStock() {
        val inv = InvoiceInfo(2, 1, InvoiceKind.SALE, "INV/26-27/001", 9, d(5, 2), d(5, 17), 118_000, placeOfSupply = "27")
        val balances = Invoices.balances(listOf(quote, inv), emptyList(), emptyMap<Long, TxnType>(), d(5, 3))
        assertEquals(listOf(2L), balances.map { it.invoice.id })      // the quotation is not a receivable
        assertEquals(DocType.QUOTATION.sign, 0)
        assertFalse(DocType.QUOTATION.isNote)
        assertEquals(Invoices.NoteError.NOT_AN_INVOICE, Invoices.validateNote(quote, listOf(quote), DocType.CREDIT_NOTE, 100))
        assertEquals(Invoices.NoteError.NOT_AN_INVOICE, Invoices.validateNote(inv, listOf(inv), DocType.QUOTATION, 100))
        val items = mapOf(1L to listOf(InvoiceItem(description = "Toner", quantityMilli = 2_000, rate = 250_000, gstBp = 1800, itemId = 1)))
        val moves = Stock.moves(listOf(quote), items, emptyList())
        assertTrue(moves.isEmpty())
        assertEquals(10_000L, Stock.onHand(toner, moves, d(5, 30)))
        assertTrue(Stock.itemSales(listOf(quote), items, mapOf(1L to toner), "27", DateRange(d(4, 1), d(6, 30))).isEmpty())
    }

    @Test fun upiIdsAndLinks() {
        assertTrue(Upi.isValidVpa("shop.name@okhdfcbank"))
        assertTrue(Upi.isValidVpa("9876543210@ybl"))
        assertTrue(Upi.isValidVpa(" sharma-traders_1@paytm "))
        listOf("", "shop", "@ybl", "a@", "a b@ybl", "shop@9bank", "shop@@ybl", "x@ybl").forEach { assertFalse(it, Upi.isValidVpa(it)) }
        assertEquals("upi://pay?pa=shop@okhdfcbank&pn=Sharma%20Traders&am=5900.00&cu=INR&tn=INV/26-27/001",
            Upi.payUri("shop@okhdfcbank", "Sharma Traders", 590_000, "INV/26-27/001"))
        assertEquals("upi://pay?pa=shop@ybl&am=0.05&cu=INR", Upi.payUri("shop@ybl", "", 5))
        assertEquals("upi://pay?pa=shop@ybl&pn=A%26B%3DC&cu=INR", Upi.payUri("shop@ybl", "A&B=C", null))
        assertEquals("%E0%A4%B6", Upi.encode("श"))
    }

    @Test fun qrRoundTrip() {
        val uri = Upi.payUri("shop.name@okhdfcbank", "शर्मा ट्रेडर्स", 1_23_45_678_90, "INV/26-27/001")
        val qr = Qr.encode(uri)
        assertTrue(qr.size in 21..177 && (qr.size - 17) % 4 == 0)
        // render with a 4-module quiet zone at 4 px per module and read it back with ZXing's decoder
        val scale = 4; val n = (qr.size + 8) * scale
        val px = IntArray(n * n) { i ->
            val mx = (i % n) / scale - 4; val my = (i / n) / scale - 4
            if (mx in 0 until qr.size && my in 0 until qr.size && qr[mx, my]) 0xFF000000.toInt() else 0xFFFFFFFF.toInt()
        }
        val result = QRCodeReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(n, n, px))), mapOf(DecodeHintType.PURE_BARCODE to true, DecodeHintType.CHARACTER_SET to "UTF-8"))
        assertEquals(uri, result.text)
    }
}
