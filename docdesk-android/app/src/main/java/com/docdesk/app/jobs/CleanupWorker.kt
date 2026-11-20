package com.docdesk.app.jobs

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.docdesk.app.DocDeskApp
import java.util.concurrent.TimeUnit

/** Daily removal of temporary files older than one day (outputs that were never saved). */
class CleanupWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as DocDeskApp
        if (!app.jobs.isBusy) app.files.cleanTemporary(olderThanMillis = TimeUnit.DAYS.toMillis(1))
        return Result.success()
    }
}
