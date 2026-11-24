package com.cashbook.core

import com.cashbook.core.backup.BackupCodec
import com.cashbook.core.backup.BackupData
import com.cashbook.core.backup.CashbookDto
import com.cashbook.core.backup.InvoiceDto
import com.cashbook.core.backup.InvoiceScheduleDto
import com.cashbook.core.backup.PartyDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.Locale

class ScheduleTest {
    private fun d(y: Int, m: Int, day: Int) = LocalDate.of(y, m, day)
    private val monthly = InvoiceSchedule(1, 10, Frequency.MONTHLY, 1, d(2026, 1, 31), dueDays = 7)

    @Test fun datesDontDriftAndCatchUpIsCapped() {
        assertEquals(listOf(d(2026, 1, 31), d(2026, 2, 28), d(2026, 3, 31), d(2026, 4, 30)), InvoiceSchedules.due(monthly, d(2026, 5, 29)).map { it.second })
        assertEquals(listOf(2, 3), InvoiceSchedules.due(monthly.copy(nextIndex = 2), d(2026, 5, 1)).map { it.first })
        assertTrue(InvoiceSchedules.due(monthly.copy(active = false), d(2027, 1, 1)).isEmpty())
        assertEquals(2, InvoiceSchedules.due(monthly.copy(endDate = d(2026, 3, 1)), d(2027, 1, 1)).size)
        assertEquals(InvoiceSchedules.MAX_CATCH_UP, InvoiceSchedules.due(monthly, d(2030, 1, 1)).size)
        assertEquals(d(2026, 2, 28), monthly.copy(nextIndex = 1).nextDate)
        assertTrue(monthly.copy(nextIndex = 2, endDate = d(2026, 3, 1)).finished)
        // quarterly every 2 → every 6 months
        assertEquals(d(2026, 7, 31), InvoiceSchedule(2, 11, Frequency.QUARTERLY, 2, d(2026, 1, 31)).occurrence(1))
        // resuming continues from today (no back-fill)
        assertEquals(4, InvoiceSchedules.firstIndexOnOrAfter(monthly, d(2026, 5, 15)))
    }

    @Test fun placeholders() {
        val s = InvoiceSchedule(1, 10, Frequency.MONTHLY, 1, d(2026, 4, 1))
        assertEquals("Retainer for May 2026 (01-05-2026 – 31-05-2026)",
            InvoiceSchedules.fill("Retainer for {month} ({period})", s, 1, DateFormatOption.DD_MM_YYYY, Locale.ENGLISH))
        assertEquals("No placeholders", InvoiceSchedules.fill("No placeholders", s, 3, DateFormatOption.DD_MM_YYYY, Locale.ENGLISH))
    }

    @Test fun templatesAreOffTheBooks() {
        val t = InvoiceInfo(10, 1, InvoiceKind.SALE, "REC/26-27/001", 9, d(2026, 4, 1), d(2026, 4, 1), 590_000, docType = DocType.TEMPLATE)
        assertTrue(DocType.TEMPLATE.isOffBook); assertEquals(0, DocType.TEMPLATE.sign)
        assertTrue(Invoices.balances(listOf(t), emptyList(), emptyMap<Long, TxnType>(), d(2026, 5, 1)).isEmpty())
        val items = mapOf(10L to listOf(InvoiceItem(description = "Toner", quantityMilli = 1_000, rate = 500_000, gstBp = 1800, itemId = 1)))
        assertTrue(Stock.moves(listOf(t), items, emptyList()).isEmpty())
        assertEquals("REC/26-27/002", Invoices.nextNumber(InvoiceKind.SALE, listOf("REC/26-27/001"), d(2026, 5, 1), DocType.TEMPLATE))
    }

    @Test fun transport() {
        assertEquals(Transport("MH12AB1234", "VRL Logistics", "LR-5521", "381001234567"),
            Transport(" mh 12-ab 1234 ", " VRL Logistics ", " LR-5521 ", "3810 0123 4567").normalized())
        assertTrue(Transport().isEmpty); assertFalse(Transport(lrNo = "1").isEmpty)
        assertTrue(Transport.isValidEwayBill("")); assertTrue(Transport.isValidEwayBill("3810 0123 4567"))
        assertFalse(Transport.isValidEwayBill("38100123456")); assertFalse(Transport.isValidEwayBill("38100123456A"))
    }

    @Test fun backupValidatesSchedules() {
        val base = BackupData(listOf(CashbookDto(1, "Shop", openingDate = 0, createdAt = 0, updatedAt = 0)), emptyList(), emptyList(),
            listOf(PartyDto(9, "ABC", "CUSTOMER", createdAt = 0, updatedAt = 0)), emptyList(), emptyList(),
            invoices = listOf(InvoiceDto(10, 1, "SALE", "REC/1", 9, 0, 0, 100, createdAt = 0, updatedAt = 0, docType = "TEMPLATE"),
                InvoiceDto(11, 1, "SALE", "INV/1", 9, 0, 7, 100, createdAt = 0, updatedAt = 0, scheduleId = 5)),
            invoiceSchedules = listOf(InvoiceScheduleDto(5, 10, "MONTHLY", 1, 0, null, 1, 7, true, 0, 0)))
        assertEquals(emptyList<String>(), BackupCodec.validate(base))
        assertTrue(BackupCodec.validate(base.copy(invoiceSchedules = listOf(base.invoiceSchedules[0].copy(templateId = 11)))).isNotEmpty())   // not a template
        assertTrue(BackupCodec.validate(base.copy(invoiceSchedules = listOf(base.invoiceSchedules[0].copy(frequency = "HOURLY")))).isNotEmpty())
        assertTrue(BackupCodec.validate(base.copy(invoiceSchedules = emptyList())).isNotEmpty())                                             // invoice refers to it
        assertNull(base.invoices[0].convertedInvoiceId)
    }
}
