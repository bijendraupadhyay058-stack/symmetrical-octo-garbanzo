package com.cashbook.app

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.db.CategoryEntity
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.StatementLine
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Categories learned from imported statement lines. */
@RunWith(AndroidJUnit4::class)
class Phase14Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    @Test fun learnsAndAppliesCategories(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val bank = s.accounts.first { it.cashbookId == cb && it.type == AccountType.BANK }
        val charges = d.db.categories().insert(CategoryEntity(kind = "EXPENSE", name = "Bank charges", createdAt = 0, updatedAt = 0))
        val interest = d.db.categories().insert(CategoryEntity(kind = "INCOME", name = "Interest", createdAt = 0, updatedAt = 0))

        // May: added uncategorised, then the user sorts it out
        val may = repo.addStatementLine(bank.id, StatementLine(1, today.minusDays(30), "SMS CHARGES INCL GST 0525", "", -1_770))
        s = d.snap { it.txns.any { t -> t.id == may } }
        assertNull(s.txns.single { it.id == may }.categoryId)
        repo.saveTxn(s.txns.single { it.id == may }.copy(categoryId = charges), emptyList(), emptyList())
        s = d.snap { it.categoryRules.isNotEmpty() }
        assertEquals("SMS CHARGES INCL", s.categoryRules.single().key)
        assertEquals(charges, s.categoryRules.single().categoryId)

        // June: the same charge with a new date and number comes in already categorised
        val june = repo.addStatementLine(bank.id, StatementLine(2, today, "SMS CHARGES INCL GST 0625", "", -1_770))
        // an income line with that wording doesn't take an expense category
        val odd = repo.addStatementLine(bank.id, StatementLine(3, today, "SMS CHARGES INCL REVERSAL", "", 1_770))
        s = d.snap { it.txns.any { t -> t.id == odd } }
        assertEquals(charges, s.txns.single { it.id == june }.categoryId)
        assertNull(s.txns.single { it.id == odd }.categoryId)

        // re-categorising an already categorised entry doesn't change the rule; categorising another uncategorised one adds one
        repo.saveTxn(s.txns.single { it.id == june }.copy(categoryId = s.categories.first { it.kind == CategoryKind.EXPENSE && it.id != charges }.id), emptyList(), emptyList())
        val int1 = repo.addStatementLine(bank.id, StatementLine(4, today, "INT.PD:01-04-26 TO 30-06-26", "", 12_500))
        s = d.snap { it.txns.any { t -> t.id == int1 } }
        repo.saveTxn(s.txns.single { it.id == int1 }.copy(categoryId = interest), emptyList(), emptyList())
        s = d.snap { it.categoryRules.size == 2 }
        assertEquals(charges, s.categoryRules.first { it.key == "SMS CHARGES INCL" }.categoryId)
        assertEquals(interest, s.categoryRules.first { it.key == "INT PD TO" }.categoryId)

        // archived categories aren't applied; rules survive a backup; a deleted rule stops applying
        val file = File(context().cacheDir, "p14.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(cb)); d.db.reconcile().clearRules(); d.snap { it.categoryRules.isEmpty() }
        d.backup.restore(d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow(), file.name).getOrThrow()
        s = d.snap { it.categoryRules.size == 2 }
        repo.deleteCategoryRule(s.categoryRules.first { it.key == "INT PD TO" }.id)
        s = d.snap { it.categoryRules.size == 1 }
        val later = repo.addStatementLine(bank.id, StatementLine(5, today, "INT.PD:01-07-26 TO 30-09-26", "", 13_000))
        s = d.snap { it.txns.any { t -> t.id == later } }
        assertNull(s.txns.single { it.id == later }.categoryId)
        assertTrue(repo.ruleCategory("SMS CHARGES INCL GST 0725", com.cashbook.core.TxnType.EXPENSE) == charges)
    }
}
