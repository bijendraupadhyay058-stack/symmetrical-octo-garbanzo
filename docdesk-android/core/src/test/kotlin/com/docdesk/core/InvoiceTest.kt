package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InvoiceTest {
    private fun page(vararg lines: String): PageText {
        val words = lines.flatMapIndexed { li, l -> var x = 10f; l.split(" ").filter { it.isNotEmpty() }.map { w -> TextWord(w, x, 20f + li * 15f, w.length * 5f, 10f).also { x += w.length * 5f + 3f } } }
        return PageText(0, 600f, 800f, words, TextSource.PDF_TEXT)
    }

    @Test fun intraStateInvoice() {
        val r = InvoiceExtractor.extract(listOf(page(
            "TAX INVOICE", "Sample Supplies Pvt Ltd GSTIN: 27AAPFU0939F1ZV",
            "Invoice No: INV/2024-25/0042 Date: 15-Apr-2024",
            "Bill to: Example Traders GSTIN 27AAACR5055K1Z7",
            "Sub-total 26,482.50", "CGST 9% 2,383.42", "SGST 9% 2,383.42", "Round off 0.01", "Grand Total 31,249.35",
        )), "inv42.pdf")
        assertEquals("INV/2024-25/0042", r.invoiceNo)
        assertEquals(LocalDate.of(2024, 4, 15), r.date)
        assertEquals("27AAPFU0939F1ZV", r.supplierGstin)
        assertEquals("27AAACR5055K1Z7", r.buyerGstin)
        assertEquals(BigDecimal("26482.50"), r.taxable)
        assertEquals(BigDecimal("2383.42"), r.cgst); assertEquals(BigDecimal("2383.42"), r.sgst)
        assertNull(r.igst)
        assertEquals(BigDecimal("31249.35"), r.total)
        assertTrue(r.flags.joinToString(), r.flags.none { it.contains("Taxable +") || it.contains("states") })
    }

    @Test fun flagsWrongTaxType() {
        val r = InvoiceExtractor.extract(listOf(page("GSTIN 27AAPFU0939F1ZV", "Invoice # A-17 dated 02/05/2024", "Buyer GSTIN 29AAACR5055K1Z5",
            "Taxable Value 10,000.00", "CGST 900.00", "SGST 900.00", "Total Amount 11,800.00")), "a17.pdf")
        assertTrue(r.flags.any { it.contains("different states") })
    }

    @Test fun missingFieldsStayBlank() {
        val r = InvoiceExtractor.extract(listOf(page("Receipt", "Thank you")), "x.pdf")
        assertNull(r.total); assertNull(r.invoiceNo); assertNull(r.supplierGstin)
        assertTrue(r.flags.size >= 3)
    }

    @Test fun registerChecks() {
        fun rec(src: String, no: String?, d: LocalDate?, gstin: String?) = InvoiceRecord(src, no, d, d?.toString(), gstin, null, BigDecimal("100"), null, null, null, null, BigDecimal("118"), emptyList(), emptyMap())
        val out = InvoiceChecks.apply(listOf(
            rec("a.pdf", "INV-1", LocalDate.of(2024, 5, 1), "27AAPFU0939F1ZV"),
            rec("b.pdf", "inv 1", LocalDate.of(2025, 2, 1), "27AAPFU0939F1ZV"), // same FY 2024-25 → duplicate
            rec("c.pdf", "INV-1", LocalDate.of(2025, 5, 1), "27AAPFU0939F1ZV"), // next FY → not a duplicate
            rec("d.pdf", null, null, null),
        ), setOf(InvoiceChecks.Field.INVOICE_NO, InvoiceChecks.Field.SUPPLIER_GSTIN))
        assertTrue(out[1].flags.single().startsWith("Possible duplicate of a.pdf"))
        assertTrue(out[0].flags.isEmpty() && out[2].flags.isEmpty())
        assertEquals(listOf("Required field missing: Invoice number", "Required field missing: Supplier GSTIN"), out[3].flags)
        val sheets = InvoiceExtractor.toSheets(out)
        assertEquals(listOf("Invoice register", "Line items", "Where values came from", "About the checks"), sheets.map { it.name })
    }
}
