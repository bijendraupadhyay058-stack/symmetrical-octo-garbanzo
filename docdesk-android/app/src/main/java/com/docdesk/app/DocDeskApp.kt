package com.docdesk.app

import android.app.Application
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.docdesk.app.data.FileRepository
import com.docdesk.app.data.HistoryRepository
import com.docdesk.app.data.SettingsRepository
import com.docdesk.app.data.db.AppDatabase
import com.docdesk.app.jobs.CleanupWorker
import com.docdesk.app.jobs.JobRunner
import com.docdesk.app.ui.result.ResultStore
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import java.util.concurrent.TimeUnit

/** Simple manual dependency container; the app is small enough not to need a DI framework. */
class DocDeskApp : Application() {
    lateinit var files: FileRepository private set
    lateinit var settings: SettingsRepository private set
    lateinit var history: HistoryRepository private set
    lateinit var jobs: JobRunner private set
    val results = ResultStore()

    override fun onCreate() {
        super.onCreate()
        instance = this
        PDFBoxResourceLoader.init(applicationContext)
        files = FileRepository(this)
        settings = SettingsRepository(this)
        history = HistoryRepository(AppDatabase.get(this).historyDao(), settings)
        jobs = JobRunner()
        // Remove stale temporary files left by interrupted work (e.g. the app was killed).
        Thread { files.cleanTemporary(olderThanMillis = TimeUnit.HOURS.toMillis(6)) }.start()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "temp-cleanup",
            ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<CleanupWorker>(1, TimeUnit.DAYS).build(),
        )
    }

    companion object {
        lateinit var instance: DocDeskApp private set
    }
}
