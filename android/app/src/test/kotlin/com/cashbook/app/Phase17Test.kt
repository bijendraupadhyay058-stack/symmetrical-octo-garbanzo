package com.cashbook.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.AppSettings
import com.cashbook.app.ui.dashboard.StartStep
import com.cashbook.app.ui.dashboard.gettingStarted
import com.cashbook.app.ui.dashboard.releasesSince
import com.cashbook.core.AccountType
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate

/** Getting-started steps and "What's new". */
@RunWith(AndroidJUnit4::class)
class Phase17Test {
    private val d = deps()

    @Test fun stepsFollowTheData(): Unit = runBlocking {
        val sample = d.ledger.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val none = gettingStarted(s, AppSettings(), "")
        assertTrue(none.values.none { it })                                    // sample entries don't count
        val real = d.ledger.createCashbook("My shop", "", LocalDate.now(), listOf(com.cashbook.app.data.LedgerRepository.NewAccount("Cash", AccountType.CASH, 0, LocalDate.now())))
        s = d.snap { it.cashbooks.size == 2 }
        val acc = s.accounts.first { it.cashbookId == real }
        d.ledger.saveTxn(Txn(0, real, TxnType.EXPENSE, LocalDate.now(), 5_000, acc.id, description = "Tea"), emptyList(), emptyList())
        s = d.snap { it.txns.size == 5 }
        val some = gettingStarted(s, AppSettings(lockEnabled = true, autoBackupEnabled = true, seenReports = true), "Sharma & Associates")
        assertEquals(listOf(StartStep.FIRST_ENTRY, StartStep.BUSINESS_PROFILE, StartStep.APP_LOCK, StartStep.BACKUP, StartStep.REPORT),
            some.filterValues { it }.keys.toList())
        assertEquals(false, some[StartStep.INVOICE])
        assertTrue(sample != real)
    }

    @Test fun whatsNewOnlyAfterAnUpdate() {
        assertTrue(releasesSince(0, onboarded = false, current = 18).isEmpty())          // fresh install (still onboarding)
        assertEquals(listOf("1.17"), releasesSince(0, onboarded = true, current = 18).map { it.name })   // updated from 1.16
        assertEquals(listOf("1.17"), releasesSince(17, onboarded = true, current = 18).map { it.name })
        assertTrue(releasesSince(18, onboarded = true, current = 18).isEmpty())          // already seen
        assertEquals(listOf("1.16", "1.17"), releasesSince(16, onboarded = true, current = 18).map { it.name })
        assertEquals(listOf("1.18"), releasesSince(18, onboarded = true, current = 19).map { it.name })
    }
}
