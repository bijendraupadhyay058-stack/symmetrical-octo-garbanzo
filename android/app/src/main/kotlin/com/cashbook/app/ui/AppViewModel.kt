package com.cashbook.app.ui

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.cashbook.app.AppContainer
import com.cashbook.app.CashbookApp
import com.cashbook.app.Dependencies
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.Snapshot
import com.cashbook.core.SortOrder
import com.cashbook.core.TxnFilter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Activity-scoped view model: exposes the ledger snapshot and settings to every screen, runs
 * repository actions, owns the app-lock state and the transaction-list filter.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AppViewModel(app: Application) : AndroidViewModel(app) {
    val container: AppContainer = (app as CashbookApp).container
    val state: StateFlow<AppContainer.State> = container.state

    val settings: StateFlow<AppSettings?> = container.settings.settings.stateIn(viewModelScope, SharingStarted.Eagerly, null)

    val snapshot: StateFlow<Snapshot> = state.flatMapLatest { s ->
        if (s is AppContainer.State.Ready) s.deps.ledger.snapshot else flowOf(Snapshot())
    }.stateIn(viewModelScope, SharingStarted.Eagerly, Snapshot())

    val deps: Dependencies? get() = (state.value as? AppContainer.State.Ready)?.deps

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val messages: SharedFlow<String> = _messages
    fun toast(msg: String) { _messages.tryEmit(msg) }

    // ----- transaction list state (survives tab switches) -----
    val listFilter = MutableStateFlow(TxnFilter())
    val listSort = MutableStateFlow(SortOrder.LATEST)

    /** One-shot parameters for the next report screen (e.g. "export this party / cashbook"). */
    var pendingReportFilter: TxnFilter? = null
    var pendingReportAllTime: Boolean = false

    /** Screen requested from outside (widget button, notification): "add_INCOME", "invoices", "budgets", "backup"… */
    private val _openRequest = MutableStateFlow<String?>(null)
    val openRequest: StateFlow<String?> = _openRequest
    fun requestOpen(target: String) { _openRequest.value = target }
    fun consumeOpen() { _openRequest.value = null }

    // ----- app lock -----
    private val _locked = MutableStateFlow(true)
    val locked: StateFlow<Boolean> = _locked
    private var backgroundAt = 0L
    private var skipNextLock = false

    init {
        viewModelScope.launch {
            val s = settings.filterNotNull().first()
            _locked.value = s.lockEnabled && container.secure.hasPin
        }
    }

    fun onAppBackground() { backgroundAt = SystemClock.elapsedRealtime() }

    fun onAppForeground() {
        val s = settings.value ?: return
        if (skipNextLock) { skipNextLock = false; return }
        if (!s.lockEnabled || !container.secure.hasPin || backgroundAt == 0L) return
        if (SystemClock.elapsedRealtime() - backgroundAt >= s.autoLockSeconds * 1000L) _locked.value = true
    }

    /** Call before opening the camera / file picker / share sheet so returning doesn't lock immediately. */
    fun allowExternalActivity() { skipNextLock = true }

    fun lockNow() { if (container.secure.hasPin) _locked.value = true }
    fun unlocked() { _locked.value = false; backgroundAt = 0L }

    // ----- actions -----
    fun run(onError: ((Throwable) -> Unit)? = null, block: suspend Dependencies.() -> Unit) {
        val d = deps ?: return
        viewModelScope.launch {
            try { d.block() } catch (e: CancellationException) { throw e } catch (e: Throwable) {
                onError?.invoke(e) ?: _messages.tryEmit(e.localizedMessage ?: e.javaClass.simpleName)
            }
        }
    }

    fun updateSettings(transform: (AppSettings) -> AppSettings) {
        viewModelScope.launch { container.settings.update(transform) }
    }

    /** Cashbook ids in the current scope (one cashbook, or all active ones for the combined view). */
    fun scopeIds(snap: Snapshot, s: AppSettings): Set<Long> = currentScope(snap, s)
}

fun currentScope(snap: Snapshot, s: AppSettings): Set<Long> {
    val active = snap.cashbooks.filter { !it.archived }
    if (s.currentCashbookId == AppSettings.ALL_CASHBOOKS) return active.map { it.id }.toSet()
    snap.cashbookById[s.currentCashbookId]?.let { return setOf(it.id) }
    snap.cashbookById[s.defaultCashbookId]?.let { return setOf(it.id) }
    return active.firstOrNull()?.let { setOf(it.id) } ?: snap.cashbooks.firstOrNull()?.let { setOf(it.id) } ?: emptySet()
}

fun scopeName(snap: Snapshot, s: AppSettings, allLabel: String): String =
    if (s.currentCashbookId == AppSettings.ALL_CASHBOOKS) allLabel
    else currentScope(snap, s).firstOrNull()?.let { snap.cashbookById[it]?.name } ?: ""
