package com.docdesk.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.core.DateOrder
import com.docdesk.core.NumberStyle
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

enum class ThemeMode(val label: String) { SYSTEM("Follow system"), LIGHT("Light"), DARK("Dark") }

data class AppSettings(
    val theme: ThemeMode = ThemeMode.SYSTEM,
    val ocrLanguage: OcrLanguage = OcrLanguage.LATIN,
    val dateOrder: DateOrder = DateOrder.DMY,
    val numberStyle: NumberStyle = NumberStyle.INDIAN,
    val keepHistory: Boolean = true,
    /** Ask for fingerprint / face / screen lock when opening DocDesk. */
    val appLock: Boolean = false,
    /** Block screenshots and hide the app's content in the recent-apps screen. */
    val secureScreen: Boolean = false,
    /** Keyword → ledger rules ("SALARY => Salary A/c"), used for categories and Tally export. */
    val ledgerRules: String = DEFAULT_RULES,
    val tallyBankLedger: String = "",
    val tallyDefaultLedger: String = "Suspense A/c",
    val favourites: Set<String> = setOf("statements", "pdf2excel", "edit", "create"),
)

const val DEFAULT_RULES = "# Keyword => Ledger (one per line; first match wins)\nSALARY => Salary\nRENT => Rent\nATM => Cash\nGST => GST Payable\nINTEREST => Bank Interest\nCHARGES => Bank Charges"

private val Context.dataStore by preferencesDataStore("settings")

class SettingsRepository(private val context: Context) {
    private val theme = stringPreferencesKey("theme")
    private val ocr = stringPreferencesKey("ocr_language")
    private val date = stringPreferencesKey("date_order")
    private val number = stringPreferencesKey("number_style")
    private val keepHistory = booleanPreferencesKey("keep_history")
    private val appLock = booleanPreferencesKey("app_lock")
    private val secureScreen = booleanPreferencesKey("secure_screen")
    private val rules = stringPreferencesKey("ledger_rules")
    private val bankLedger = stringPreferencesKey("tally_bank_ledger")
    private val defaultLedger = stringPreferencesKey("tally_default_ledger")
    private val favourites = stringSetPreferencesKey("favourites")

    val settings: Flow<AppSettings> = context.dataStore.data.map { p ->
        AppSettings(
            theme = p[theme]?.let { runCatching { ThemeMode.valueOf(it) }.getOrNull() } ?: ThemeMode.SYSTEM,
            ocrLanguage = p[ocr]?.let { runCatching { OcrLanguage.valueOf(it) }.getOrNull() } ?: OcrLanguage.LATIN,
            dateOrder = p[date]?.let { runCatching { DateOrder.valueOf(it) }.getOrNull() } ?: DateOrder.DMY,
            numberStyle = p[number]?.let { runCatching { NumberStyle.valueOf(it) }.getOrNull() } ?: NumberStyle.INDIAN,
            keepHistory = p[keepHistory] ?: true,
            appLock = p[appLock] ?: false,
            secureScreen = p[secureScreen] ?: false,
            ledgerRules = p[rules] ?: DEFAULT_RULES,
            tallyBankLedger = p[bankLedger] ?: "",
            tallyDefaultLedger = p[defaultLedger] ?: "Suspense A/c",
            favourites = p[favourites] ?: setOf("statements", "pdf2excel", "edit", "create"),
        )
    }

    suspend fun setTheme(v: ThemeMode) = context.dataStore.edit { it[theme] = v.name }
    suspend fun setOcrLanguage(v: OcrLanguage) = context.dataStore.edit { it[ocr] = v.name }
    suspend fun setDateOrder(v: DateOrder) = context.dataStore.edit { it[date] = v.name }
    suspend fun setNumberStyle(v: NumberStyle) = context.dataStore.edit { it[number] = v.name }
    suspend fun setKeepHistory(v: Boolean) = context.dataStore.edit { it[keepHistory] = v }
    suspend fun setAppLock(v: Boolean) = context.dataStore.edit { it[appLock] = v }
    suspend fun setSecureScreen(v: Boolean) = context.dataStore.edit { it[secureScreen] = v }
    suspend fun setTally(rulesText: String, bank: String, default: String) = context.dataStore.edit { it[rules] = rulesText; it[bankLedger] = bank; it[defaultLedger] = default }
    suspend fun toggleFavourite(route: String) = context.dataStore.edit { p -> val cur = p[favourites] ?: setOf("statements", "pdf2excel", "edit", "create"); p[favourites] = if (route in cur) cur - route else cur + route }

    /** All settings as plain values, for backups. App lock and screen protection are included; nothing secret is stored in settings. */
    suspend fun exportAll(): Map<String, Any> = context.dataStore.data.first().asMap().mapKeys { it.key.name }.filterValues { it is String || it is Boolean || it is Set<*> }

    /** Restores settings from a backup: only strings, booleans and string sets are accepted. */
    suspend fun importAll(values: Map<String, Any>) {
        context.dataStore.edit { p ->
            for ((k, v) in values) when (v) {
                is String -> p[stringPreferencesKey(k)] = v
                is Boolean -> p[booleanPreferencesKey(k)] = v
                is Set<*> -> p[stringSetPreferencesKey(k)] = v.filterIsInstance<String>().toSet()
            }
        }
    }
}
