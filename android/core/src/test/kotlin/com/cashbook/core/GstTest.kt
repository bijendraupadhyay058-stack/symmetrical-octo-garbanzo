package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class GstTest {
    @Test fun gstinCheckDigit() {
        assertTrue(Gst.isValidGstin("27AAPFU0939F1ZV"))          // example from the GST portal
        assertTrue(Gst.isValidGstin("29aagcb7383j1z4"))          // case-insensitive
        assertFalse(Gst.isValidGstin("27AAPFU0939F1ZX"))         // wrong check digit
        assertFalse(Gst.isValidGstin("99AAPFU0939F1ZV"))         // unknown state
        assertFalse(Gst.isValidGstin("27AAPFU0939F1Z"))          // too short
        assertEquals("27", Gst.stateFromGstin("27AAPFU0939F1ZV"))
        assertEquals("27 – Maharashtra", Gst.stateLabel("27"))
    }

    @Test fun rateLabels() {
        assertEquals(listOf("0%", "0.25%", "3%", "5%", "12%", "18%", "28%", "40%"), Gst.RATES_BP.map { Gst.rateLabel(it) })
    }

    private val items = listOf(
        InvoiceItem(description = "Audit fees", hsn = "998221", quantityMilli = 1000, unit = "Nos", rate = 5_000_000, gstBp = 1800),
        InvoiceItem(description = "Printing", hsn = "4911", quantityMilli = 2500, unit = "Kg", rate = 12_345, discountBp = 1000, gstBp = 500),
    )

    @Test fun intraStateSplitsCgstSgst() {
        val t = GstCalc.totals(items, interState = false, roundOff = true)
        // line 2: 2.5 × 123.45 = 308.625 → 308.63; 10 % discount 30.86 → taxable 277.77; 2.5 % = 6.94 each
        assertEquals(30_863L, t.lines[1].gross)
        assertEquals(3_086L, t.lines[1].discount)
        assertEquals(27_777L, t.lines[1].taxable)
        assertEquals(694L, t.lines[1].cgst)
        assertEquals(694L, t.lines[1].sgst)
        assertEquals(450_000L, t.lines[0].cgst)
        assertEquals(5_027_777L, t.taxable)
        assertEquals(901_388L, t.tax)
        assertEquals(0L, t.igst)
        assertEquals(5_929_165L, t.beforeRounding)
        assertEquals(35L, t.roundOff)                            // ₹59,291.65 → ₹59,292.00
        assertEquals(5_929_200L, t.grandTotal)
        assertEquals(-49L, GstCalc.totals(listOf(InvoiceItem(description = "x", rate = 10_049)), false, true).roundOff) // ₹100.49 → ₹100.00
    }

    @Test fun interStateUsesIgstAndRoundsToNearestRupee() {
        val t = GstCalc.totals(items, interState = true, roundOff = true)
        assertEquals(0L, t.cgst + t.sgst)
        assertEquals(900_000L + 1_389L, t.igst)                  // 5 % of 277.77 = 13.8885 → 13.89
        assertEquals(5_929_166L, t.beforeRounding)
        assertEquals(34L, t.roundOff)                            // 59,291.66 → 59,292.00
        assertEquals(5_929_200L, t.grandTotal)
        assertEquals(listOf(500, 1800), t.breakup.map { it.gstBp })
        assertEquals(5_929_166L, GstCalc.totals(items, true, roundOff = false).grandTotal)
    }

    @Test fun parsing() {
        assertEquals(1500L, Gst.parseQuantity("1.5"))
        assertEquals(1L, Gst.parseQuantity("0.001"))
        assertEquals(null, Gst.parseQuantity("0"))
        assertEquals(null, Gst.parseQuantity("1.2345"))
        assertEquals(null, Gst.parseQuantity("abc"))
        assertEquals(1250, Gst.parsePercent("12.5"))
        assertEquals(0, Gst.parsePercent(""))
        assertEquals(null, Gst.parsePercent("101"))
        assertEquals(null, Gst.parsePercent("-1"))
        assertEquals("1.5", Gst.formatQuantity(1500))
        assertEquals("12.5", Gst.formatPercent(1250))
    }

    @Test fun placeOfSupply() {
        assertTrue(GstCalc.isInterState("27", "29"))
        assertFalse(GstCalc.isInterState("27", "27"))
        assertFalse(GstCalc.isInterState("", "29"))              // unknown seller state → treated as intra-state
    }

    @Test fun amountInWordsIndianSystem() {
        assertEquals("Rupees One Lakh Twenty-Five Thousand Only", AmountInWords.rupees(12_500_000))
        assertEquals("Rupees Twelve Crore Thirty-Four Lakh Fifty-Six Thousand Seven Hundred Eighty-Nine and Fifty Paise Only", AmountInWords.rupees(12_345_678_950))
        assertEquals("Rupees Zero Only", AmountInWords.rupees(0))
        assertEquals("Rupees Five Hundred and Five Paise Only", AmountInWords.rupees(50_005))
    }

    @Test fun gstSummaryReport() {
        val sale = InvoiceInfo(1, 1, InvoiceKind.SALE, "INV/1", 9, LocalDate.of(2026, 4, 5), LocalDate.of(2026, 4, 20), 0, placeOfSupply = "27")
        val sale2 = sale.copy(id = 2, number = "INV/2", placeOfSupply = "29")
        val bill = InvoiceInfo(3, 1, InvoiceKind.PURCHASE, "B/1", 9, LocalDate.of(2026, 4, 6), LocalDate.of(2026, 4, 30), 0, placeOfSupply = "27")
        val cancelled = sale.copy(id = 4, number = "INV/3", cancelled = true)
        val one = listOf(InvoiceItem(description = "Service", quantityMilli = 1000, rate = 1_000_000, gstBp = 1800))
        val doc = ReportEngine(ReportInput(ReportType.GST_SUMMARY, "Office", accounts = SampleScenario.accounts, categories = emptyMap(), parties = emptyMap(),
            txns = emptyList(), range = DateRange(LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 30)), generatedAt = "now",
            invoices = listOf(sale, sale2, bill, cancelled), invoiceItems = mapOf(1L to one, 2L to one, 3L to one.map { it.copy(rate = 400_000) }, 4L to one),
            sellerState = "27")).build()
        assertEquals(Cell.Amount(360_000), doc.summary[0].value)  // 18 % of 10,000 twice (one CGST+SGST, one IGST)
        assertEquals(Cell.Amount(72_000), doc.summary[1].value)
        assertEquals(Cell.Amount(288_000), doc.summary[2].value)
        val outTotal = doc.tables[0].rows.last().cells
        assertEquals(Cell.Amount(90_000), outTotal[2])           // CGST
        assertEquals(Cell.Amount(180_000), outTotal[4])          // IGST
    }
}
