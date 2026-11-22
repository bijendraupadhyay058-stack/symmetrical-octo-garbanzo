package com.cashbook.core.backup

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import kotlin.random.Random

class BackupCodecTest {
    private val pw = "secret-123".toCharArray()
    private val iterations = 10_000 // fast for tests

    private val data = BackupData(
        cashbooks = listOf(CashbookDto(1, "Office", openingDate = 20544, createdAt = 1, updatedAt = 1)),
        accounts = listOf(
            AccountDto(1, 1, "Cash", "CASH", 1_000_000, 20544, createdAt = 1, updatedAt = 1),
            AccountDto(2, 1, "SBI", "BANK", 5_000_000, 20544, createdAt = 1, updatedAt = 1),
        ),
        categories = listOf(CategoryDto(1, "INCOME", "Fees", createdAt = 1, updatedAt = 1)),
        parties = emptyList(),
        transactions = listOf(
            TransactionDto(1, 1, "INCOME", 20545, 1_500_000, 2, categoryId = 1, paymentMode = "UPI", createdAt = 1, updatedAt = 1),
            TransactionDto(2, 1, "TRANSFER", 20546, 500_000, 2, toAccountId = 1, paymentMode = "OTHER", createdAt = 2, updatedAt = 2),
        ),
        attachments = listOf(AttachmentDto(1, 1, "bill.pdf", "application/pdf", 3, "a1.pdf", 1)),
    )
    private val manifest = BackupManifest(appVersion = "1.0", createdAt = 99, cashbooks = 1, accounts = 2, categories = 1, parties = 0,
        transactions = 2, attachments = 1, includesAttachments = true)

    private fun backup(attachment: ByteArray = byteArrayOf(1, 2, 3)): ByteArray {
        val out = ByteArrayOutputStream()
        BackupCodec.write(out, pw, manifest, data, listOf(AttachmentSource("a1.pdf") { ByteArrayInputStream(attachment) }), iterations)
        return out.toByteArray()
    }

    @Test fun roundTripWithAttachments() {
        val big = Random(1).nextBytes(300_000) // spans several encrypted chunks
        val files = HashMap<String, ByteArray>()
        val decoded = BackupCodec.read(ByteArrayInputStream(backup(big)), pw) { n, s -> files[n] = s.readBytes() }
        assertEquals(data, decoded.data)
        assertEquals(manifest, decoded.manifest)
        assertArrayEquals(big, files["a1.pdf"])
    }

    @Test fun wrongPasswordIsRejected() = expect(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED) {
        BackupCodec.read(ByteArrayInputStream(backup()), "wrong-pass".toCharArray()) { _, _ -> }
    }

    @Test fun damagedFileIsRejected() = expect(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED) {
        val b = backup(); b[b.size / 2] = (b[b.size / 2].toInt() xor 0x40).toByte()
        BackupCodec.read(ByteArrayInputStream(b), pw) { _, _ -> }
    }

    @Test fun truncatedFileIsRejected() {
        val b = backup(Random(2).nextBytes(200_000))
        try {
            BackupCodec.read(ByteArrayInputStream(b.copyOf(b.size - 100)), pw) { _, _ -> }
            fail()
        } catch (e: BackupException) {
            assertTrue(e.reason == BackupException.Reason.TRUNCATED || e.reason == BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED)
        }
    }

    @Test fun randomFileIsNotABackup() = expect(BackupException.Reason.NOT_A_BACKUP) {
        BackupCodec.read(ByteArrayInputStream("hello world, this is not a backup file!".toByteArray()), pw) { _, _ -> }
    }

    @Test fun shortPasswordRefused() = expect(BackupException.Reason.WEAK_PASSWORD) {
        BackupCodec.write(ByteArrayOutputStream(), "123".toCharArray(), manifest, data, emptyList())
    }

    @Test fun recurringAndBudgetsRoundTripAndValidate() {
        val full = data.copy(
            recurring = listOf(RecurringDto(1, 1, "EXPENSE", 250_000, 1, categoryId = 1, paymentMode = "CASH", frequency = "MONTHLY", startDate = 20544, createdAt = 1, updatedAt = 1)),
            budgets = listOf(BudgetDto(1, 1, 1, 500_000, 1, 1)),
        )
        assertTrue(BackupCodec.validate(full).isEmpty())
        val out = ByteArrayOutputStream()
        BackupCodec.write(out, pw, manifest, full, emptyList(), iterations)
        assertEquals(full, BackupCodec.read(ByteArrayInputStream(out.toByteArray()), pw) { _, _ -> }.data)
        val bad = full.copy(recurring = listOf(full.recurring[0].copy(frequency = "HOURLY", accountId = 99)), budgets = full.budgets + full.budgets[0].copy(id = 2))
        assertEquals(3, BackupCodec.validate(bad).size)
    }

    @Test fun version10BackupJsonStillDecodes() {
        // data.json written by app 1.0 has no "recurring"/"budgets" keys
        val json = BackupCodec.json.encodeToString(BackupData.serializer(), data).replace(",\"recurring\":[]", "").replace(",\"budgets\":[]", "")
        assertTrue(!json.contains("recurring"))
        assertEquals(data, BackupCodec.json.decodeFromString(BackupData.serializer(), json))
    }

    @Test fun validationFindsBrokenReferences() {
        val bad = data.copy(transactions = data.transactions + TransactionDto(3, 1, "TRANSFER", 1, 5, 1, toAccountId = 1, paymentMode = "CASH", createdAt = 1, updatedAt = 1))
        assertTrue(BackupCodec.validate(bad).any { it.contains("destination") })
        val bad2 = data.copy(transactions = listOf(data.transactions[0].copy(amount = 0, accountId = 77)))
        assertEquals(2, BackupCodec.validate(bad2).size)
        assertTrue(BackupCodec.validate(data).isEmpty())
    }

    private fun expect(reason: BackupException.Reason, block: () -> Unit) {
        try { block(); fail("expected $reason") } catch (e: BackupException) { assertEquals(reason, e.reason) }
    }
}
