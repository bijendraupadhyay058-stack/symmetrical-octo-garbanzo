package com.cashbook.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.core.AccountType
import com.cashbook.core.LedgerImport
import com.cashbook.core.PaymentMode
import com.cashbook.core.StatementFiles
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Importing entries from another app's export. */
@RunWith(AndroidJUnit4::class)
class Phase16Test {
    private val d = deps()
    private val repo = d.ledger

    private val csv = """
Date,Particulars,Category,Party,Account,Mode,Cash In,Cash Out
01/10/2026,Consulting retainer,Professional fees,ABC Enterprises,SBI Bank,NEFT,"25,000",
02/10/2026,Printer paper,Stationery Supplies,Office Mart,,Cash,,450
03/10/2026,Taxi to client,Travel and conveyance,,,UPI,,320
03/10/2026,Taxi to client,Travel and conveyance,,,UPI,,320
04/10/2026,Cash to bank,,,,,,
,Total,,,,,"25,000","1,090"
""".trimIndent()

    @Test fun importsMatchesCreatesAndUndoes(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        val bank = s.accounts.first { it.cashbookId == cb && it.type == AccountType.BANK }
        val catsBefore = s.categories.size
        val rows = StatementFiles.rows(csv.toByteArray())
        val parsed = LedgerImport.parse(rows, LedgerImport.guess(rows)!!)
        assertEquals(4, parsed.rows.size)                                       // "Cash to bank" has no amount: not an entry

        val r = repo.importEntries(cb, cash.id, parsed.rows, createMissing = true, tag = "import-test-1")
        assertEquals(4, r.created); assertEquals(0, r.duplicates)
        s = d.snap { it.txns.size == 8 }
        val fees = s.txns.single { it.description == "Consulting retainer" }
        assertEquals(TxnType.INCOME, fees.type); assertEquals(2_500_000L, fees.amount)
        assertEquals(bank.id, fees.accountId)                                   // account matched by name
        assertEquals(PaymentMode.BANK_TRANSFER, fees.paymentMode)
        assertEquals("Professional fees", s.categoryName(fees.categoryId))      // existing category matched
        assertEquals("ABC Enterprises", s.names.party(fees.partyId))            // party created
        val paper = s.txns.single { it.description == "Printer paper" }
        assertEquals(cash.id, paper.accountId)                                  // no account in the file → the chosen one
        assertEquals("Stationery Supplies", s.categoryName(paper.categoryId))   // category created
        assertEquals(1, r.newCategories); assertEquals(2, r.newParties)
        assertEquals(catsBefore + 1, s.categories.size)
        assertEquals(2, s.txns.count { it.description == "Taxi to client" })    // two identical rows in the file are both kept
        assertTrue(s.txns.filter { "import-test-1" in it.tagList }.size == 4)

        // importing the same file again adds nothing
        val again = repo.importEntries(cb, cash.id, parsed.rows, createMissing = true, tag = "import-test-2")
        assertEquals(0, again.created); assertEquals(4, again.duplicates)

        // without creating, unknown categories and parties stay empty
        val other = LedgerImport.parse(listOf(listOf("Date", "Description", "Category", "Party", "Amount"),
            listOf("05/10/2026", "Mystery spend", "Nonexistent", "Nobody", "-99")), LedgerImport.guess(listOf(listOf("Date", "Description", "Category", "Party", "Amount")))!!)
        repo.importEntries(cb, cash.id, other.rows, createMissing = false, tag = "import-test-3")
        s = d.snap { it.txns.any { t -> t.description == "Mystery spend" } }
        s.txns.single { it.description == "Mystery spend" }.let { assertNull(it.categoryId); assertNull(it.partyId) }

        // undo moves exactly that import's entries to the recycle bin
        assertEquals(4, repo.undoImport("import-test-1"))
        s = d.snap { it.txns.none { t -> "import-test-1" in t.tagList } }
        assertEquals(4, s.deleted.count { "import-test-1" in it.tagList })
        assertTrue(s.txns.any { it.description == "Mystery spend" })
    }
}
