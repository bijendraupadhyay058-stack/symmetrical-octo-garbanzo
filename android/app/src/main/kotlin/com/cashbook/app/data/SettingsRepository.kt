package com.cashbook.app.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import com.cashbook.core.CurrencyDisplay
import com.cashbook.core.DateFormatOption
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.time.DayOfWeek

enum class ThemeMode { SYSTEM, LIGHT, DARK }

/** All non-sensitive user preferences (stored with Jetpack DataStore). Sensitive values live in [com.cashbook.app.data.security.SecureStore]. */
data class AppSettings(
    val onboarded: Boolean = false,
    val language: String = "en",
    val theme: ThemeMode = ThemeMode.SYSTEM,
    val dateFormat: DateFormatOption = DateFormatOption.DD_MM_YYYY,
    val defaultCashbookId: Long = 0,
    /** Cashbook shown on Dashboard/Transactions/Reports. [ALL_CASHBOOKS] = combined view. */
    val currentCashbookId: Long = 0,
    val defaultAccountId: Long = 0,
    val weekStart: DayOfWeek = DayOfWeek.MONDAY,
    /** When false, saving an entry that makes an account negative is blocked. When true the user is warned and may proceed. */
    val allowNegative: Boolean = true,
    val currencyDisplay: CurrencyDisplay = CurrencyDisplay.SYMBOL,
    val lockEnabled: Boolean = false,
    val biometricEnabled: Boolean = false,
    val autoLockSeconds: Int = 60,
    val lastBackupAt: Long = 0,
    val backupReminderDays: Int = 0,
    /** Days to keep deleted entries; 0 = keep until removed manually. */
    val recycleRetentionDays: Int = 30,
    val secureScreen: Boolean = false,
    // ---- automatic backup (v1.1) ----
    val autoBackupEnabled: Boolean = false,
    /** Folder chosen with the system picker (persisted SAF tree URI). */
    val autoBackupFolder: String = "",
    val autoBackupFolderName: String = "",
    val autoBackupEveryDays: Int = 1,
    val autoBackupKeep: Int = 5,
    val autoBackupAttachments: Boolean = true,
    val lastAutoBackupAt: Long = 0,
    /** Empty when the last automatic backup succeeded; otherwise a short reason shown in Backup. */
    val lastAutoBackupError: String = "",
    // ---- alerts & widget (v1.2) ----
    val invoiceReminders: Boolean = false,
    val budgetAlerts: Boolean = false,
    /** Budget alerts already sent, as "budgetId:yyyy-MM:STATUS" keys, so each level is notified once a month. */
    val sentBudgetAlerts: Set<String> = emptySet(),
    /** Show the total balance on the home-screen widget (always hidden while the app lock is on). */
    val widgetShowBalance: Boolean = false,
) {
    companion object { const val ALL_CASHBOOKS = -1L }
}

/** One instance per process (created by [com.cashbook.app.AppContainer]). */
class SettingsRepository(context: Context, fileName: String = "settings") {
    private val dataStore = PreferenceDataStoreFactory.create(produceFile = { context.applicationContext.preferencesDataStoreFile(fileName) })

    private object K {
        val onboarded = booleanPreferencesKey("onboarded")
        val language = stringPreferencesKey("language")
        val theme = stringPreferencesKey("theme")
        val dateFormat = stringPreferencesKey("date_format")
        val defaultCashbook = longPreferencesKey("default_cashbook")
        val currentCashbook = longPreferencesKey("current_cashbook")
        val defaultAccount = longPreferencesKey("default_account")
        val weekStart = stringPreferencesKey("week_start")
        val allowNegative = booleanPreferencesKey("allow_negative")
        val currencyDisplay = stringPreferencesKey("currency_display")
        val lockEnabled = booleanPreferencesKey("lock_enabled")
        val biometric = booleanPreferencesKey("biometric")
        val autoLock = intPreferencesKey("auto_lock_seconds")
        val lastBackup = longPreferencesKey("last_backup")
        val reminderDays = intPreferencesKey("backup_reminder_days")
        val retention = intPreferencesKey("recycle_retention_days")
        val secureScreen = booleanPreferencesKey("secure_screen")
        val abEnabled = booleanPreferencesKey("auto_backup_enabled")
        val abFolder = stringPreferencesKey("auto_backup_folder")
        val abFolderName = stringPreferencesKey("auto_backup_folder_name")
        val abEvery = intPreferencesKey("auto_backup_every_days")
        val abKeep = intPreferencesKey("auto_backup_keep")
        val abAttach = booleanPreferencesKey("auto_backup_attachments")
        val abLast = longPreferencesKey("last_auto_backup")
        val abError = stringPreferencesKey("last_auto_backup_error")
        val invoiceReminders = booleanPreferencesKey("invoice_reminders")
        val budgetAlerts = booleanPreferencesKey("budget_alerts")
        val sentBudgetAlerts = stringSetPreferencesKey("sent_budget_alerts")
        val widgetBalance = booleanPreferencesKey("widget_show_balance")
    }

