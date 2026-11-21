package com.docdesk.app.data.db

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

/**
 * One processing operation. Only file NAMES and counts are stored – never document content,
 * extracted text or passwords.
 */
@Entity(tableName = "history")
data class HistoryEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val timestamp: Long,
    val operation: String,
    val inputNames: String,
    val status: String,
    val pagesSelected: Int?,
    val pagesProcessed: Int?,
    val warningCount: Int,
    val summary: String,
    /** Paths of outputs saved in My Files, separated by newlines (empty if not saved). */
    val outputPaths: String = "",
)

@Dao
interface HistoryDao {
    @Query("SELECT * FROM history ORDER BY timestamp DESC")
    fun observeAll(): Flow<List<HistoryEntity>>

    @Insert
    suspend fun insert(e: HistoryEntity): Long

    @Query("UPDATE history SET outputPaths = :paths WHERE id = :id")
    suspend fun setOutputs(id: Long, paths: String)

    @Query("DELETE FROM history WHERE id = :id")
    suspend fun delete(id: Long)

    @Query("DELETE FROM history")
    suspend fun clear()
}

@Database(entities = [HistoryEntity::class], version = 1, exportSchema = true)
abstract class AppDatabase : RoomDatabase() {
    abstract fun historyDao(): HistoryDao

    companion object {
        @Volatile private var db: AppDatabase? = null
        fun get(context: Context): AppDatabase = db ?: synchronized(this) {
            db ?: Room.databaseBuilder(context.applicationContext, AppDatabase::class.java, "docdesk.db").build().also { db = it }
        }
    }
}
