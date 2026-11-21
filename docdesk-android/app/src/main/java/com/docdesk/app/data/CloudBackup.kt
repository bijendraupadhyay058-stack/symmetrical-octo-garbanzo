package com.docdesk.app.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.docdesk.app.DocDeskApp
import com.docdesk.core.BackupCrypto
import com.docdesk.core.BackupPackage
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

enum class BackupFrequency(val label: String, val days: Long) { OFF("Off", 0), DAILY("Every day", 1), WEEKLY("Every week", 7) }

/**
 * Encrypted backups to a location the user picks with Android's file picker – a cloud app such as
 * Google Drive, OneDrive or Dropbox, or the phone. DocDesk itself makes no internet connection: the
 * chosen cloud app uploads the file. Everything is encrypted (AES-256-GCM, key from the user's password)
 * before it leaves DocDesk.
 *
 * Automatic backups keep the *derived key* (never the password) wrapped by a key in the Android
 * Keystore, which can't be exported from the device. These settings are kept outside the normal
 * settings so they are never copied into a backup.
 */
object CloudBackup {
    private const val PREFS = "cloud_backup"
    private const val KEY_ALIAS = "docdesk_backup_key_wrap"
    private const val WORK = "cloud-backup"

    data class Config(val uri: Uri?, val fileName: String?, val includeFiles: Boolean, val frequency: BackupFrequency, val lastTime: Long, val lastStatus: String, val hasKey: Boolean)

    data class Outcome(val bytes: Long, val documents: Int)
    data class RestoreOutcome(val data: Backup.RestoreResult, val documentsRestored: Int)

    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun config(c: Context): Config = prefs(c).let { p ->
        Config(p.getString("uri", null)?.let(Uri::parse), p.getString("name", null), p.getBoolean("files", true),
            runCatching { BackupFrequency.valueOf(p.getString("freq", "OFF")!!) }.getOrDefault(BackupFrequency.OFF),
            p.getLong("last", 0), p.getString("status", "") ?: "", p.contains("key"))
    }

    /** Builds the backup: workspace + settings JSON and, if asked, the documents in My Files. */
    suspend fun build(app: DocDeskApp, includeFiles: Boolean): Pair<ByteArray, Int> {
        val json = Backup.export(app)
        val docs = if (includeFiles) app.files.listMyFiles() else emptyList()
        return BackupPackage.write(json, docs.map { f -> f.name to { f.file.inputStream() } }) to docs.size
    }

    private fun write(c: Context, uri: Uri, data: ByteArray) {
        val out = c.contentResolver.openOutputStream(uri, "wt") ?: c.contentResolver.openOutputStream(uri, "w") ?: throw com.docdesk.app.jobs.OperationFailed("The backup location can't be written.")
        out.use { it.write(data) }
    }

