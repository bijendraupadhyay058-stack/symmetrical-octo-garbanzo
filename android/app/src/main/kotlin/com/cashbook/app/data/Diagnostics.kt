package com.cashbook.app.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.cashbook.app.Dependencies
import com.cashbook.app.work.Alerts
import com.cashbook.app.work.DailyWorker
import com.cashbook.core.HealthCheck
import com.cashbook.core.Severity
import java.util.concurrent.TimeUnit

/**
 * The app health check: things about this phone that decide whether reminders, automatic backups, WhatsApp sending
 * and PDF viewing will work, plus the database's own integrity check and the ledger consistency checks.
 */
object Diagnostics {
    enum class DeviceCheck { NOTIFICATIONS, DAILY_JOB, BATTERY, BACKUP_FOLDER, LAST_BACKUP, WHATSAPP, PDF_VIEWER, STORAGE, DATABASE }

    data class DeviceFinding(val check: DeviceCheck, val severity: Severity, val detail: String = "")

    data class Report(val device: List<DeviceFinding>, val ledger: List<HealthCheck.Finding>) {
        val worst: Severity get() = (device.map { it.severity } + ledger.map { it.severity }).maxOrNull() ?: Severity.OK
    }

    /** Runs every check. Call off the main thread (WorkManager and the database are queried). */
    suspend fun run(context: Context, deps: Dependencies, s: AppSettings, snap: Snapshot, now: Long = System.currentTimeMillis()): Report {
        val out = ArrayList<DeviceFinding>()
        out += DeviceFinding(DeviceCheck.NOTIFICATIONS, if (Alerts.canNotify(context)) Severity.OK else if (s.invoiceReminders || s.budgetAlerts) Severity.WARNING else Severity.INFO)
        val job = runCatching { WorkManager.getInstance(context).getWorkInfosForUniqueWork(DailyWorker.NAME).get(5, TimeUnit.SECONDS) }.getOrNull().orEmpty()
        out += DeviceFinding(DeviceCheck.DAILY_JOB, if (job.any { it.state == WorkInfo.State.ENQUEUED || it.state == WorkInfo.State.RUNNING }) Severity.OK else Severity.WARNING,
            job.joinToString { it.state.name })
        val pm = context.getSystemService(PowerManager::class.java)
        out += DeviceFinding(DeviceCheck.BATTERY, if (pm?.isIgnoringBatteryOptimizations(context.packageName) == true) Severity.OK else Severity.INFO)
        if (s.autoBackupEnabled) {
            val ok = runCatching {
                val uri = Uri.parse(s.autoBackupFolder)
                context.contentResolver.persistedUriPermissions.any { it.uri == uri && it.isWritePermission } &&
                    androidx.documentfile.provider.DocumentFile.fromTreeUri(context, uri)?.canWrite() == true
            }.getOrDefault(false)
            out += DeviceFinding(DeviceCheck.BACKUP_FOLDER, if (ok) Severity.OK else Severity.ERROR, s.autoBackupFolderName)
        }
        val last = maxOf(s.lastBackupAt, s.lastAutoBackupAt)
        val days = if (last == 0L) -1 else TimeUnit.MILLISECONDS.toDays(now - last).toInt()
        out += DeviceFinding(DeviceCheck.LAST_BACKUP, when { last == 0L -> Severity.WARNING; days > 30 -> Severity.WARNING; else -> Severity.OK }, days.toString())
        val wa = listOf("com.whatsapp", "com.whatsapp.w4b").any { p -> runCatching { context.packageManager.getPackageInfo(p, 0) }.isSuccess }
        out += DeviceFinding(DeviceCheck.WHATSAPP, if (wa) Severity.OK else Severity.INFO)
        val pdf = Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("content://x/y.pdf"), "application/pdf").resolveActivity(context.packageManager) != null
        out += DeviceFinding(DeviceCheck.PDF_VIEWER, if (pdf) Severity.OK else Severity.WARNING)
        val freeMb = context.filesDir.usableSpace / (1024 * 1024)
        out += DeviceFinding(DeviceCheck.STORAGE, if (freeMb < 100) Severity.WARNING else Severity.OK, freeMb.toString())
        val integrity = runCatching { deps.ledger.integrityCheck() }.getOrElse { it.message ?: "error" }
        out += DeviceFinding(DeviceCheck.DATABASE, if (integrity.equals("ok", ignoreCase = true)) Severity.OK else Severity.ERROR, integrity.take(200))
        val ledger = HealthCheck.ledger(snap.accounts, snap.categories, snap.txns, snap.deleted, snap.invoices + snap.quotations + snap.challans + snap.templates,
            snap.allocations)
        return Report(out, ledger)
    }
}
