package com.cashbook.app.data.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec

/**
 * Small encrypted key/value file for sensitive values (database key, PIN hash).
 * The file is encrypted with AES-256-GCM using a non-exportable key in the Android Keystore,
 * so its contents are useless if copied off the device.
 */
class SecureStore(context: Context, private val keyProvider: (() -> SecretKey)? = null) {
    private val file = File(context.noBackupFilesDir, "secure_store.bin")
    private val lock = Any()

    private fun masterKey(): SecretKey {
        keyProvider?.let { return it() }
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build())
        return gen.generateKey()
    }

    private fun readAll(): JSONObject = synchronized(lock) {
        if (!file.exists()) return JSONObject()
        val bytes = file.readBytes()
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, masterKey(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        JSONObject(String(c.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8))
    }

    private fun writeAll(obj: JSONObject) = synchronized(lock) {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, masterKey())
        val out = c.iv + c.doFinal(obj.toString().toByteArray(Charsets.UTF_8))
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeBytes(out)
        if (!tmp.renameTo(file)) { file.delete(); tmp.renameTo(file) }
    }

    private fun get(key: String): String? = readAll().optString(key, "").ifEmpty { null }
    private fun put(key: String, value: String?) = synchronized(lock) {
        val o = readAll(); if (value == null) o.remove(key) else o.put(key, value); writeAll(o)
    }

    /** 32-byte random database passphrase, created on first use. */
    fun databaseKey(): ByteArray = synchronized(lock) {
        get(K_DB)?.let { return Base64.decode(it, Base64.NO_WRAP) }
        val key = ByteArray(32).also { SecureRandom().nextBytes(it) }
        put(K_DB, Base64.encodeToString(key, Base64.NO_WRAP))
        key
    }

    val hasPin: Boolean get() = get(K_PIN_HASH) != null

    fun setPin(pin: String) {
        val salt = ByteArray(16).also { SecureRandom().nextBytes(it) }
        synchronized(lock) {
            val o = readAll()
            o.put(K_PIN_SALT, Base64.encodeToString(salt, Base64.NO_WRAP))
            o.put(K_PIN_HASH, Base64.encodeToString(hash(pin, salt), Base64.NO_WRAP))
            o.put(K_PIN_LEN, pin.length.toString())
            writeAll(o)
        }
    }

    fun verifyPin(pin: String): Boolean {
        val o = readAll()
        val salt = o.optString(K_PIN_SALT, "").ifEmpty { return false }
        val expected = o.optString(K_PIN_HASH, "").ifEmpty { return false }
        return MessageDigest.isEqual(hash(pin, Base64.decode(salt, Base64.NO_WRAP)), Base64.decode(expected, Base64.NO_WRAP))
    }

    fun clearPin() = synchronized(lock) {
        val o = readAll(); o.remove(K_PIN_HASH); o.remove(K_PIN_SALT); o.remove(K_PIN_LEN); writeAll(o)
    }

    /** Number of digits in the PIN (stored encrypted) so the lock screen knows when to check it. */
    val pinLength: Int get() = get(K_PIN_LEN)?.toIntOrNull() ?: 0

    /** Password used for automatic backups (kept only in this encrypted store, never in plain settings). */
    fun autoBackupPassword(): String? = get(K_AB_PASSWORD)
    fun setAutoBackupPassword(password: String?) = put(K_AB_PASSWORD, password)

    private fun hash(pin: String, salt: ByteArray): ByteArray {
        val spec = PBEKeySpec(pin.toCharArray(), salt, 60_000, 256)
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
    }

    companion object {
        private const val ALIAS = "cashbook_master_key"
        private const val K_DB = "db_key"
        private const val K_PIN_HASH = "pin_hash"
        private const val K_PIN_SALT = "pin_salt"
        private const val K_PIN_LEN = "pin_len"
        private const val K_AB_PASSWORD = "auto_backup_password"
    }
}