    val settings: Flow<AppSettings> = dataStore.data.map { p -> p.toSettings() }

    private fun Preferences.toSettings(): AppSettings {
        val d = AppSettings()
        return AppSettings(
            onboarded = this[K.onboarded] ?: d.onboarded,
            language = this[K.language] ?: d.language,
            theme = this[K.theme]?.let { runCatching { ThemeMode.valueOf(it) }.getOrNull() } ?: d.theme,
            dateFormat = this[K.dateFormat]?.let { runCatching { DateFormatOption.valueOf(it) }.getOrNull() } ?: d.dateFormat,
            defaultCashbookId = this[K.defaultCashbook] ?: d.defaultCashbookId,
            currentCashbookId = this[K.currentCashbook] ?: d.currentCashbookId,
            defaultAccountId = this[K.defaultAccount] ?: d.defaultAccountId,
            weekStart = this[K.weekStart]?.let { runCatching { DayOfWeek.valueOf(it) }.getOrNull() } ?: d.weekStart,
            allowNegative = this[K.allowNegative] ?: d.allowNegative,
            currencyDisplay = this[K.currencyDisplay]?.let { runCatching { CurrencyDisplay.valueOf(it) }.getOrNull() } ?: d.currencyDisplay,
            lockEnabled = this[K.lockEnabled] ?: d.lockEnabled,
            biometricEnabled = this[K.biometric] ?: d.biometricEnabled,
            autoLockSeconds = this[K.autoLock] ?: d.autoLockSeconds,
            lastBackupAt = this[K.lastBackup] ?: d.lastBackupAt,
            backupReminderDays = this[K.reminderDays] ?: d.backupReminderDays,
            recycleRetentionDays = this[K.retention] ?: d.recycleRetentionDays,
            secureScreen = this[K.secureScreen] ?: d.secureScreen,
            autoBackupEnabled = this[K.abEnabled] ?: d.autoBackupEnabled,
            autoBackupFolder = this[K.abFolder] ?: d.autoBackupFolder,
            autoBackupFolderName = this[K.abFolderName] ?: d.autoBackupFolderName,
            autoBackupEveryDays = this[K.abEvery] ?: d.autoBackupEveryDays,
            autoBackupKeep = this[K.abKeep] ?: d.autoBackupKeep,
            autoBackupAttachments = this[K.abAttach] ?: d.autoBackupAttachments,
            lastAutoBackupAt = this[K.abLast] ?: d.lastAutoBackupAt,
            lastAutoBackupError = this[K.abError] ?: d.lastAutoBackupError,
            invoiceReminders = this[K.invoiceReminders] ?: d.invoiceReminders,
            budgetAlerts = this[K.budgetAlerts] ?: d.budgetAlerts,
            sentBudgetAlerts = this[K.sentBudgetAlerts] ?: d.sentBudgetAlerts,
            widgetShowBalance = this[K.widgetBalance] ?: d.widgetShowBalance,
        )
    }

    suspend fun update(transform: (AppSettings) -> AppSettings) {
        dataStore.edit { p ->
            val n = transform(p.toSettings())
            p[K.onboarded] = n.onboarded
            p[K.language] = n.language
            p[K.theme] = n.theme.name
            p[K.dateFormat] = n.dateFormat.name
            p[K.defaultCashbook] = n.defaultCashbookId
            p[K.currentCashbook] = n.currentCashbookId
            p[K.defaultAccount] = n.defaultAccountId
            p[K.weekStart] = n.weekStart.name
            p[K.allowNegative] = n.allowNegative
            p[K.currencyDisplay] = n.currencyDisplay.name
            p[K.lockEnabled] = n.lockEnabled
            p[K.biometric] = n.biometricEnabled
            p[K.autoLock] = n.autoLockSeconds
            p[K.lastBackup] = n.lastBackupAt
            p[K.reminderDays] = n.backupReminderDays
            p[K.retention] = n.recycleRetentionDays
            p[K.secureScreen] = n.secureScreen
            p[K.abEnabled] = n.autoBackupEnabled
            p[K.abFolder] = n.autoBackupFolder
            p[K.abFolderName] = n.autoBackupFolderName
            p[K.abEvery] = n.autoBackupEveryDays
            p[K.abKeep] = n.autoBackupKeep
            p[K.abAttach] = n.autoBackupAttachments
            p[K.abLast] = n.lastAutoBackupAt
            p[K.abError] = n.lastAutoBackupError
            p[K.invoiceReminders] = n.invoiceReminders
            p[K.budgetAlerts] = n.budgetAlerts
            p[K.sentBudgetAlerts] = n.sentBudgetAlerts
            p[K.widgetBalance] = n.widgetShowBalance
        }
    }
}
