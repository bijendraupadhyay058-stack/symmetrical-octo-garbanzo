package com.docdesk.app.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import com.docdesk.app.data.db.ActivityEntity
import com.docdesk.app.data.db.ChecklistEntity
import com.docdesk.app.data.db.ChecklistItemEntity
import com.docdesk.app.data.db.ClientEntity
import com.docdesk.app.data.db.FolderEntity
import com.docdesk.app.data.db.WorkspaceDao
import com.docdesk.app.data.db.WsDocEntity
import com.docdesk.core.DocStatus
import com.docdesk.core.Workspace

/** Client workspace: clients, folders, filed documents (as references), checklists and activity. Local only. */
class WorkspaceRepository(private val context: Context, val dao: WorkspaceDao) {
    private suspend fun log(clientId: Long, text: String) = dao.insertActivity(ActivityEntity(clientId = clientId, text = text))

    suspend fun createClient(name: String, reference: String): Long {
        val id = dao.insertClient(ClientEntity(name = name.trim(), reference = reference.trim()))
        log(id, "Client created"); return id
    }

    suspend fun updateClient(c: ClientEntity, what: String) { dao.updateClient(c.copy(updatedAt = System.currentTimeMillis())); log(c.id, what) }

    suspend fun createFolder(clientId: Long, parentId: Long?, name: String, kind: com.docdesk.core.FolderKind): Long {
        val id = dao.insertFolder(FolderEntity(clientId = clientId, parentId = parentId, name = name.trim(), kind = kind.name))
        log(clientId, "Folder “${name.trim()}” created"); return id
    }

    suspend fun renameFolder(f: FolderEntity, name: String) { dao.updateFolder(f.copy(name = name.trim())); log(f.clientId, "Folder “${f.name}” renamed to “${name.trim()}”") }

    /** Deletes a folder; its documents and subfolders move up to the parent folder (nothing is lost). */
    suspend fun deleteFolder(f: FolderEntity) {
        dao.moveDocs(f.id, f.parentId); dao.moveFolders(f.id, f.parentId); dao.deleteFolder(f)
        log(f.clientId, "Folder “${f.name}” removed (its contents moved up)")
    }

    /** Files picked documents under a client. Keeps Android's read permission so they open later. */
    suspend fun addDocuments(clientId: Long, folderId: Long?, uris: List<Uri>, files: FileRepository): Int {
        var n = 0
        for (u in uris) {
            if (u.scheme == "content") runCatching { context.contentResolver.takePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            val d = runCatching { files.describe(u) }.getOrNull() ?: continue
            dao.insertDoc(WsDocEntity(clientId = clientId, folderId = folderId, name = d.name, uri = u.toString(), mime = context.contentResolver.getType(u) ?: "", size = d.size))
            n++
        }
        if (n > 0) log(clientId, "$n document(s) added")
        return n
    }

    suspend fun updateDoc(d: WsDocEntity, what: String) { dao.updateDoc(d.copy(updatedAt = System.currentTimeMillis())); log(d.clientId, "${d.name}: $what") }

    suspend fun setStatus(d: WsDocEntity, s: DocStatus) = updateDoc(d.copy(status = s.name), "status set to ${s.label}")

    /** Removes the entry only; the file itself is not deleted. */
    suspend fun removeDoc(d: WsDocEntity) {
        dao.deleteDoc(d)
        runCatching { context.contentResolver.releasePersistableUriPermission(Uri.parse(d.uri), Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        log(d.clientId, "${d.name}: removed from workspace (file not deleted)")
    }

    /** True if the referenced file can still be opened. */
    fun isAvailable(d: WsDocEntity): Boolean = runCatching {
        val u = Uri.parse(d.uri)
        if (u.scheme == "file") java.io.File(u.path!!).exists() else context.contentResolver.openFileDescriptor(u, "r")?.use { true } ?: false
    }.getOrDefault(false)

    suspend fun createChecklist(clientId: Long, title: String, items: List<String>): Long {
        val id = dao.insertChecklist(ChecklistEntity(clientId = clientId, title = title.trim()))
        dao.insertItems(items.mapIndexed { i, t -> ChecklistItemEntity(checklistId = id, text = t, position = i) })
        log(clientId, "Checklist “${title.trim()}” created"); return id
    }

    suspend fun deleteChecklist(c: ChecklistEntity) { dao.deleteItemsOf(c.id); dao.deleteChecklist(c); log(c.clientId, "Checklist “${c.title}” deleted") }

    suspend fun toggleItem(clientId: Long, i: ChecklistItemEntity) { dao.upsertItem(i.copy(done = !i.done)); log(clientId, "${if (i.done) "Unticked" else "Ticked"}: ${i.text}") }

    companion object {
        val categories = Workspace.categories
    }
}
