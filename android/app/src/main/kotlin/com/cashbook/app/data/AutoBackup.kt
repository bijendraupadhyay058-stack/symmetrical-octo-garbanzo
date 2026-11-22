package com.cashbook.app.data

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * Scheduled backups into a folder the user picked once with the system folder picker
 * (device storage, SD card, or a cloud provider such as Google Drive). Uses the same encrypted
 * format as manual backups and keeps only the newest [AppSettings.autoBackupKeep] copies.
 */
class AutoBackup(
    private val context: Context,
    private val backup: BackupManager,
    private val settings: SettingsRepository,
    private val secure: com.cashbook.app.data.security.SecureStore,
) {
    sealed interface Result {
        data object NotDue : Result
        data object Done : Result
        data class Failed(val reason: String) : Result
    }

    suspend fun runIfDue(s: AppSettings, force: Boolean = false): Result {
        if (!s.autoBackupEnabled || s.autoBackupFolder.isBlank()) return Result.NotDue
        val due = s.lastAutoBackupAt + s.autoBackupEveryDays * DAY - HOUR // small tolerance for WorkManager timing
        if (!force && System.currentTimeMillis() < due) return Result.NotDue
        val password = secure.autoBackupPassword() ?: return fail("NO_PASSWORD")
        val tree = Uri.parse(s.autoBackupFolder)
        val hasPermission = context.contentResolver.persistedUriPermissions.any { it.uri == tree && it.isWritePermission }
        if (!hasPermission) return fail("NO_FOLDER_ACCESS")
        val doc = try {
            val parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
            DocumentsContract.createDocument(context.contentResolver, parent, "application/octet-stream", fileName(LocalDateTime.now()))
        } catch (e: Exception) { null } ?: return fail("CANNOT_CREATE_FILE")
        val r = backup.createBackup(doc, password.toCharArray(), s.autoBackupAttachments)
        if (r.isFailure) return fail("BACKUP_FAILED")
        settings.update { it.copy(lastAutoBackupAt = System.currentTimeMillis(), lastAutoBackupError = "") }
        prune(tree, s.autoBackupKeep)
        return Result.Done
    }

    private suspend fun fail(reason: String): Result {
        settings.update { it.copy(lastAutoBackupError = reason) }
        return Result.Failed(reason)
    }

    /** Deletes older automatic backups in the folder beyond [keep]. Manual backups are never touched. */
    private fun prune(tree: Uri, keep: Int) = runCatching {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val files = ArrayList<Pair<String, String>>() // (documentId, name)
        context.contentResolver.query(children, arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)?.use { c ->
            while (c.moveToNext()) files += c.getString(0) to (c.getString(1) ?: "")
        }
        val names = files.map { it.second }
        val delete = toDelete(names, keep).toSet()
        files.filter { it.second in delete }.forEach { (id, _) ->
            runCatching { DocumentsContract.deleteDocument(context.contentResolver, DocumentsContract.buildDocumentUriUsingTree(tree, id)) }
        }
    }

    companion object {
        const val PREFIX = "Cashbook_auto_"
        private const val DAY = 86_400_000L
        private const val HOUR = 3_600_000L
        private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd_HHmmss")

        /** Sortable name, e.g. Cashbook_auto_2026-11-22_090000.cbk */
        fun fileName(t: LocalDateTime) = PREFIX + t.format(STAMP) + ".cbk"

        /** Which automatic backup files to delete so only the newest [keep] remain. Other files are ignored. */
        fun toDelete(names: List<String>, keep: Int): List<String> =
            names.filter { it.startsWith(PREFIX) && it.endsWith(".cbk") }.sortedDescending().drop(keep.coerceAtLeast(1))
    }
}
