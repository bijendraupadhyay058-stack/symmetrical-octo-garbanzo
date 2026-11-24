package com.cashbook.app.work

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.cashbook.app.CashbookApp
import com.cashbook.app.MainActivity
import com.cashbook.app.R
import kotlinx.coroutines.flow.first
import java.util.concurrent.TimeUnit

/** Daily housekeeping: recycle-bin retention and optional backup reminder notification. */
class DailyWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as CashbookApp
        val container = app.container.awaitReady() ?: return Result.success()
        val s = container.settings.settings.first()
        container.ledger.purgeOlderThan(s.recycleRetentionDays)
        container.ledger.postDueRecurring()
        container.ledger.postDueInvoiceSchedules(dates = s.dateFormat)
        container.autoBackup.runIfDue(s)
        val sent = Alerts.run(applicationContext, container.ledger.snapshot.first { it.loaded }, s)
        if (sent.isNotEmpty()) container.settings.update { st ->
            // keep only this month's keys so the set stays small
            val month = java.time.YearMonth.now().toString()
            st.copy(sentBudgetAlerts = (st.sentBudgetAlerts + sent).filter { it.contains(":$month:") }.toSet())
        }
        com.cashbook.app.widget.WidgetUpdater.updateAll(applicationContext)
        if (s.backupReminderDays > 0 && !s.autoBackupEnabled) {
            val due = s.lastBackupAt + s.backupReminderDays * 86_400_000L
            if (System.currentTimeMillis() >= due) notifyBackup(applicationContext)
        }
        return Result.success()
    }

    companion object {
        private const val NAME = "cashbook-daily"
        private const val CHANNEL = "backup_reminders"

        fun schedule(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<DailyWorker>(1, TimeUnit.DAYS).build())
        }

        fun notifyBackup(context: Context) {
            if (Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
            val nm = context.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.backup_reminder_channel), NotificationManager.IMPORTANCE_DEFAULT))
            val intent = PendingIntent.getActivity(context, 0,
                Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN, "backup"),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val n = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(context.getString(R.string.backup_reminder_title))
                .setContentText(context.getString(R.string.backup_reminder_text))
                .setContentIntent(intent)
                .setAutoCancel(true)
                .build()
            NotificationManagerCompat.from(context).notify(1001, n)
        }
    }
}
