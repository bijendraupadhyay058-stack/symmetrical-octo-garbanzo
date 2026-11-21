package com.docdesk.app.ui.components

import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.Outcome
import com.docdesk.app.data.db.HistoryEntity
import com.docdesk.app.jobs.OperationCancelled
import com.docdesk.app.jobs.Progress
import com.docdesk.app.jobs.userMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Starts an operation on the shared job runner. On success the result is stored (and recorded
 * in history) and [onResult] receives its id for navigation to the Result screen.
 */
object Operations {
    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun run(
        title: String,
        onError: (String) -> Unit,
        onResult: (Long) -> Unit,
        block: suspend (Progress) -> OperationResult,
    ): Boolean {
        val app = DocDeskApp.instance
        return app.jobs.start(title, block) { r ->
            r.fold(
                onSuccess = { res ->
                    ioScope.launch {
                        val hid = app.history.record(res.toHistory())
                        val id = app.results.put(res, hid)
                        kotlinx.coroutines.withContext(Dispatchers.Main) { onResult(id) }
                    }
                },
                onFailure = { e ->
                    if (e !is OperationCancelled) ioScope.launch {
                        app.history.record(HistoryEntity(timestamp = System.currentTimeMillis(), operation = title, inputNames = "", status = Outcome.FAILED.name, pagesSelected = null, pagesProcessed = null, warningCount = 0, summary = e.userMessage()))
                    }
                    onError(e.userMessage())
                },
            )
        }.also { started -> if (!started) onError("Another operation is still running. Wait for it to finish or cancel it from the Home screen.") }
    }

    private fun OperationResult.toHistory() = HistoryEntity(
        timestamp = System.currentTimeMillis(),
        operation = report.operation,
        inputNames = report.inputNames.joinToString(", "),
        status = report.outcome.name,
        pagesSelected = report.pagesSelected,
        pagesProcessed = report.pagesProcessed,
        warningCount = report.warnings.size + report.failedPages.size,
        summary = report.summary,
    )
}
