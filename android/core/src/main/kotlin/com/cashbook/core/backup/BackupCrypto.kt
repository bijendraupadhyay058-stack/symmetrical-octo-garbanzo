package com.cashbook.core.backup

import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.EOFException
import java.io.FilterOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.security.SecureRandom
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

class BackupException(val reason: Reason, cause: Throwable? = null) : Exception(reason.name, cause) {
    enum class Reason { NOT_A_BACKUP, UNSUPPORTED_VERSION, WRONG_PASSWORD_OR_DAMAGED, TRUNCATED, INVALID_DATA, WEAK_PASSWORD }
}

/**
 * Password-based streaming encryption for backup files.
 *
 * File layout:
 * ```
 * "CBKP" | version:u8 | iterations:i32 | salt[16] | noncePrefix[8]          (header, 33 bytes)
 * { lengthAndFlag:i32 | AES-256-GCM ciphertext+tag }*                        (chunks)
 * ```
 * Each chunk holds up to 64 KiB of plaintext, uses nonce = noncePrefix ‖ chunkIndex and
 * authenticates (header ‖ chunkIndex ‖ finalFlag) as associated data. The high bit of the
 * length marks the final chunk, so truncation, reordering and tampering are all detected.
 * The key is derived with PBKDF2-HMAC-SHA256.
 */
object BackupCrypto {
    private val MAGIC = byteArrayOf('C'.code.toByte(), 'B'.code.toByte(), 'K'.code.toByte(), 'P'.code.toByte())
    private const val VERSION: Byte = 1
    const val DEFAULT_ITERATIONS = 150_000
    private const val CHUNK = 64 * 1024
    private const val TAG_BITS = 128
    private const val FINAL_FLAG = 0x80000000.toInt()
    const val MIN_PASSWORD_LENGTH = 6

    fun deriveKey(password: CharArray, salt: ByteArray, iterations: Int): SecretKeySpec {
        val spec = PBEKeySpec(password, salt, iterations, 256)
        val bytes = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
        spec.clearPassword()
        return SecretKeySpec(bytes, "AES")
    }

    fun encrypt(out: OutputStream, password: CharArray, iterations: Int = DEFAULT_ITERATIONS): OutputStream {
        if (password.size < MIN_PASSWORD_LENGTH) throw BackupException(BackupException.Reason.WEAK_PASSWORD)
        val rnd = SecureRandom()
        val salt = ByteArray(16).also(rnd::nextBytes)
        val prefix = ByteArray(8).also(rnd::nextBytes)
        val header = ByteBuffer.allocate(33).put(MAGIC).put(VERSION).putInt(iterations).put(salt).put(prefix).array()
        out.write(header)
        return EncryptingStream(out, deriveKey(password, salt, iterations), header, prefix)
    }

    /** Returns a stream of decrypted bytes. Fails with [BackupException] on any problem. */
    fun decrypt(input: InputStream, password: CharArray): InputStream {
        val din = DataInputStream(input)
        val header = ByteArray(33)
        try { din.readFully(header) } catch (e: EOFException) { throw BackupException(BackupException.Reason.NOT_A_BACKUP, e) }
        val bb = ByteBuffer.wrap(header)
        val magic = ByteArray(4).also { bb.get(it) }
        if (!magic.contentEquals(MAGIC)) throw BackupException(BackupException.Reason.NOT_A_BACKUP)
        val version = bb.get()
        if (version != VERSION) throw BackupException(BackupException.Reason.UNSUPPORTED_VERSION)
        val iterations = bb.int
        if (iterations !in 10_000..5_000_000) throw BackupException(BackupException.Reason.NOT_A_BACKUP)
        val salt = ByteArray(16).also { bb.get(it) }
        val prefix = ByteArray(8).also { bb.get(it) }
        return DecryptingStream(din, deriveKey(password, salt, iterations), header, prefix)
    }

    private fun nonce(prefix: ByteArray, index: Int) = ByteBuffer.allocate(12).put(prefix).putInt(index).array()
    private fun aad(header: ByteArray, index: Int, final: Boolean) =
        ByteBuffer.allocate(header.size + 5).put(header).putInt(index).put(if (final) 1 else 0).array()

    private class EncryptingStream(
        out: OutputStream, private val key: SecretKeySpec, private val header: ByteArray, private val prefix: ByteArray,
    ) : FilterOutputStream(out) {
        private val buf = ByteArrayOutputStream(CHUNK)
        private var index = 0
        private var closed = false

        override fun write(b: Int) { buf.write(b); if (buf.size() >= CHUNK) emit(false) }
        override fun write(b: ByteArray, off: Int, len: Int) {
            var o = off; var remaining = len
            while (remaining > 0) {
                val n = minOf(remaining, CHUNK - buf.size())
                buf.write(b, o, n); o += n; remaining -= n
                if (buf.size() >= CHUNK) emit(false)
            }
        }

        private fun emit(final: Boolean) {
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(TAG_BITS, nonce(prefix, index)))
            c.updateAAD(aad(header, index, final))
            val ct = c.doFinal(buf.toByteArray())
            out.write(ByteBuffer.allocate(4).putInt(if (final) ct.size or FINAL_FLAG else ct.size).array())
            out.write(ct)
            buf.reset()
            index++
        }

        override fun flush() = out.flush()
        override fun close() {
            if (closed) return
            closed = true
            emit(true)
            out.flush()
            out.close()
        }
    }

    private class DecryptingStream(
        private val din: DataInputStream, private val key: SecretKeySpec, private val header: ByteArray, private val prefix: ByteArray,
    ) : InputStream() {
        private var plain = ByteArray(0)
        private var pos = 0
        private var index = 0
        private var finished = false

        private fun fill(): Boolean {
            while (pos >= plain.size) {
                if (finished) return false
                val raw = try { din.readInt() } catch (e: EOFException) { throw BackupException(BackupException.Reason.TRUNCATED, e) }
                val final = raw and FINAL_FLAG != 0
                val len = raw and FINAL_FLAG.inv()
                if (len < 16 || len > CHUNK + 16) throw BackupException(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED)
                val ct = ByteArray(len)
                try { din.readFully(ct) } catch (e: EOFException) { throw BackupException(BackupException.Reason.TRUNCATED, e) }
                val c = Cipher.getInstance("AES/GCM/NoPadding")
                c.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, nonce(prefix, index)))
                c.updateAAD(aad(header, index, final))
                plain = try { c.doFinal(ct) } catch (e: AEADBadTagException) {
                    throw BackupException(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED, e)
                } catch (e: javax.crypto.BadPaddingException) {
                    throw BackupException(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED, e)
                }
                pos = 0
                index++
                if (final) {
                    finished = true
                    if (din.read() != -1) throw BackupException(BackupException.Reason.WRONG_PASSWORD_OR_DAMAGED)
                }
            }
            return true
        }

        override fun read(): Int = if (!fill()) -1 else plain[pos++].toInt() and 0xff
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (len == 0) return 0
            if (!fill()) return -1
            val n = minOf(len, plain.size - pos)
            System.arraycopy(plain, pos, b, off, n)
            pos += n
            return n
        }
        override fun close() = din.close()
    }
}
