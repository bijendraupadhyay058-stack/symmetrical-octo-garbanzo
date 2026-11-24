package com.cashbook.app

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.data.SettingsRepository
import com.cashbook.app.data.Snapshot
import com.cashbook.app.data.db.AppDatabase
import com.cashbook.app.data.security.SecureStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import javax.crypto.spec.SecretKeySpec

/**
 * Test application: same wiring as production, except the Keystore key is replaced by a fixed
 * key and the database is in-memory Room without SQLCipher (neither exists on the JVM).
 */
class TestApp : CashbookApp() {
    override fun createContainer() = AppContainer(this, SecureStore(this) { SecretKeySpec(ByteArray(32) { 7 }, "AES") },
        SettingsRepository(this, "settings-" + java.util.UUID.randomUUID())) { ctx, _ ->
        Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java).build()
    }
    override fun scheduleWork() {}
}

fun app(): TestApp = ApplicationProvider.getApplicationContext()
fun context(): Context = ApplicationProvider.getApplicationContext()
fun deps(): Dependencies = runBlocking { app().container.awaitReady()!! }

suspend fun Dependencies.snap(timeoutMs: Long = 10_000, pred: (Snapshot) -> Boolean): Snapshot =
    // a predicate like `it.quotations.single().cancelled` throws on a snapshot taken before the change landed: keep waiting
    withTimeout(timeoutMs) { ledger.snapshot.first { it.loaded && runCatching { pred(it) }.getOrDefault(false) } }

val SAMPLE_NAMES = LedgerRepository.SampleNames("Office Cashbook", "Sample", "Office Cash", "SBI Bank",
    "Professional fees received", "Office stationery", "Internet bill", "SBI Bank to Office Cash")
