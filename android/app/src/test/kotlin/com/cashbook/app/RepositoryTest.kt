package com.cashbook.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.AttachmentStore
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.Ledger
import com.cashbook.core.PaymentMode
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate

/** Exercises the real Room schema, DAOs and repository rules. */
@RunWith(AndroidJUnit4::class)
class RepositoryTest {
    private val d = deps()
    private val repo = d.ledger
    private val day = { n: Int -> LocalDate.of(2026, 4, n) }

    private fun setupSample(): Long = runBlocking { repo.addSampleData("en", SAMPLE_NAMES) }

    @Test fun sampleDataGivesExpectedBalances() = runBlocking {
        val cb = setupSample()
        val s = d.snap { it.txns.size == 4 }
        val accs = s.accounts.filter { it.cashbookId == cb }
        val cash = accs.first { it.type == AccountType.CASH }
        val bank = accs.first { it.type == AccountType.BANK }
        assertEquals(1_350_000L, Ledger.currentBalance(cash, s.txns))
        assertEquals(5_900_000L, Ledger.currentBalance(bank, s.txns))
        assertEquals(7_250_000L, accs.sumOf { Ledger.currentBalance(it, s.txns) })
        assertTrue("default categories created", s.categories.size >= 22)
    }

    @Test fun addEditDeleteRestoreRecalculates() = runBlocking {
        val cb = setupSample()
        var s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        val cat = s.categories.first { it.kind == CategoryKind.EXPENSE }
        val id = repo.saveTxn(Txn(0, cb, TxnType.EXPENSE, day(10), 250_000, cash.id, categoryId = cat.id, paymentMode = PaymentMode.CASH, description = "Office rent"), emptyList(), emptyList())
        s = d.snap { it.txns.size == 5 }
        assertEquals(1_100_000L, Ledger.currentBalance(cash, s.txns))
        // edit
        repo.saveTxn(s.txns.first { it.id == id }.copy(amount = 300_000), emptyList(), emptyList())
        s = d.snap { it.txns.any { t -> t.id == id && t.amount == 300_000L } }
        assertEquals(1_050_000L, Ledger.currentBalance(cash, s.txns))
        val edited = s.txns.first { it.id == id }
        assertTrue(edited.updatedAt >= edited.createdAt)
        // delete -> recycle bin
        repo.deleteTxn(id)
        s = d.snap { it.txns.none { t -> t.id == id } }
        assertEquals(1, s.deleted.size)
        assertEquals(1_350_000L, Ledger.currentBalance(cash, s.txns))
        // restore
        repo.restoreTxn(id)
        s = d.snap { it.txns.any { t -> t.id == id } }
        assertEquals(1_050_000L, Ledger.currentBalance(cash, s.txns))
    }

    @Test fun transferIsOneLinkedEntry() = runBlocking {
        val cb = setupSample()
        var s = d.snap { it.txns.size == 4 }
        val transfer = s.txns.first { it.type == TxnType.TRANSFER }
        val accs = s.accounts.filter { it.cashbookId == cb }
        val total = { snap: com.cashbook.app.data.Snapshot -> accs.sumOf { Ledger.currentBalance(it, snap.txns) } }
        assertEquals(7_250_000L, total(s))
        repo.deleteTxn(transfer.id)
        s = d.snap { it.deleted.size == 1 }
        val cash = accs.first { it.type == AccountType.CASH }
        val bank = accs.first { it.type == AccountType.BANK }
        assertEquals(850_000L, Ledger.currentBalance(cash, s.txns))   // both sides removed together
        assertEquals(6_400_000L, Ledger.currentBalance(bank, s.txns))
        assertEquals(7_250_000L, total(s))                             // combined total unchanged
        repo.restoreTxn(transfer.id)
        s = d.snap { it.deleted.isEmpty() }
        assertEquals(1_350_000L, Ledger.currentBalance(cash, s.txns))
        assertEquals(5_900_000L, Ledger.currentBalance(bank, s.txns))
    }

