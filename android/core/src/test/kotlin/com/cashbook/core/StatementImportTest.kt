package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class StatementImportTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)

    // withdrawal / deposit columns, account details above the header, a totals row below, quoted narration with a comma
    private val sbiStyle = """
Account Name :,SHARMA AND ASSOCIATES
Account Number :,00000031234567890
Statement From :,01/05/2026 to 31/05/2026

Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
02/05/2026,02/05/2026,"NEFT-ABC ENTERPRISES, MUMBAI",N12345678,,"25,000.00","75,000.00"
05/05/2026,05/05/2026,ATM WDL,ATM556,"5,000.00",,"70,000.00"
31/05/2026,31/05/2026,SMS CHARGES,,17.70,,"69,982.30"
,,Total,,"5,017.70","25,000.00",
""".trimIndent()

    // one signed amount column, newest first, dd-MMM-yyyy dates with time, ₹ signs
    private val signedStyle = "Date\tNarration\tAmount (INR)\tBalance (INR)\n" +
        "15-May-2026 18:22\tUPI/ACME/PAYMENT\t-₹1,200.50\t₹8,799.50\n" +
        "10-May-2026 09:05\tINTEREST CREDIT\t₹ 10,000.00\t₹10,000.00\n"

    // amount + Dr/Cr column; overdrawn balance marked Dr
    private val drCrStyle = """
Sl No;Transaction Date;Cheque Number;Transaction Remarks;Amount;Dr/Cr;Balance
1;2026-05-03;000123;CHQ PAID;"1,500.00";DR;"500.00 Dr"
2;2026-05-04;;CASH DEP;"2,000.00";CR;"1,500.00"
""".trimIndent()

    @Test fun debitCreditColumns() {
        val r = StatementImport.parse(sbiStyle)
        assertEquals(3, r.lines.size)
        assertEquals(1, r.skipped)                                           // the totals row
        assertEquals(StatementLine(6, d(5, 2), "NEFT-ABC ENTERPRISES, MUMBAI", "N12345678", 2_500_000, 7_500_000), r.lines[0])
        assertEquals(-500_000L, r.lines[1].amount)
        assertEquals(-1_770L, r.lines[2].amount); assertEquals("", r.lines[2].reference)
        assertEquals(6_998_230L, r.closingBalance)
        assertEquals(d(5, 31), r.lastDate)
    }

    @Test fun signedAmountNewestFirst() {
        val r = StatementImport.parse(signedStyle)
        assertEquals(listOf(d(5, 10), d(5, 15)), r.lines.map { it.date })      // put in date order
        assertEquals(listOf(1_000_000L, -120_050L), r.lines.map { it.amount })
        assertEquals(879_950L, r.closingBalance)                             // balance on the latest row
    }

    @Test fun drCrColumnAndOverdraft() {
        val r = StatementImport.parse(drCrStyle)
        assertEquals(listOf(-150_000L, 200_000L), r.lines.map { it.amount })
        assertEquals("000123", r.lines[0].reference)
        assertEquals(-50_000L, r.lines[0].balance)
        assertEquals(150_000L, r.closingBalance)
    }

    @Test fun parsingDetails() {
        assertEquals(12_345_678L, StatementImport.parseAmount("1,23,456.78"))
        assertEquals(-25_000L, StatementImport.parseAmount("(250.00)"))
        assertEquals(50_000L, StatementImport.parseAmount("500.00 Dr"))
        assertNull(StatementImport.parseAmount("-")); assertNull(StatementImport.parseAmount("abc"))
        assertEquals(d(4, 1), StatementImport.parseDate("01/04/2026"))
        assertEquals(d(4, 1), StatementImport.parseDate("01-04-26"))
        assertEquals(d(4, 1), StatementImport.parseDate("1 Apr 2026"))
        assertEquals(d(4, 1), StatementImport.parseDate("01-APR-2026 10:15"))
        assertNull(StatementImport.parseDate("Total"))
        assertEquals(listOf(listOf("a", "b \"c\"", "d,e"), listOf("1", "", "")), StatementImport.splitRows("a,\"b \"\"c\"\"\",\"d,e\"\r\n1,,\n"))
        assertTrue(runCatching { StatementImport.parse("name,phone\nA,1") }.exceptionOrNull() is StatementImport.FormatException)
    }

    @Test fun matchingEntries() {
        val bank = 2L
        val lines = StatementImport.parse(sbiStyle).lines
        val txns = listOf(
            Txn(1, 1, TxnType.INCOME, d(5, 1), 2_500_000, bank, reference = "N12345678"),     // a day early, same reference
            Txn(2, 1, TxnType.INCOME, d(5, 2), 2_500_000, bank),                             // same amount and date, no reference
            Txn(3, 1, TxnType.TRANSFER, d(5, 5), 500_000, bank, toAccountId = 1),            // ATM withdrawal as a transfer to cash
            Txn(4, 1, TxnType.EXPENSE, d(5, 20), 1_770, bank),                               // too far from 31 May
        )
        val (matched, missing) = StatementMatcher.match(lines, txns, bank)
        assertEquals(listOf(1L, 3L), matched.map { it.txn.id })                            // the reference beats the exact date
        assertEquals(listOf("SMS CHARGES"), missing.map { it.description })
        // re-importing after entries 1 and 3 were cleared: they aren't offered again as missing, nor as matches
        val account = AccountInfo(bank, 1, "SBI", AccountType.BANK, 0, d(4, 1))
        val cleared = txns.map { if (it.id == 1L || it.id == 3L) it.copy(clearedOn = d(5, 31)) else it }
        val (again, stillMissing) = StatementMatcher.matchForReconcile(lines, cleared, account, d(5, 31))
        assertTrue(again.isEmpty())
        assertEquals(listOf("SMS CHARGES"), stillMissing.map { it.description })
    }
}
