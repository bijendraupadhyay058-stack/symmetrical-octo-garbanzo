package com.cashbook.app

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.AttachmentStore
import com.cashbook.app.data.Snapshot
import com.cashbook.core.TxnType
import com.cashbook.core.backup.BackupException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Backup → change data → restore, plus every failure path must leave current data untouched. */
@RunWith(AndroidJUnit4::class)
class BackupRestoreTest {
    private val d = deps()
    private val pw = "correct horse"

    private fun fingerprint(s: Snapshot) = listOf(s.cashbooks.map { it.name }.sorted(), s.accounts.map { it.name to it.openingBalance }.sortedBy { it.first },
        s.txns.map { Triple(it.description, it.amount, it.type) }.sortedBy { it.first }, s.deleted.size, s.attachmentCounts.values.sum())

    private fun seed(): Snapshot = runBlocking {
        d.ledger.addSampleData("en", SAMPLE_NAMES)
        val s = d.snap { it.txns.size == 4 }
        val t = s.txns.first { it.type == TxnType.INCOME }
        d.attachments.file("r1.jpg").writeBytes(ByteArray(5000) { (it % 251).toByte() })
        d.ledger.saveTxn(t, listOf(AttachmentStore.Imported("r1.jpg", "receipt.jpg", "image/jpeg", 5000)), emptyList())
        d.ledger.deleteTxn(s.txns.first { it.type == TxnType.EXPENSE }.id) // recycle-bin entries are backed up too
        d.snap { it.attachmentCounts.isNotEmpty() && it.deleted.size == 1 }
    }

    private fun backupFile(name: String = "test.cbk") = File(context().cacheDir, name).also { it.delete() }

    @Test fun backupAndRestoreRoundTripWithAttachments() = runBlocking {
        val before = fingerprint(seed())
        val file = backupFile()
        assertTrue(d.backup.createBackup(Uri.fromFile(file), pw.toCharArray(), includeAttachments = true).isSuccess)
        assertTrue(file.length() > 0)
        assertTrue(d.settings.settings.first().lastBackupAt > 0)
        // change the data
        val s = d.snap { true }
        d.ledger.deleteCashbooks(s.cashbooks.map { it.id })
        d.snap { it.cashbooks.isEmpty() }
        assertTrue(!d.attachments.file("r1.jpg").exists())
        // inspect then restore
        val decoded = d.backup.inspect(Uri.fromFile(file), pw.toCharArray()).getOrThrow()
        assertEquals(1, decoded.manifest.cashbooks)
        assertEquals(4, decoded.manifest.transactions)
        assertTrue(decoded.manifest.includesAttachments)
        assertTrue(d.backup.restore(decoded, file.name).isSuccess)
        val after = d.snap { it.cashbooks.isNotEmpty() && it.attachmentCounts.isNotEmpty() }
        assertEquals(before, fingerprint(after))
        assertArrayEquals(ByteArray(5000) { (it % 251).toByte() }, d.attachments.file("r1.jpg").readBytes())
    }

    @Test fun restoreWithoutAttachments() = runBlocking {
        seed()
        val file = backupFile("noatt.cbk")
        assertTrue(d.backup.createBackup(Uri.fromFile(file), pw.toCharArray(), includeAttachments = false).isSuccess)
        val decoded = d.backup.inspect(Uri.fromFile(file), pw.toCharArray()).getOrThrow()
        assertTrue(!decoded.manifest.includesAttachments)
        assertTrue(d.backup.restore(decoded, file.name).isSuccess)
        val after = d.snap { it.attachmentCounts.isEmpty() }
        assertEquals(3, after.txns.size)
    }

    @Test fun wrongPasswordDamagedOrForeignFilesLeaveDataUntouched() = runBlocking {
        val before = fingerprint(seed())
        val file = backupFile()
        d.backup.createBackup(Uri.fromFile(file), pw.toCharArray(), true).getOrThrow()

        val wrong = d.backup.inspect(Uri.fromFile(file), "wrong password".toCharArray())
        assertEquals(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED, (wrong.exceptionOrNull() as BackupException).reason)

        val damaged = backupFile("damaged.cbk").apply { writeBytes(file.readBytes().also { it[it.size / 2] = (it[it.size / 2] + 1).toByte() }) }
        assertTrue(d.backup.inspect(Uri.fromFile(damaged), pw.toCharArray()).isFailure)

        val truncated = backupFile("short.cbk").apply { writeBytes(file.readBytes().copyOf(file.length().toInt() - 40)) }
        assertTrue(d.backup.inspect(Uri.fromFile(truncated), pw.toCharArray()).isFailure)

        val foreign = backupFile("photo.jpg").apply { writeText("not a backup at all, just some text") }
        assertEquals(BackupException.Reason.NOT_A_BACKUP, (d.backup.inspect(Uri.fromFile(foreign), pw.toCharArray()).exceptionOrNull() as BackupException).reason)

        assertEquals(before, fingerprint(d.snap { true }))
        assertTrue(d.attachments.file("r1.jpg").exists())
    }
}
