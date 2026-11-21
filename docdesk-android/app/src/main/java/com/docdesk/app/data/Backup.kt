package com.docdesk.app.data

import com.docdesk.app.DocDeskApp
import com.docdesk.app.data.db.ActivityEntity
import com.docdesk.app.data.db.ChecklistEntity
import com.docdesk.app.data.db.ChecklistItemEntity
import com.docdesk.app.data.db.ClientEntity
import com.docdesk.app.data.db.FolderEntity
import com.docdesk.app.data.db.WsDocEntity
import org.json.JSONArray
import org.json.JSONObject

/**
 * Local backup of app data: client workspace (clients, folders, document entries, tags, notes,
 * statuses, checklists, activity) and settings. Documents themselves are NOT included – only
 * their names and links. Nothing is uploaded; the user chooses where the file is saved.
 */
object Backup {
    const val FORMAT = "docdesk-backup"
    const val VERSION = 1

    data class RestoreResult(val clients: Int, val documents: Int, val checklists: Int, val settings: Int)

    private fun <T> arr(list: List<T>, f: (T) -> JSONObject) = JSONArray().apply { list.forEach { put(f(it)) } }
    private fun JSONArray.objs() = (0 until length()).map { getJSONObject(it) }
    private fun JSONObject.optLongOrNull(k: String) = if (isNull(k) || !has(k)) null else getLong(k)

    suspend fun export(app: DocDeskApp): String {
        val d = app.workspace.dao
        val root = JSONObject()
        root.put("format", FORMAT); root.put("version", VERSION); root.put("created", System.currentTimeMillis())
        root.put("note", "Contains client folders, document names and links, tags, notes, checklists and settings. Document files are not included.")
        root.put("clients", arr(d.allClients()) { JSONObject().put("id", it.id).put("name", it.name).put("reference", it.reference).put("notes", it.notes).put("archived", it.archived).put("createdAt", it.createdAt).put("updatedAt", it.updatedAt) })
        root.put("folders", arr(d.allFolders()) { JSONObject().put("id", it.id).put("clientId", it.clientId).put("parentId", it.parentId ?: JSONObject.NULL).put("name", it.name).put("kind", it.kind).put("createdAt", it.createdAt) })
        root.put("documents", arr(d.allDocs()) { JSONObject().put("id", it.id).put("clientId", it.clientId).put("folderId", it.folderId ?: JSONObject.NULL).put("name", it.name).put("uri", it.uri).put("mime", it.mime).put("size", it.size).put("tags", it.tags).put("note", it.note).put("status", it.status).put("addedAt", it.addedAt).put("updatedAt", it.updatedAt) })
        root.put("activity", arr(d.allActivity()) { JSONObject().put("id", it.id).put("clientId", it.clientId).put("time", it.time).put("text", it.text) })
        root.put("checklists", arr(d.allChecklists()) { JSONObject().put("id", it.id).put("clientId", it.clientId).put("title", it.title).put("createdAt", it.createdAt) })
        root.put("checklistItems", arr(d.allItems()) { JSONObject().put("id", it.id).put("checklistId", it.checklistId).put("text", it.text).put("done", it.done).put("position", it.position) })
        val st = JSONObject()
        app.settings.exportAll().forEach { (k, v) -> st.put(k, if (v is Set<*>) JSONArray(v.toList()) else v) }
        root.put("settings", st)
        return root.toString(1)
    }

    /** Replaces the workspace and settings with the backup's contents. Throws if the file isn't a DocDesk backup. */
    suspend fun restore(app: DocDeskApp, json: String): RestoreResult {
        val root = try { JSONObject(json) } catch (e: Exception) { throw com.docdesk.app.jobs.OperationFailed("This file is not a DocDesk backup.") }
        if (root.optString("format") != FORMAT) throw com.docdesk.app.jobs.OperationFailed("This file is not a DocDesk backup.")
        if (root.optInt("version") > VERSION) throw com.docdesk.app.jobs.OperationFailed("This backup was made by a newer DocDesk. Update the app first.")
        val clients = root.optJSONArray("clients")?.objs().orEmpty().map { ClientEntity(it.getLong("id"), it.getString("name"), it.optString("reference"), it.optString("notes"), it.optBoolean("archived"), it.optLong("createdAt"), it.optLong("updatedAt")) }
        val folders = root.optJSONArray("folders")?.objs().orEmpty().map { FolderEntity(it.getLong("id"), it.getLong("clientId"), it.optLongOrNull("parentId"), it.getString("name"), it.optString("kind", "OTHER"), it.optLong("createdAt")) }
        val docs = root.optJSONArray("documents")?.objs().orEmpty().map { WsDocEntity(it.getLong("id"), it.getLong("clientId"), it.optLongOrNull("folderId"), it.getString("name"), it.getString("uri"), it.optString("mime"), it.optLong("size"), it.optString("tags"), it.optString("note"), it.optString("status", "PENDING_REVIEW"), it.optLong("addedAt"), it.optLong("updatedAt")) }
        val act = root.optJSONArray("activity")?.objs().orEmpty().map { ActivityEntity(it.getLong("id"), it.getLong("clientId"), it.optLong("time"), it.getString("text")) }
        val cls = root.optJSONArray("checklists")?.objs().orEmpty().map { ChecklistEntity(it.getLong("id"), it.getLong("clientId"), it.getString("title"), it.optLong("createdAt")) }
        val items = root.optJSONArray("checklistItems")?.objs().orEmpty().map { ChecklistItemEntity(it.getLong("id"), it.getLong("checklistId"), it.getString("text"), it.optBoolean("done"), it.optInt("position")) }
        app.workspace.dao.replaceAll(clients, folders, docs, act, cls, items)
        val st = root.optJSONObject("settings")
        val values = HashMap<String, Any>()
        st?.keys()?.forEach { k -> when (val v = st.get(k)) { is String, is Boolean -> values[k] = v; is JSONArray -> values[k] = (0 until v.length()).map { v.getString(it) }.toSet() } }
        app.settings.importAll(values)
        return RestoreResult(clients.size, docs.size, cls.size, values.size)
    }
}
