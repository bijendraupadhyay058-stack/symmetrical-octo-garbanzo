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
import com.cashbook.app.MainActivity
import com.cashbook.app.R
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.Snapshot
import com.cashbook.core.BudgetStatus
import com.cashbook.core.Budgets
import com.cashbook.core.CurrencyDisplay
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.MoneyFormatter
import java.time.LocalDate
import java.time.YearMonth

/** Optional notifications: overdue / due-soon invoices and budget thresholds. Only shown if the user turned them on. */
object Alerts {
    private const val CHANNEL = "alerts"

    data class InvoiceDigest(val overdueCount: Int, val overdueReceivable: Long, val overduePayable: Long, val dueSoonCount: Int)

    /** Invoices overdue, and those due today or tomorrow (pure; tested). */
    fun invoiceDigest(snap: Snapshot, today: LocalDate): InvoiceDigest {
        val open = snap.invoiceBalances(today).filter { it.outstanding > 0 }
        val overdue = open.filter { it.status == InvoiceStatus.OVERDUE }
        val dueSoon = open.filter { it.status != InvoiceStatus.OVERDUE && !it.invoice.dueDate.isAfter(today.plusDays(1)) }
        return InvoiceDigest(overdue.size, overdue.filter { it.invoice.kind == InvoiceKind.SALE }.sumOf { it.outstanding },
            overdue.filter { it.invoice.kind == InvoiceKind.PURCHASE }.sumOf { it.outstanding }, dueSoon.size)
    }

    /** Budget alerts not yet sent this month, as (key, text-ready progress). */
    fun pendingBudgetAlerts(snap: Snapshot, s: AppSettings, today: LocalDate) =
        Budgets.progress(snap.budgets, snap.txns, snap.categoryById, YearMonth.from(today))
            .filter { it.status != BudgetStatus.OK }
            .map { "${it.budget.id}:${YearMonth.from(today)}:${it.status}" to it }
            .filter { it.first !in s.sentBudgetAlerts }

    fun canNotify(context: Context) = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun notify(context: Context, id: Int, title: String, text: String, open: String) {
        if (!canNotify(context)) return
        context.getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.alerts_channel), NotificationManager.IMPORTANCE_DEFAULT))
        val intent = PendingIntent.getActivity(context, id, Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN, open)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        NotificationManagerCompat.from(context).notify(id, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(intent).setAutoCancel(true).build())
    }

    /** Called by the daily worker. Returns the budget-alert keys that were sent. */
    fun run(context: Context, snap: Snapshot, s: AppSettings, today: LocalDate = LocalDate.now()): Set<String> {
        val money = MoneyFormatter(s.currencyDisplay.takeIf { it != CurrencyDisplay.NONE } ?: CurrencyDisplay.SYMBOL)
        if (s.invoiceReminders) {
            val d = invoiceDigest(snap, today)
            if (d.overdueCount > 0 || d.dueSoonCount > 0) {
                val parts = buildList {
                    if (d.overdueCount > 0) add(context.getString(R.string.alert_overdue, d.overdueCount, money.format(d.overdueReceivable), money.format(d.overduePayable)))
                    if (d.dueSoonCount > 0) add(context.getString(R.string.alert_due_soon, d.dueSoonCount))
                }
                notify(context, 2001, context.getString(R.string.alert_invoices_title), parts.joinToString(" "), "invoices")
            }
        }
        if (!s.budgetAlerts) return emptySet()
        val pending = pendingBudgetAlerts(snap, s, today)
        pending.forEachIndexed { i, (_, p) ->
            val name = snap.categoryName(p.budget.categoryId)
            val text = if (p.status == BudgetStatus.OVER) context.getString(R.string.alert_budget_over, name, money.format(-p.remaining))
            else context.getString(R.string.alert_budget_near, name, p.percent)
            notify(context, 3000 + (p.budget.id % 900).toInt() + i, context.getString(R.string.alert_budget_title), text, "budgets")
        }
        return pending.map { it.first }.toSet()
    }
}
