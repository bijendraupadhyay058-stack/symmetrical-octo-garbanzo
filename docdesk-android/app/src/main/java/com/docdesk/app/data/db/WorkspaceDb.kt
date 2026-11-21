package com.docdesk.app.data.db

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Delete
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

/** A client. Stored only on this device (and in backups the user makes). */
@Entity(tableName = "clients")
data class ClientEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val reference: String = "", // e.g. PAN or file number – optional, typed by the user
    val notes: String = "",
    val archived: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
)

/** A folder inside a client: financial year, assessment year, document category or any name. */
@Entity(tableName = "folders", indices = [Index("clientId"), Index("parentId")])
data class FolderEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val clientId: Long,
    val parentId: Long?,
    val name: String,
    val kind: String,
    val createdAt: Long = System.currentTimeMillis(),
)

/**
 * A document filed under a client. [uri] is a reference to the file (Android keeps read access
 * for files picked with the system picker); the file itself is not copied unless it is in My Files.
 */
@Entity(tableName = "documents", indices = [Index("clientId"), Index("folderId")])
data class WsDocEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val clientId: Long,
    val folderId: Long?,
    val name: String,
    val uri: String,
    val mime: String = "",
    val size: Long = 0,
    val tags: String = "",
    val note: String = "",
    val status: String = "PENDING_REVIEW",
    val addedAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
)

@Entity(tableName = "activity", indices = [Index("clientId")])
data class ActivityEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val clientId: Long,
    val time: Long = System.currentTimeMillis(),
    val text: String,
)

@Entity(tableName = "checklists", indices = [Index("clientId")])
data class ChecklistEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val clientId: Long,
    val title: String,
    val createdAt: Long = System.currentTimeMillis(),
)

@Entity(tableName = "checklist_items", indices = [Index("checklistId")])
data class ChecklistItemEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val checklistId: Long,
    val text: String,
    val done: Boolean = false,
    val position: Int = 0,
)

@Dao
interface WorkspaceDao {
    @Query("SELECT * FROM clients ORDER BY archived, name COLLATE NOCASE") fun observeClients(): Flow<List<ClientEntity>>
    @Query("SELECT * FROM clients WHERE id = :id") fun observeClient(id: Long): Flow<ClientEntity?>
    @Insert suspend fun insertClient(c: ClientEntity): Long
    @Update suspend fun updateClient(c: ClientEntity)

    @Query("SELECT * FROM folders WHERE clientId = :clientId ORDER BY name COLLATE NOCASE") fun observeFolders(clientId: Long): Flow<List<FolderEntity>>
    @Query("SELECT * FROM folders") fun observeAllFolders(): Flow<List<FolderEntity>>
    @Insert suspend fun insertFolder(f: FolderEntity): Long
    @Update suspend fun updateFolder(f: FolderEntity)
    @Delete suspend fun deleteFolder(f: FolderEntity)

    @Query("SELECT * FROM documents WHERE clientId = :clientId ORDER BY name COLLATE NOCASE") fun observeDocs(clientId: Long): Flow<List<WsDocEntity>>
    @Query("SELECT * FROM documents") fun observeAllDocs(): Flow<List<WsDocEntity>>
    @Insert suspend fun insertDoc(d: WsDocEntity): Long
    @Update suspend fun updateDoc(d: WsDocEntity)
    @Delete suspend fun deleteDoc(d: WsDocEntity)
    @Query("UPDATE documents SET folderId = :to WHERE folderId = :from") suspend fun moveDocs(from: Long, to: Long?)
    @Query("UPDATE folders SET parentId = :to WHERE parentId = :from") suspend fun moveFolders(from: Long, to: Long?)

    @Query("SELECT * FROM activity WHERE clientId = :clientId ORDER BY time DESC LIMIT 200") fun observeActivity(clientId: Long): Flow<List<ActivityEntity>>
    @Insert suspend fun insertActivity(a: ActivityEntity)

    @Query("SELECT * FROM checklists WHERE clientId = :clientId ORDER BY createdAt DESC") fun observeChecklists(clientId: Long): Flow<List<ChecklistEntity>>
    @Insert suspend fun insertChecklist(c: ChecklistEntity): Long
    @Update suspend fun updateChecklist(c: ChecklistEntity)
    @Delete suspend fun deleteChecklist(c: ChecklistEntity)
    @Query("DELETE FROM checklist_items WHERE checklistId = :id") suspend fun deleteItemsOf(id: Long)
    @Query("SELECT * FROM checklist_items WHERE checklistId IN (SELECT id FROM checklists WHERE clientId = :clientId) ORDER BY position") fun observeItems(clientId: Long): Flow<List<ChecklistItemEntity>>
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsertItem(i: ChecklistItemEntity): Long
    @Insert suspend fun insertItems(i: List<ChecklistItemEntity>)
    @Delete suspend fun deleteItem(i: ChecklistItemEntity)

    // Backup / restore
    @Query("SELECT * FROM clients") suspend fun allClients(): List<ClientEntity>
    @Query("SELECT * FROM folders") suspend fun allFolders(): List<FolderEntity>
    @Query("SELECT * FROM documents") suspend fun allDocs(): List<WsDocEntity>
    @Query("SELECT * FROM activity") suspend fun allActivity(): List<ActivityEntity>
    @Query("SELECT * FROM checklists") suspend fun allChecklists(): List<ChecklistEntity>
    @Query("SELECT * FROM checklist_items") suspend fun allItems(): List<ChecklistItemEntity>
    @Query("DELETE FROM clients") suspend fun clearClients()
    @Query("DELETE FROM folders") suspend fun clearFolders()
    @Query("DELETE FROM documents") suspend fun clearDocs()
    @Query("DELETE FROM activity") suspend fun clearActivity()
    @Query("DELETE FROM checklists") suspend fun clearChecklists()
    @Query("DELETE FROM checklist_items") suspend fun clearItems()
    @Insert suspend fun insertClients(l: List<ClientEntity>)
    @Insert suspend fun insertFolders(l: List<FolderEntity>)
    @Insert suspend fun insertDocs(l: List<WsDocEntity>)
    @Insert suspend fun insertActivities(l: List<ActivityEntity>)
    @Insert suspend fun insertChecklists(l: List<ChecklistEntity>)

    @Transaction
    suspend fun replaceAll(c: List<ClientEntity>, f: List<FolderEntity>, d: List<WsDocEntity>, a: List<ActivityEntity>, cl: List<ChecklistEntity>, i: List<ChecklistItemEntity>) {
        clearItems(); clearChecklists(); clearActivity(); clearDocs(); clearFolders(); clearClients()
        insertClients(c); insertFolders(f); insertDocs(d); insertActivities(a); insertChecklists(cl); insertItems(i)
    }
}

@Database(entities = [ClientEntity::class, FolderEntity::class, WsDocEntity::class, ActivityEntity::class, ChecklistEntity::class, ChecklistItemEntity::class], version = 1, exportSchema = true)
abstract class WorkspaceDatabase : RoomDatabase() {
    abstract fun dao(): WorkspaceDao

    companion object {
        @Volatile private var db: WorkspaceDatabase? = null
        fun get(context: Context): WorkspaceDatabase = db ?: synchronized(this) {
            db ?: Room.databaseBuilder(context.applicationContext, WorkspaceDatabase::class.java, "workspace.db").build().also { db = it }
        }
    }
}
