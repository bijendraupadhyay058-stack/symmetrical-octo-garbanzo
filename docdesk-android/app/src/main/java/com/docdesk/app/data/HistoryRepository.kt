package com.docdesk.app.data

import com.docdesk.app.data.db.HistoryDao
import com.docdesk.app.data.db.HistoryEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first

class HistoryRepository(private val dao: HistoryDao, private val settings: SettingsRepository) {
    val all: Flow<List<HistoryEntity>> = dao.observeAll()

    /** Records an operation if the user keeps history; returns the row id or null. */
    suspend fun record(e: HistoryEntity): Long? = if (settings.settings.first().keepHistory) dao.insert(e) else null
    suspend fun setOutputs(id: Long, paths: List<String>) = dao.setOutputs(id, paths.joinToString("\n"))
    suspend fun delete(id: Long) = dao.delete(id)
    suspend fun clear() = dao.clear()
}