    @Test fun categoryCannotBeDeletedWhileUsedUnlessReassigned() = runBlocking {
        setupSample()
        val s = d.snap { it.txns.size == 4 }
        val used = s.txns.first { it.type == TxnType.EXPENSE }.categoryId!!
        val other = s.categories.first { it.kind == CategoryKind.EXPENSE && it.id != used }
        assertFalse(repo.deleteCategory(used, null))
        // rename keeps history
        repo.saveCategory(used, CategoryKind.EXPENSE, "Stationery (renamed)", null, "print")
        val renamed = d.snap { it.categoryById[used]?.name == "Stationery (renamed)" }
        assertEquals("Stationery (renamed)", renamed.categoryName(renamed.txns.first { it.categoryId == used }.categoryId))
        assertTrue(repo.deleteCategory(used, other.id))
        val after = d.snap { it.categoryById[used] == null }
        assertTrue(after.txns.none { it.categoryId == used })
        assertEquals(4, after.txns.size)
    }

    @Test fun partyInUseCannotBeDeleted() = runBlocking {
        val cb = setupSample()
        val s = d.snap { it.txns.size == 4 }
        val pid = repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CLIENT", createdAt = 0, updatedAt = 0))
        val income = s.txns.first { it.type == TxnType.INCOME }
        repo.saveTxn(income.copy(partyId = pid), emptyList(), emptyList())
        d.snap { it.txns.any { t -> t.partyId == pid } }
        assertFalse(repo.deleteParty(pid))
        val unused = repo.saveParty(PartyEntity(name = "Unused", type = "OTHER", createdAt = 0, updatedAt = 0))
        assertTrue(repo.deleteParty(unused))
        assertNotNull(cb)
    }

    @Test fun accountWithEntriesCannotBeDeletedButCanBeArchived() = runBlocking {
        val cb = setupSample()
        val s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        assertFalse(repo.deleteAccount(cash.id))
        repo.setAccountArchived(cash.id, true)
        val after = d.snap { it.accountById[cash.id]?.archived == true }
        assertEquals(1_350_000L, Ledger.currentBalance(after.accountById[cash.id]!!, after.txns)) // history kept
        val empty = repo.addAccount(cb, LedgerRepository.NewAccount("Petty cash", AccountType.CASH, 0, day(1)))
        assertTrue(repo.deleteAccount(empty))
    }

    @Test fun deletingCashbookReportsImpactAndRemovesEverything() = runBlocking {
        val keep = repo.createCashbook("Personal", "", day(1), listOf(LedgerRepository.NewAccount("Wallet", AccountType.WALLET, 10_000, day(1))))
        val cb = setupSample()
        d.snap { it.txns.size == 4 }
        val impact = repo.cashbookDeleteImpact(cb)
        assertEquals(2, impact.accounts)
        assertEquals(4, impact.transactions)
        repo.deleteCashbooks(listOf(cb))
        val s = d.snap { it.cashbookById[cb] == null }
        assertTrue(s.txns.isEmpty())
        assertEquals(listOf(keep), s.cashbooks.map { it.id })
        assertEquals(1, s.accounts.size)
    }

    @Test fun removeSampleDataLeavesUserData() = runBlocking {
        val mine = repo.createCashbook("Shop", "", day(1), listOf(LedgerRepository.NewAccount("Cash", AccountType.CASH, 0, day(1))))
        setupSample()
        d.snap { it.cashbooks.size == 2 }
        repo.removeSampleData()
        val s = d.snap { it.cashbooks.size == 1 }
        assertEquals(mine, s.cashbooks.single().id)
    }

    @Test fun recycleBinRetentionPurgesOldEntriesAndFiles() = runBlocking {
        val cb = setupSample()
        val s = d.snap { it.txns.size == 4 }
        val t = s.txns.first { it.type == TxnType.EXPENSE }
        // attach a file
        val f = d.attachments.file("test.png").apply { writeBytes(byteArrayOf(1, 2, 3)) }
        repo.saveTxn(t, listOf(AttachmentStore.Imported("test.png", "bill.png", "image/png", 3)), emptyList())
        d.snap { it.attachmentCounts[t.id] == 1 }
        repo.deleteTxn(t.id)
        d.snap { it.deleted.size == 1 }
        repo.purgeOlderThan(30)          // deleted just now: kept
        assertEquals(1, d.snap { true }.deleted.size)
        repo.emptyRecycleBin()
        d.snap { it.deleted.isEmpty() }
        assertFalse("attachment file removed with entry", f.exists())
        assertNotNull(cb)
    }
}
