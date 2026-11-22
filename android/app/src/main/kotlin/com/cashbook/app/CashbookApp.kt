package com.cashbook.app

import android.app.Application
import android.content.Context
import com.cashbook.app.data.AttachmentStore
import com.cashbook.app.data.BackupManager
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.data.SettingsRepository
import com.cashbook.app.data.db.AppDatabase
import com.cashbook.app.data.security.SecureStore
import com.cashbook.app.work.DailyWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

open class CashbookApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = createContainer()
        scheduleWork()
    }

    /** Production wiring: Keystore-backed secrets and the SQLCipher database. Tests override this. */
    protected open fun createContainer() = AppContainer(this, SecureStore(this)) { ctx, key -> AppDatabase.open(ctx, key) }

    protected open fun scheduleWork() = DailyWorker.schedule(this)
}

/** Ready dependencies, created once the encrypted database has been opened. */
class Dependencies(
    val db: AppDatabase,
    val ledger: LedgerRepository,
    val settings: SettingsRepository,
    val secure: SecureStore,
    val attachments: AttachmentStore,
    val backup: BackupManager,
)

/** Manual dependency injection container. */
class AppContainer(
    context: Context,
    val secure: SecureStore,
    val settings: SettingsRepository = SettingsRepository(context),
    openDatabase: (Context, ByteArray) -> AppDatabase,
) {
    sealed interface State {
        data object Loading : State
        data class Ready(val deps: Dependencies) : State
        data class Failed(val error: Throwable) : State
    }

    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _state = MutableStateFlow<State>(State.Loading)
    val state: StateFlow<State> = _state

    init {
        appScope.launch(Dispatchers.IO) {
            _state.value = try {
                val db = openDatabase(context, secure.databaseKey())
                db.openHelper.writableDatabase // open now so failures surface here
                val store = AttachmentStore(context)
                State.Ready(Dependencies(db, LedgerRepository(db, store, appScope), settings, secure, store,
                    BackupManager(context, db, store, settings)))
            } catch (t: Throwable) {
                State.Failed(t)
            }
        }
    }

    suspend fun awaitReady(): Dependencies? = when (val s = state.first { it !is State.Loading }) {
        is State.Ready -> s.deps
        else -> null
    }
}
