package com.cashbook.core

import com.cashbook.core.LedgerImport.Field
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class LedgerImportTest {
    private fun d(m: Int, day: Int) = LocalDate.of(2026, m, day)

    // a typical cashbook-app export: Cash In / Cash Out columns, category, mode, party, remarks
    private val cashInOut = """
Office Cashbook – exported 25/11/2026
Date,Remark,Category,Mode,Cash In,Cash Out,Balance,Party
01/11/2026,Opening sale,Sales,Cash,"5,000",,5000,
02/11/2026,Tea & snacks,Food,Cash,,120,4880,
03/11/2026,Courier,Postage,UPI,,250.50,4629.50,Blue Dart
,,,Total,"5,000",370.50,,
""".trimIndent()

    // a spreadsheet: one signed amount, a Type column, an Account column
    private val typed = listOf(
        listOf("S.No", "Dated", "Particulars", "Amount", "Type", "Account", "Head", "Ref No"),
        listOf("1", "05-11-2026", "Rent for November", "15000", "Expense", "SBI Bank", "Rent", "CHQ 101"),
        listOf("2", "06-11-2026", "Consulting fees", "25000", "Income", "", "Fees", ""),
        listOf("3", "07-11-2026", "Cash to bank", "2000", "Transfer", "", "", ""),
        listOf("4", "08-11-2026", "Mystery", "10", "Refund?", "", "", ""),
        listOf("5", "", "No date here", "99", "Expense", "", "", ""),
        listOf("6", "09-11-2026", "Zero", "0", "Expense", "", "", ""),
    )

    @Test fun cashInOutExport() {
        val rows = StatementImport.splitRows(cashInOut)
        val m = LedgerImport.guess(rows)!!
        assertEquals(1, m.headerRow)
        assertEquals(mapOf(Field.DATE to 0, Field.DESCRIPTION to 1, Field.CATEGORY to 2, Field.MODE to 3, Field.CREDIT to 4, Field.DEBIT to 5, Field.PARTY to 7),
            m.columns.filterKeys { it != Field.AMOUNT })
        val p = LedgerImport.parse(rows, m)
        assertEquals(listOf(TxnType.INCOME, TxnType.EXPENSE, TxnType.EXPENSE), p.rows.map { it.type })
        assertEquals(listOf(500_000L, 12_000L, 25_050L), p.rows.map { it.amount })
        assertEquals(LedgerImport.ImportRow(5, d(11, 3), TxnType.EXPENSE, 25_050, "Courier", "Postage", "Blue Dart", "", PaymentMode.UPI), p.rows[2])
        assertTrue(p.problems.isEmpty())                                  // the totals row has no date and is skipped quietly
    }

    @Test fun typedSpreadsheet() {
        val m = LedgerImport.guess(typed)!!
        assertEquals(1, m[Field.DATE]); assertEquals(2, m[Field.DESCRIPTION]); assertEquals(3, m[Field.AMOUNT]); assertEquals(4, m[Field.TYPE])
        assertEquals(5, m[Field.ACCOUNT]); assertEquals(6, m[Field.CATEGORY]); assertEquals(7, m[Field.REFERENCE])
        val p = LedgerImport.parse(typed, m)
        assertEquals(listOf("Rent for November", "Consulting fees"), p.rows.map { it.description })
        assertEquals(listOf(TxnType.EXPENSE, TxnType.INCOME), p.rows.map { it.type })
        assertEquals("SBI Bank", p.rows[0].account); assertEquals("CHQ 101", p.rows[0].reference)
        assertEquals(listOf(LedgerImport.Reason.TRANSFER, LedgerImport.Reason.UNKNOWN_TYPE, LedgerImport.Reason.NO_DATE, LedgerImport.Reason.ZERO_AMOUNT),
            p.problems.map { it.reason })
        assertEquals(listOf(4, 5, 6, 7), p.problems.map { it.row })
    }

    @Test fun signedAmountsAndDuplicates() {
        val rows = listOf(listOf("Date", "Description", "Amount"), listOf("2026-11-10", "Electricity", "-1,800.00"), listOf("2026-11-11", "Interest", "45.20"),
            listOf("12 Nov 2026", "Old bill", "300 Dr"))
        val p = LedgerImport.parse(rows, LedgerImport.guess(rows)!!)
        assertEquals(listOf(TxnType.EXPENSE, TxnType.INCOME, TxnType.EXPENSE), p.rows.map { it.type })
        assertEquals(listOf(180_000L, 4_520L, 30_000L), p.rows.map { it.amount })
        val existing = listOf(Txn(1, 1, TxnType.EXPENSE, d(11, 10), 180_000, 7, description = " electricity "))
        assertTrue(LedgerImport.isDuplicate(p.rows[0], existing, 7))
        assertFalse(LedgerImport.isDuplicate(p.rows[0], existing, 8))                       // another account
        assertFalse(LedgerImport.isDuplicate(p.rows[1], existing, 7))
    }

    @Test fun headersTypesModes() {
        assertEquals(Field.ACCOUNT, LedgerImport.fieldOf("Bank Account"))
        assertEquals(Field.CREDIT, LedgerImport.fieldOf("Cash In"))
        assertEquals(Field.DEBIT, LedgerImport.fieldOf("Withdrawal Amt."))
        assertEquals(Field.PARTY, LedgerImport.fieldOf("Paid To"))
        assertNull(LedgerImport.fieldOf("S.No"))
        assertEquals(TxnType.INCOME, LedgerImport.typeOf("CR")); assertEquals(TxnType.EXPENSE, LedgerImport.typeOf("Debit entry"))
        assertNull(LedgerImport.typeOf("maybe"))
        assertEquals(PaymentMode.UPI, LedgerImport.modeOf("PhonePe")); assertEquals(PaymentMode.BANK_TRANSFER, LedgerImport.modeOf("NEFT"))
        assertEquals(PaymentMode.OTHER, LedgerImport.modeOf("Barter")); assertNull(LedgerImport.modeOf(""))
        assertNull(LedgerImport.guess(listOf(listOf("Name", "Phone"), listOf("A", "1"))))
    }
}
