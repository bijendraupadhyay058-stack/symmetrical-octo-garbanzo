package com.docdesk.app.ui.result

import com.docdesk.app.convert.OperationResult
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/** Holds finished results in memory so the Result screen can show them (keyed by id). */
class ResultStore {
    private val next = AtomicLong(1)
    private val results = ConcurrentHashMap<Long, Pair<OperationResult, Long?>>()

    fun put(result: OperationResult, historyId: Long?): Long {
        val id = next.getAndIncrement()
        results[id] = result to historyId
        return id
    }

    fun get(id: Long): Pair<OperationResult, Long?>? = results[id]
}
