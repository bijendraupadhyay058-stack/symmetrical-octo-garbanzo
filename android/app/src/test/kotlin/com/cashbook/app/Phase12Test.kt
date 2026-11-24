package com.cashbook.app

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.LedgerRepository.ReconcileException
import com.cashbook.core.AccountType
import com.cashbook.core.Ledger
import com.cashbook.core.PaymentMode
import com.cashbook.core.Reconcile
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Bank reconciliation and cash counts. */
@RunWith(AndroidJUnit4::class)
class Phase12Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    private suspend fun add(t: Txn) = repo.saveTxn(t, emptyList(), emptyList())

    @Test fun reconcileBankAccount(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val bank = s.accounts.first { it.cashbookId == cb && it.type == AccountType.BANK }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        val fees = s.categories.first { it.kind == com.cashbook.core.CategoryKind.INCOME }.id
        val a = add(Txn(0, cb, TxnType.INCOME, today.minusDays(3), 250_000, bank.id, categoryId = fees, paymentMode = PaymentMode.BANK_TRANSFER, description = "NEFT client"))
        val b = add(Txn(0, cb, TxnType.TRANSFER, today.minusDays(2), 100_000, bank.id, toAccountId = cash.id, description = "Cash withdrawal"))
        val c = add(Txn(0, cb, TxnType.INCOME, today.minusDays(1), 70_000, bank.id, categoryId = fees, description = "Cheque not yet credited"))
        s = d.snap { it.txns.size == 7 }
        val all = Reconcile.uncleared(bank, s.txns, today)
        assertTrue(all.map { it.id }.containsAll(listOf(a, b, c)))
        // the statement shows everything except the cheque
        val statement = Ledger.balanceAsOf(bank, s.txns, today) - 70_000
        val onStatement = all.filter { it.id != c }.map { it.id }
        try { repo.reconcile(bank.id, today, statement, all.map { it.id }); fail() }
        catch (e: ReconcileException) { assertEquals(ReconcileException.Reason.DIFFERENCE, e.reason); assertEquals(-70_000L, e.difference) }
        repo.reconcile(bank.id, today, statement, onStatement)
        s = d.snap { it.reconciliations.size == 1 }
        assertEquals(listOf(c), Reconcile.uncleared(bank, s.txns, today).map { it.id })
        assertEquals(statement, Reconcile.clearedBalance(bank, s.txns))
        assertEquals(onStatement.size, s.reconciliations.single().entries)
        // the transfer is cleared on the bank side only; the cash side is still open
        val tr = s.txns.single { it.id == b }
        assertEquals(today, tr.clearedOn); assertNull(tr.toClearedOn)
        assertTrue(Reconcile.uncleared(cash, s.txns, today).any { it.id == b })
        // an entry can't be cleared twice, and other accounts' entries are refused
        try { repo.reconcile(bank.id, today, statement, listOf(a)); fail() } catch (e: ReconcileException) { assertEquals(ReconcileException.Reason.INVALID_ENTRY, e.reason) }

        // editing words keeps it cleared; changing the amount un-clears it
        add(s.txns.single { it.id == a }.copy(description = "NEFT from ABC"))
        s = d.snap { it.txns.single { t -> t.id == a }.description == "NEFT from ABC" }
        assertNotNull(s.txns.single { it.id == a }.clearedOn)
        add(s.txns.single { it.id == a }.copy(amount = 260_000))
        s = d.snap { it.txns.single { t -> t.id == a }.amount == 260_000L }
        assertNull(s.txns.single { it.id == a }.clearedOn)
        // undo on one side
        repo.unclear(b, bank.id)
        assertNull(d.snap { it.txns.single { t -> t.id == b }.clearedOn == null }.txns.single { it.id == b }.clearedOn)
    }

    @Test fun cashCountRecordsTheDifference(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        val book = Ledger.balanceAsOf(cash, s.txns, today)
        assertEquals(1_350_000L, book)                                                               // ₹13,500 in the sample
        // counted ₹13,380: 26 × 500 + 1 × 200 + 18 × 10 → short by ₹120
        val id = repo.saveCashCount(cash.id, today, mapOf(500 to 26, 200 to 1, 10 to 18), "Evening count", true, "Cash excess", "Cash shortage", "Cash count difference")
        s = d.snap { it.cashCounts.isNotEmpty() && it.txns.size == 5 }
        val cc = s.cashCounts.single()
        assertEquals(id, cc.id); assertEquals(1_338_000L, cc.counted); assertEquals(1_350_000L, cc.book); assertEquals(-12_000L, cc.difference)
        val adj = s.txns.single { it.id == cc.adjustmentTxnId }
        assertEquals(TxnType.EXPENSE, adj.type); assertEquals(12_000L, adj.amount); assertEquals("Cash shortage", s.categoryName(adj.categoryId))
        assertEquals(1_338_000L, Ledger.balanceAsOf(cash, s.txns, today))                            // books now match the drawer
        // an excess the next day reuses / creates the income category; a count without recording adds no entry
        repo.saveCashCount(cash.id, today, mapOf(500 to 27), "", true, "Cash excess", "Cash shortage", "Cash count difference")
        s = d.snap { it.cashCounts.size == 2 }
        assertEquals(TxnType.INCOME, s.txns.single { it.id == s.cashCounts.first().adjustmentTxnId }.type)
        repo.saveCashCount(cash.id, today, mapOf(500 to 30), "", false, "Cash excess", "Cash shortage", "x")
        s = d.snap { it.cashCounts.size == 3 }
        assertNull(s.cashCounts.first().adjustmentTxnId)
        assertEquals(1, s.categories.count { it.name == "Cash shortage" })

        // reconciliation and counts survive a backup
        val bank = s.accounts.first { it.cashbookId == cb && it.type == AccountType.BANK }
        repo.reconcile(bank.id, today, Ledger.balanceAsOf(bank, s.txns, today), Reconcile.uncleared(bank, s.txns, today).map { it.id })
        s = d.snap { it.reconciliations.isNotEmpty() }
        val cleared = s.txns.count { it.clearedOn != null || it.toClearedOn != null }
        val file = File(context().cacheDir, "p12.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(cb)); d.snap { it.cashCounts.isEmpty() && it.reconciliations.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        s = d.snap { it.cashCounts.size == 3 && it.reconciliations.size == 1 }
        assertEquals(cleared, s.txns.count { it.clearedOn != null || it.toClearedOn != null })
        assertEquals(mapOf(500 to 26, 200 to 1, 10 to 18), s.cashCounts.last().counts)
    }
}
