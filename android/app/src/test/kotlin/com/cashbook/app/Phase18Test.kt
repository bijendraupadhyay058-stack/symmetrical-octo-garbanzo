package com.cashbook.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.Diagnostics
import com.cashbook.app.data.Diagnostics.DeviceCheck
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.HealthCheck.Check
import com.cashbook.core.Severity
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate

/** The app health check on a real (in-memory, encrypted-schema) database. */
@RunWith(AndroidJUnit4::class)
class Phase18Test {
    private val d = deps()

    @Test fun healthyBooksAndDeviceFindings(): Unit = runBlocking {
        val cb = d.ledger.addSampleData("en", SAMPLE_NAMES)
        val s = d.snap { it.txns.size == 4 }
        assertEquals("ok", d.ledger.integrityCheck())
        val settings = d.settings.settings.first().copy(autoBackupEnabled = true, autoBackupFolder = "content://gone/tree/x", autoBackupFolderName = "Old folder")
        val r = Diagnostics.run(context(), d, settings, s)
        val dev = r.device.associateBy { it.check }
        assertEquals(Severity.OK, dev[DeviceCheck.DATABASE]!!.severity)
        assertEquals(Severity.ERROR, dev[DeviceCheck.BACKUP_FOLDER]!!.severity)          // folder permission gone
        assertEquals(Severity.WARNING, dev[DeviceCheck.LAST_BACKUP]!!.severity)          // never backed up
        assertTrue(DeviceCheck.entries.all { it in dev.keys })
        assertTrue(r.ledger.filter { it.check != Check.NEGATIVE_BALANCE }.all { it.severity == Severity.OK })
        assertEquals(Severity.ERROR, r.worst)
        assertTrue(cb > 0)
    }

    @Test fun findsInconsistentData(): Unit = runBlocking {
        val cb = d.ledger.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        val expenseCat = s.categories.first { it.kind == CategoryKind.EXPENSE }.id
        // an income entry filed under an expense category (only possible via an old backup or a bug)
        d.db.transactions().insert(com.cashbook.app.data.db.TransactionEntity(cashbookId = cb, type = "INCOME", date = LocalDate.now().toEpochDay(), amount = 1_000,
            accountId = cash.id, categoryId = expenseCat, paymentMode = "CASH", description = "Odd income", createdAt = 0, updatedAt = 0))
        s = d.snap { it.txns.any { t -> t.description == "Odd income" } }
        val r = Diagnostics.run(context(), d, d.settings.settings.first(), s).ledger.associateBy { it.check }
        assertEquals(Severity.WARNING, r[Check.CATEGORY_KIND]!!.severity)
        assertEquals(1, r[Check.CATEGORY_KIND]!!.count)
        assertTrue(r[Check.CATEGORY_KIND]!!.examples.single().contains("Odd income"))
        assertTrue(Txn(0, cb, TxnType.INCOME, LocalDate.now(), 1, cash.id).amount == 1L)
    }
}
