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

    /** Files shared into the app ("Share › DocDesk" with several files), picked up by Create PDF. */
    private val pendingInputs = mutableListOf<android.net.Uri>()
    @Synchronized fun setPendingInputs(uris: List<android.net.Uri>) { pendingInputs.clear(); pendingInputs.addAll(uris) }
    @Synchronized fun takePendingInputs(): List<android.net.Uri> = pendingInputs.toList().also { pendingInputs.clear() }

    override fun onCreate() {
        super.onCreate()
        instance = this
        com.docdesk.app.data.ProblemReports.install(this)
        PDFBoxResourceLoader.init(applicationContext)
        files = FileRepository(this)
        settings = SettingsRepository(this)
        history = HistoryRepository(AppDatabase.get(this).historyDao(), settings)
        jobs = JobRunner()
        // Remove stale temporary files left by interrupted work (e.g. the app was killed).
        Thread { files.cleanTemporary(olderThanMillis = TimeUnit.HOURS.toMillis(6)) }.start()
        publishShortcuts()
        runCatching {
            WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                "temp-cleanup",
                ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<CleanupWorker>(1, TimeUnit.DAYS).build(),
            )
        }
    }

    /** Long-press shortcuts on the launcher icon. Dynamic, so they work for debug and release package names. */
    private fun publishShortcuts() = runCatching {
        fun sc(id: String, label: String, route: String, icon: Int) = androidx.core.content.pm.ShortcutInfoCompat.Builder(this, id)
            .setShortLabel(label)
            .setIcon(androidx.core.graphics.drawable.IconCompat.createWithResource(this, icon))
            .setIntent(android.content.Intent(this, MainActivity::class.java).setAction(MainActivity.ACTION_OPEN_TOOL).putExtra(MainActivity.EXTRA_ROUTE, route))
            .build()
        androidx.core.content.pm.ShortcutManagerCompat.setDynamicShortcuts(this, listOf(
            sc("scan", "Scan document", "scan", R.drawable.shortcut_scan),
            sc("create", "Create PDF", "create", R.drawable.shortcut_create),
            sc("statements", "Bank statements", "statements", R.drawable.shortcut_bank),
        ))
    }

    companion object {
        lateinit var instance: DocDeskApp private set
    }
}
