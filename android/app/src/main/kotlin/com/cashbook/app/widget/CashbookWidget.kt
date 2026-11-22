package com.cashbook.app.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.cashbook.app.CashbookApp
import com.cashbook.app.MainActivity
import com.cashbook.app.R
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.Snapshot
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.scopeName
import com.cashbook.core.DateRange
import com.cashbook.core.Ledger
import com.cashbook.core.MoneyFormatter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.time.LocalDate

/** Home-screen widget: quick Add Income / Expense / Transfer, plus the balance when the user allows it. */
class CashbookWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try { WidgetUpdater.updateAll(context) } finally { pending.finish() }
        }
    }
}

object WidgetUpdater {
    data class Content(val title: String, val balance: String, val today: String)

    /** What the widget shows. Amounts are hidden while the app lock is on or unless the user opted in. */
    fun content(context: Context, snap: Snapshot, s: AppSettings, today: LocalDate = LocalDate.now()): Content {
        val scope = currentScope(snap, s)
        val title = context.getString(R.string.app_name) + " · " + scopeName(snap, s, context.getString(R.string.all_cashbooks))
        if (s.lockEnabled || !s.widgetShowBalance) return Content(title, context.getString(R.string.widget_balance_hidden), context.getString(R.string.widget_tap_to_add))
        val money = MoneyFormatter(s.currencyDisplay)
        val accounts = snap.accountsOf(scope)
        val txns = snap.txnsOf(scope)
        val total = accounts.sumOf { Ledger.balanceAsOf(it, txns, today) }
        val t = Ledger.totals(txns, accounts.map { it.id }.toSet(), DateRange(today, today))
        return Content(title, money.format(total), context.getString(R.string.widget_today, money.format(t.income), money.format(t.expense)))
    }

    fun views(context: Context, c: Content): RemoteViews = RemoteViews(context.packageName, R.layout.widget_cashbook).apply {
        setTextViewText(R.id.widget_title, c.title)
        setTextViewText(R.id.widget_balance, c.balance)
        setTextViewText(R.id.widget_today, c.today)
        setTextViewText(R.id.widget_income, "+ " + context.getString(R.string.type_income))
        setTextViewText(R.id.widget_expense, "− " + context.getString(R.string.type_expense))
        setTextViewText(R.id.widget_transfer, "⇄ " + context.getString(R.string.type_transfer))
        setOnClickPendingIntent(R.id.widget_root, open(context, 10, "dashboard"))
        setOnClickPendingIntent(R.id.widget_income, open(context, 11, "add_INCOME"))
        setOnClickPendingIntent(R.id.widget_expense, open(context, 12, "add_EXPENSE"))
        setOnClickPendingIntent(R.id.widget_transfer, open(context, 13, "add_TRANSFER"))
    }

    private fun open(context: Context, code: Int, target: String) = PendingIntent.getActivity(context, code,
        Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN, target).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Refreshes every placed widget. Cheap no-op when none are on the home screen. */
    suspend fun updateAll(context: Context) {
        val manager = AppWidgetManager.getInstance(context) ?: return
        val ids = manager.getAppWidgetIds(ComponentName(context, CashbookWidget::class.java))
        if (ids.isEmpty()) return
        val container = (context.applicationContext as CashbookApp).container
        val deps = container.awaitReady() ?: return
        val snap = deps.ledger.snapshot.first { it.loaded }
        val s = deps.settings.settings.first()
        val v = views(context, content(context, snap, s))
        ids.forEach { manager.updateAppWidget(it, v) }
    }
}
