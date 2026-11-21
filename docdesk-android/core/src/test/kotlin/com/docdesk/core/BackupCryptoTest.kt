package com.docdesk.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class BackupCryptoTest {
    @Test fun roundTripAndWrongPassword() {
        val pkg = BackupPackage.write("""{"format":"docdesk-backup","clients":[{"name":"Sharma Traders"}]}""",
            listOf("GSTR-3B.pdf" to { "PDFDATA".byteInputStream() }, "GSTR-3B.pdf" to { "OTHER".byteInputStream() }, "../evil.txt" to { "x".byteInputStream() }))
        val enc = BackupCrypto.encrypt(pkg, "correct horse".toCharArray())
        assertTrue(BackupCrypto.isBackup(enc))
        // Encrypted: neither client names nor file contents are readable.
        val asText = String(enc, Charsets.ISO_8859_1)
        assertFalse(asText.contains("Sharma") || asText.contains("PDFDATA") || asText.contains("GSTR"))
        val dec = BackupCrypto.decrypt(enc, "correct horse".toCharArray())
        assertArrayEquals(pkg, dec)
        val files = linkedMapOf<String, String>()
        val json = BackupPackage.read(dec) { n, s -> files[n] = s.readBytes().decodeToString() }
        assertTrue(json.contains("Sharma Traders"))
        assertEquals(mapOf("GSTR-3B.pdf" to "PDFDATA", "GSTR-3B (2).pdf" to "OTHER", "_evil.txt" to "x"), files)
        try { BackupCrypto.decrypt(enc, "wrong password".toCharArray()); fail() } catch (e: WrongBackupPasswordException) { }
        // Tampering is detected.
        val bad = enc.copyOf().also { it[it.size - 5] = (it[it.size - 5] + 1).toByte() }
        try { BackupCrypto.decrypt(bad, "correct horse".toCharArray()); fail() } catch (e: WrongBackupPasswordException) { }
        try { BackupCrypto.decrypt("hello".toByteArray(), "x".toCharArray()); fail() } catch (e: NotABackupException) { }
    }

    @Test fun derivedKeyMatchesPassword() {
        val salt = BackupCrypto.newSalt()
        val key = BackupCrypto.deriveKey("my backup pw".toCharArray(), salt)
        val enc = BackupCrypto.encrypt("data".toByteArray(), key, salt)
        assertEquals("data", BackupCrypto.decrypt(enc, "my backup pw".toCharArray()).decodeToString())
        assertNotNull(BackupCrypto.passwordProblem("short"))
        assertNull(BackupCrypto.passwordProblem("long enough"))
    }
}