    fun displayName(c: Context, uri: Uri): String? = runCatching {
        c.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) it.getString(0) else null }
    }.getOrNull()

    /**
     * Backs up now to [uri] with [password]. If [frequency] isn't OFF, the location is remembered and
     * automatic backups are scheduled.
     */
    suspend fun backupNow(app: DocDeskApp, uri: Uri, password: CharArray, includeFiles: Boolean, frequency: BackupFrequency): Outcome {
        val (pkg, n) = build(app, includeFiles)
        val salt = BackupCrypto.newSalt()
        val key = BackupCrypto.deriveKey(password, salt)
        val enc = BackupCrypto.encrypt(pkg, key, salt)
        write(app, uri, enc)
        val p = prefs(app).edit()
        if (frequency != BackupFrequency.OFF) {
            runCatching { app.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION) }
            val wrapped = wrap(key + salt)
            p.putString("uri", uri.toString()).putString("name", displayName(app, uri)).putBoolean("files", includeFiles).putString("freq", frequency.name)
            if (wrapped != null) p.putString("key", wrapped) else p.remove("key")
        }
        key.fill(0)
        p.putLong("last", System.currentTimeMillis()).putString("status", "Backed up ${n} document(s), ${enc.size / 1024} KB").apply()
        schedule(app)
        return Outcome(enc.size.toLong(), n)
    }

    /** Automatic backup to the remembered location. Returns a status message. */
    suspend fun backupAutomatically(app: DocDeskApp): String {
        val cfg = config(app)
        val uri = cfg.uri ?: return "No backup location set"
        val keySalt = prefs(app).getString("key", null)?.let { unwrap(it) } ?: return "Backup key unavailable – back up manually once with your password".also { setStatus(app, it) }
        val key = keySalt.copyOfRange(0, 32); val salt = keySalt.copyOfRange(32, 48)
        return try {
            val (pkg, n) = build(app, cfg.includeFiles)
            val enc = BackupCrypto.encrypt(pkg, key, salt)
            write(app, uri, enc)
            "Backed up automatically: $n document(s), ${enc.size / 1024} KB".also { prefs(app).edit().putLong("last", System.currentTimeMillis()).putString("status", it).apply() }
        } catch (e: Exception) {
            "Automatic backup failed: ${e.message ?: "the location can't be written"} – choose the location again".also { setStatus(app, it) }
        } finally { key.fill(0); keySalt.fill(0) }
    }

    private fun setStatus(c: Context, s: String) = prefs(c).edit().putString("status", s).apply()

    fun setFrequency(app: DocDeskApp, f: BackupFrequency) {
        prefs(app).edit().putString("freq", f.name).apply()
        if (f == BackupFrequency.OFF) forget(app, keepLocation = true) else schedule(app)
    }

    /** Stops automatic backups and removes the stored key (and, unless [keepLocation], the location). */
    fun forget(app: DocDeskApp, keepLocation: Boolean = false) {
        val p = prefs(app).edit().remove("key").putString("freq", BackupFrequency.OFF.name)
        if (!keepLocation) {
            config(app).uri?.let { u -> runCatching { app.contentResolver.releasePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION) } }
            p.remove("uri").remove("name")
        }
        p.apply()
        runCatching { WorkManager.getInstance(app).cancelUniqueWork(WORK) }
    }

    fun schedule(app: DocDeskApp) {
        val cfg = config(app)
        val wm = runCatching { WorkManager.getInstance(app) }.getOrNull() ?: return
        if (cfg.frequency == BackupFrequency.OFF || cfg.uri == null || !cfg.hasKey) { wm.cancelUniqueWork(WORK); return }
        wm.enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.UPDATE,
            PeriodicWorkRequestBuilder<CloudBackupWorker>(cfg.frequency.days, TimeUnit.DAYS)
                .setConstraints(Constraints.Builder().setRequiresBatteryNotLow(true).setRequiresStorageNotLow(true).build()).build())
    }

    /** Reads an encrypted (.ddbk) or older unencrypted (.json) backup and restores it. Documents are added to My Files without overwriting. */
    suspend fun restore(app: DocDeskApp, data: ByteArray, password: CharArray?): RestoreOutcome {
        if (!BackupCrypto.isBackup(data)) return RestoreOutcome(Backup.restore(app, data.toString(Charsets.UTF_8)), 0)
        val plain = BackupCrypto.decrypt(data, password ?: CharArray(0))
        var n = 0
        val json = BackupPackage.read(plain) { name, stream ->
            val target = FileRepository.unique(app.files.myFilesDir, FileRepository.sanitize(name))
            target.outputStream().use { stream.copyTo(it) }; n++
        }
        return RestoreOutcome(Backup.restore(app, json), n)
    }

    // --- Android Keystore wrapping of the derived key (for automatic backups) ---

    private fun keystoreKey(): SecretKey? = runCatching {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(KEY_ALIAS, null) as? SecretKey) ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        }.generateKey()
    }.getOrNull()

    private fun wrap(secret: ByteArray): String? {
        val k = keystoreKey() ?: return null
        return runCatching {
            val c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.ENCRYPT_MODE, k)
            Base64.encodeToString(c.iv + c.doFinal(secret), Base64.NO_WRAP)
        }.getOrNull()
    }

    private fun unwrap(s: String): ByteArray? {
        val k = keystoreKey() ?: return null
        return runCatching {
            val b = Base64.decode(s, Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.DECRYPT_MODE, k, GCMParameterSpec(128, b.copyOfRange(0, 12)))
            c.doFinal(b, 12, b.size - 12)
        }.getOrNull()
    }
}

class CloudBackupWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as DocDeskApp
        val msg = CloudBackup.backupAutomatically(app)
        return when {
            msg.startsWith("Backed up") -> Result.success()
            msg.startsWith("No backup location") || msg.contains("key unavailable") -> Result.failure() // needs the user; shown in Settings
            else -> Result.retry() // e.g. cloud app temporarily unavailable
        }
    }
}
