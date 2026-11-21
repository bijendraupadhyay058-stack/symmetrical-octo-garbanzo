package com.docdesk.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.security.SecureRandom
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

class WrongBackupPasswordException : Exception("The password is wrong, or the backup file is damaged.")
class NotABackupException : Exception("This file is not a DocDesk encrypted backup.")

/**
 * Encrypted backup file format (.ddbk):
 *   "DDBK" | version (1 byte) | PBKDF2 iterations (4 bytes) | salt (16) | IV (12) | AES-256-GCM ciphertext+tag
 * The key is derived from the user's password with PBKDF2-HMAC-SHA256. The password is never stored in
 * the file; without it the backup can't be read (also not by DocDesk).
 */
object BackupCrypto {
    private val MAGIC = "DDBK".toByteArray()
    private const val VERSION: Byte = 1
    const val ITERATIONS = 210_000
    const val MIN_PASSWORD = 8
    private val random = SecureRandom()

    fun newSalt(): ByteArray = ByteArray(16).also { random.nextBytes(it) }

    fun deriveKey(password: CharArray, salt: ByteArray, iterations: Int = ITERATIONS): ByteArray {
        val spec = PBEKeySpec(password, salt, iterations, 256)
        try { return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded } finally { spec.clearPassword() }
    }

    /** Encrypts with an already-derived [key] (used for automatic backups so the password isn't kept). */
    fun encrypt(plain: ByteArray, key: ByteArray, salt: ByteArray, iterations: Int = ITERATIONS): ByteArray {
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        val header = ByteArrayOutputStream().apply {
            write(MAGIC); write(VERSION.toInt())
            write(byteArrayOf((iterations ushr 24).toByte(), (iterations ushr 16).toByte(), (iterations ushr 8).toByte(), iterations.toByte()))
            write(salt); write(iv)
        }.toByteArray()
        c.updateAAD(header) // the header can't be altered without detection
        return header + c.doFinal(plain)
    }

    fun encrypt(plain: ByteArray, password: CharArray): ByteArray { val salt = newSalt(); return encrypt(plain, deriveKey(password, salt), salt) }

    fun isBackup(data: ByteArray) = data.size > 37 && data.copyOfRange(0, 4).contentEquals(MAGIC)

    fun decrypt(data: ByteArray, password: CharArray): ByteArray {
        if (!isBackup(data)) throw NotABackupException()
        if (data[4] != VERSION) throw NotABackupException()
        val iterations = ((data[5].toInt() and 0xff) shl 24) or ((data[6].toInt() and 0xff) shl 16) or ((data[7].toInt() and 0xff) shl 8) or (data[8].toInt() and 0xff)
        if (iterations !in 10_000..10_000_000) throw NotABackupException()
        val salt = data.copyOfRange(9, 25); val iv = data.copyOfRange(25, 37)
        val key = deriveKey(password, salt, iterations)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        c.updateAAD(data.copyOfRange(0, 37))
        return try { c.doFinal(data, 37, data.size - 37) } catch (e: AEADBadTagException) { throw WrongBackupPasswordException() }
    }

    /** Password rules: at least 8 characters. Returns a problem description or null. */
    fun passwordProblem(p: String): String? = when {
        p.length < MIN_PASSWORD -> "Use at least $MIN_PASSWORD characters."
        p.isBlank() -> "The password can't be only spaces."
        else -> null
    }
}

/** The (unencrypted) contents of a backup: the data JSON plus, optionally, document files. */
object BackupPackage {
    const val DATA = "docdesk-backup.json"
    const val FILES = "files/"

    /** Writes a ZIP with [json] and each (name, stream) document under files/. */
    fun write(json: String, files: List<Pair<String, () -> InputStream>>, out: OutputStream) {
        ZipOutputStream(out).use { z ->
            z.putNextEntry(ZipEntry(DATA)); z.write(json.toByteArray(Charsets.UTF_8)); z.closeEntry()
            val used = HashSet<String>()
            for ((name, open) in files) {
                var n = name.replace('\\', '_').replace('/', '_'); var k = 2
                while (!used.add(n)) n = name.substringBeforeLast('.', name) + " ($k)" + (if (name.contains('.')) "." + name.substringAfterLast('.') else "").also { k++ }
                z.putNextEntry(ZipEntry(FILES + n)); open().use { it.copyTo(z) }; z.closeEntry()
            }
        }
    }

    fun write(json: String, files: List<Pair<String, () -> InputStream>>): ByteArray = ByteArrayOutputStream().also { write(json, files, it) }.toByteArray()

    /**
     * Reads a package. [onFile] receives each document's safe file name and its stream.
     * Entry names with paths ("../") are reduced to their last part, so nothing is written outside the target folder.
     */
    fun read(data: ByteArray, onFile: (String, InputStream) -> Unit): String {
        var json: String? = null
        ZipInputStream(ByteArrayInputStream(data)).use { z ->
            while (true) {
                val e = z.nextEntry ?: break
                if (e.isDirectory) continue
                when {
                    e.name == DATA -> json = z.readBytes().toString(Charsets.UTF_8)
                    e.name.startsWith(FILES) -> {
                        val safe = e.name.substringAfterLast('/').substringAfterLast('\\').trim().trimStart('.')
                        if (safe.isNotEmpty()) onFile(safe, z)
                    }
                }
            }
        }
        return json ?: throw NotABackupException()
    }
}
