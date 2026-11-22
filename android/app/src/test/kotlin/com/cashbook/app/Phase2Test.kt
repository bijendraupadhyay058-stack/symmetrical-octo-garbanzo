package com.cashbook.app

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.AutoBackup
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.Frequency
import com.cashbook.core.Ledger
import com.cashbook.core.RecurringRule
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate
import java.time.LocalDateTime

/** Recurring entries, budgets and automatic-backup housekeeping against the real database. */
@RunWith(AndroidJUnit4::class)
class Phase2Test {
    private val d = deps()
    private val repo = d.ledger

    private data class Fixture(val cb: Long, val cash: Long, val bank: Long, val rent: Long, val salary: Long)

    private fun fixture(): Fixture = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        val s = d.snap { it.txns.size == 4 }
        Fixture(cb, s.accounts.first { it.type == AccountType.CASH }.id, s.accounts.first { it.type == AccountType.BANK }.id,
            s.categories.first { it.name == "Office rent" }.id, s.categories.first { it.name == "Salary and wages" }.id)
    }

    private fun rent(f: Fixture, start: LocalDate, auto: Boolean = true) =
        RecurringRule(0, f.cb, TxnType.EXPENSE, 1_000_000, f.bank, categoryId = f.rent, description = "Office rent", frequency = Frequency.MONTHLY,
            startDate = start, autoPost = auto)

    @Test fun autoPostCatchesUpOnceAndIsIdempotent() = runBlocking {
        val f = fixture()
        val today = LocalDate.of(2026, 7, 10)
        val id = repo.saveRecurring(rent(f, LocalDate.of(2026, 4, 5)))
        assertEquals(4, repo.postDueRecurring(today))            // Apr, May, Jun, Jul
        assertEquals(0, repo.postDueRecurring(today))            // running again creates nothing
        val s = d.snap { it.txns.count { t -> t.recurringId == id } == 4 }
        assertEquals(listOf(5, 5, 5, 5), s.txns.filter { it.recurringId == id }.map { it.date.dayOfMonth })
        assertEquals(LocalDate.of(2026, 8, 5), s.recurring.single().nextDate)
        // bank: 59,000 − 4 × 10,000
        assertEquals(1_900_000L, Ledger.currentBalance(s.accountById[f.bank]!!, s.txns))
        assertEquals(1, repo.postDueRecurring(LocalDate.of(2026, 8, 5)))
    }

    @Test fun manualRulesWaitForPostOrSkip() = runBlocking {
        val f = fixture()
        val id = repo.saveRecurring(rent(f, LocalDate.of(2026, 4, 5), auto = false))
        assertEquals(0, repo.postDueRecurring(LocalDate.of(2026, 7, 10)))
        repo.skipNextOccurrence(id)                                // April skipped
        val posted = repo.postNextOccurrence(id, amount = 1_250_000) // May posted with a different amount
        val s = d.snap { it.txns.any { t -> t.id == posted } }
        val t = s.txns.first { it.id == posted }
        assertEquals(LocalDate.of(2026, 5, 5), t.date)
        assertEquals(1_250_000L, t.amount)
        assertEquals(LocalDate.of(2026, 6, 5), s.recurring.single().nextDate)
    }

    @Test fun pausedAndEndedRulesStop() = runBlocking {
        val f = fixture()
        val id = repo.saveRecurring(rent(f, LocalDate.of(2026, 4, 5)).copy(endDate = LocalDate.of(2026, 5, 31)))
        assertEquals(2, repo.postDueRecurring(LocalDate.of(2026, 12, 31)))
        assertNull(d.snap { it.recurring.isNotEmpty() && it.recurring[0].nextIndex == 2 }.recurring[0].nextDate)
        val id2 = repo.saveRecurring(rent(f, LocalDate.of(2026, 4, 1)))
        repo.setRecurringActive(id2, false)
        assertEquals(0, repo.postDueRecurring(LocalDate.of(2026, 12, 31)))
        assertTrue(id != id2)
    }

    @Test fun changingScheduleDoesNotRepostPastDates() = runBlocking {
        val f = fixture()
        val id = repo.saveRecurring(rent(f, LocalDate.of(2026, 1, 1)))
        repo.postDueRecurring(LocalDate.now())
        val before = d.snap { it.recurring.single().nextIndex > 0 }.txns.count { it.recurringId == id }
        val rule = d.snap { true }.recurring.single()
        repo.saveRecurring(rule.copy(startDate = LocalDate.of(2026, 1, 15)))
        repo.postDueRecurring(LocalDate.now())
        val after = d.snap { true }.txns.count { it.recurringId == id }
        assertTrue("no past occurrences re-created (before=$before after=$after)", after - before <= 1)
    }

    @Test fun rulesProtectAccountsAndFollowCategoryReassignment() = runBlocking {
        val f = fixture()
        val petty = repo.addAccount(f.cb, com.cashbook.app.data.LedgerRepository.NewAccount("Petty", AccountType.CASH, 0, LocalDate.of(2026, 4, 1)))
        repo.saveRecurring(rent(f, LocalDate.of(2030, 1, 1)).copy(accountId = petty))
        assertFalse(repo.deleteAccount(petty))                  // used by a schedule
        val other = d.snap { true }.categories.first { it.kind == CategoryKind.EXPENSE && it.id != f.rent }
        assertFalse(repo.deleteCategory(f.rent, null))
        assertTrue(repo.deleteCategory(f.rent, other.id))
        assertEquals(other.id, d.snap { it.categoryById[f.rent] == null }.recurring.single().categoryId)
    }

    @Test fun budgetsSetUpdateRemove() = runBlocking {
        val f = fixture()
        repo.setBudget(f.cb, f.rent, 1_500_000)
        assertEquals(1_500_000L, d.snap { it.budgets.size == 1 }.budgets.single().monthlyAmount)
        repo.setBudget(f.cb, f.rent, 2_000_000)
        assertEquals(2_000_000L, d.snap { it.budgets.singleOrNull()?.monthlyAmount == 2_000_000L }.budgets.single().monthlyAmount)
        repo.setBudget(f.cb, f.rent, 0)
        assertTrue(d.snap { it.budgets.isEmpty() }.budgets.isEmpty())
    }

    @Test fun backupIncludesSchedulesAndBudgets() = runBlocking {
        val f = fixture()
        repo.saveRecurring(rent(f, LocalDate.of(2030, 1, 1)))
        repo.setBudget(f.cb, f.salary, 9_00_000)
        d.snap { it.recurring.size == 1 && it.budgets.size == 1 }
        val file = File(context().cacheDir, "p2.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), true).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb))
        d.snap { it.recurring.isEmpty() && it.budgets.isEmpty() }
        val decoded = d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow()
        assertEquals(1, decoded.manifest.recurring)
        d.backup.restore(decoded, file.name).getOrThrow()
        val s = d.snap { it.recurring.size == 1 && it.budgets.size == 1 }
        assertEquals(LocalDate.of(2030, 1, 1), s.recurring.single().startDate)
        assertEquals(9_00_000L, s.budgets.single().monthlyAmount)
    }

    @Test fun autoBackupKeepsOnlyNewestCopies() {
        val names = (1..7).map { AutoBackup.fileName(LocalDateTime.of(2026, 11, it, 9, 0)) } + listOf("Cashbook_backup_manual.cbk", "photo.jpg")
        val del = AutoBackup.toDelete(names.shuffled(), keep = 5)
        assertEquals(listOf(AutoBackup.fileName(LocalDateTime.of(2026, 11, 2, 9, 0)), AutoBackup.fileName(LocalDateTime.of(2026, 11, 1, 9, 0))), del)
        assertTrue(AutoBackup.toDelete(names, 0).size == 6) // always keeps at least one
    }
}
