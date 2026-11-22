package com.cashbook.app.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory

@Database(
    entities = [CashbookEntity::class, AccountEntity::class, CategoryEntity::class, PartyEntity::class,
        TransactionEntity::class, AttachmentEntity::class, BackupHistoryEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun cashbooks(): CashbookDao
    abstract fun accounts(): AccountDao
    abstract fun categories(): CategoryDao
    abstract fun parties(): PartyDao
    abstract fun transactions(): TransactionDao
    abstract fun attachments(): AttachmentDao
    abstract fun backups(): BackupHistoryDao
    abstract fun maintenance(): MaintenanceDao

    companion object {
        const val NAME = "cashbook.db"

        /** Opens the SQLCipher-encrypted database with a key held by the Android Keystore. */
        fun open(context: Context, key: ByteArray): AppDatabase {
            System.loadLibrary("sqlcipher")
            return Room.databaseBuilder(context, AppDatabase::class.java, NAME)
                .openHelperFactory(SupportOpenHelperFactory(key))
                .build()
        }
    }
}
