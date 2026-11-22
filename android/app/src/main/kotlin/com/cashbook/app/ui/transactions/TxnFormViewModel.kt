package com.cashbook.app.ui.transactions

import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.SavedStateHandleSaveableApi
import androidx.lifecycle.viewmodel.compose.saveable
import com.cashbook.app.Dependencies
import com.cashbook.app.data.AppSettings
import com.cashbook.app.data.AttachmentStore
import com.cashbook.app.data.Snapshot
import com.cashbook.app.data.db.AttachmentEntity
import com.cashbook.app.ui.currentScope
import com.cashbook.core.AccountType
import com.cashbook.core.Ledger
import com.cashbook.core.Money
import com.cashbook.core.PaymentMode
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate

/**
 * State and validation for the income / expense / transfer form. Field values live in the
 * [SavedStateHandle], so a half-typed entry survives the app being killed in the background.
 */
@OptIn(SavedStateHandleSaveableApi::class)
class TxnFormViewModel(
    handle: SavedStateHandle,
    private val deps: Dependencies,
    private val initialType: TxnType?,
    val editId: Long,
    private val duplicateId: Long,
) : ViewModel() {
    var type by handle.saveable { mutableStateOf(initialType ?: TxnType.EXPENSE) }
    var cashbookId by handle.saveable { mutableStateOf(0L) }
    var date by handle.saveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var amount by handle.saveable { mutableStateOf("") }
    var categoryId by handle.saveable { mutableStateOf(0L) }
    var accountId by handle.saveable { mutableStateOf(0L) }
    var toAccountId by handle.saveable { mutableStateOf(0L) }
    var mode by handle.saveable { mutableStateOf(PaymentMode.CASH) }
    var partyId by handle.saveable { mutableStateOf(0L) }
    var description by handle.saveable { mutableStateOf("") }
    var reference by handle.saveable { mutableStateOf("") }
    var notes by handle.saveable { mutableStateOf("") }
    var tags by handle.saveable { mutableStateOf("") }
    private var initialized by handle.saveable { mutableStateOf(false) }
    private var pendingStored by handle.saveable { mutableStateOf("") } // "stored|name|mime|size;..."
    private var removedIds by handle.saveable { mutableStateOf("") }

    val pending = mutableStateListOf<AttachmentStore.Imported>()
    val existing = mutableStateListOf<AttachmentEntity>()
    var showErrors by mutableStateOf(false)
    var busy by mutableStateOf(false)
    private var saved = false

    init {
        pendingStored.split(';').filter { it.isNotBlank() }.forEach { s ->
            val p = s.split('|'); if (p.size == 4) pending += AttachmentStore.Imported(p[0], p[1], p[2], p[3].toLongOrNull() ?: 0)
        }
    }

    private fun persistPending() { pendingStored = pending.joinToString(";") { "${it.storedName}|${it.fileName.replace("|", "_").replace(";", "_")}|${it.mimeType}|${it.sizeBytes}" } }
    val removed: Set<Long> get() = removedIds.split(',').mapNotNull { it.toLongOrNull() }.toSet()

    /** One-time initialisation from defaults, an entry being edited, or one being duplicated. */
    fun initialize(snap: Snapshot, s: AppSettings) {
        if (initialized || !snap.loaded) return
        val sourceId = if (editId > 0) editId else duplicateId
        if (sourceId > 0) {
            viewModelScope.launch {
                val t = deps.ledger.getTxn(sourceId) ?: return@launch
                type = t.type; cashbookId = t.cashbookId; amount = Money.toPlain(t.amount); categoryId = t.categoryId ?: 0
                accountId = t.accountId; toAccountId = t.toAccountId ?: 0; mode = t.paymentMode; partyId = t.partyId ?: 0
                description = t.description; reference = if (editId > 0) t.reference else ""; notes = t.notes; tags = t.tags
                date = if (editId > 0) t.date.toEpochDay() else LocalDate.now().toEpochDay()
                if (editId > 0) existing.addAll(deps.ledger.attachmentList(editId))
                initialized = true
            }
            return
        }
        val scope = currentScope(snap, s)
        cashbookId = if (s.defaultCashbookId in scope) s.defaultCashbookId else scope.firstOrNull() ?: 0
        applyDefaultAccounts(snap, s)
        initialized = true
    }

    fun loadExistingIfNeeded() {
        if (editId > 0 && existing.isEmpty()) viewModelScope.launch { existing.addAll(deps.ledger.attachmentList(editId)) }
    }

    fun applyDefaultAccounts(snap: Snapshot, s: AppSettings) {
        val accs = snap.accounts.filter { it.cashbookId == cashbookId && !it.archived }
        val def = accs.firstOrNull { it.id == s.defaultAccountId }
        accountId = when (type) {
            TxnType.TRANSFER -> (accs.firstOrNull { it.type == AccountType.BANK } ?: accs.firstOrNull())?.id ?: 0
            else -> (def ?: accs.firstOrNull())?.id ?: 0
        }
        toAccountId = if (type == TxnType.TRANSFER) accs.firstOrNull { it.id != accountId && it.type == AccountType.CASH }?.id
            ?: accs.firstOrNull { it.id != accountId }?.id ?: 0 else 0
        mode = when (type) {
            TxnType.TRANSFER -> PaymentMode.BANK_TRANSFER
            else -> if (accs.firstOrNull { it.id == accountId }?.type == AccountType.CASH) PaymentMode.CASH else PaymentMode.UPI
        }
        categoryId = 0
    }

    val isInitialized get() = initialized

    // ---------- validation ----------
    enum class Err { AMOUNT_EMPTY, AMOUNT_INVALID, AMOUNT_ZERO, AMOUNT_DECIMALS, AMOUNT_LARGE, CATEGORY, ACCOUNT, TO_ACCOUNT, SAME_ACCOUNT, BEFORE_OPENING, NO_CASHBOOK }

    fun errors(snap: Snapshot): Map<String, Err> {
        val e = LinkedHashMap<String, Err>()
        if (cashbookId == 0L || snap.cashbookById[cashbookId] == null) e["cashbook"] = Err.NO_CASHBOOK
        when (val r = Money.parse(amount)) {
            is Money.ParseResult.Error -> e["amount"] = when (r.reason) {
                Money.AmountError.EMPTY -> Err.AMOUNT_EMPTY; Money.AmountError.INVALID -> Err.AMOUNT_INVALID
                Money.AmountError.ZERO_OR_NEGATIVE -> Err.AMOUNT_ZERO; Money.AmountError.TOO_MANY_DECIMALS -> Err.AMOUNT_DECIMALS
                Money.AmountError.TOO_LARGE -> Err.AMOUNT_LARGE
            }
            else -> {}
        }
        if (type != TxnType.TRANSFER && (categoryId == 0L || snap.categoryById[categoryId] == null)) e["category"] = Err.CATEGORY
        val acc = snap.accountById[accountId]?.takeIf { it.cashbookId == cashbookId }
        if (acc == null) e["account"] = Err.ACCOUNT
        val d = LocalDate.ofEpochDay(date)
        if (acc != null && d.isBefore(acc.openingDate)) e["date"] = Err.BEFORE_OPENING
        if (type == TxnType.TRANSFER) {
            val to = snap.accountById[toAccountId]?.takeIf { it.cashbookId == cashbookId }
            if (to == null) e["to"] = Err.TO_ACCOUNT
            else if (toAccountId == accountId) e["to"] = Err.SAME_ACCOUNT
            else if (d.isBefore(to.openingDate)) e["date"] = Err.BEFORE_OPENING
        }
        return e
    }

    fun buildTxn(): Txn = Txn(
        id = if (editId > 0) editId else 0, cashbookId = cashbookId, type = type, date = LocalDate.ofEpochDay(date),
        amount = (Money.parse(amount) as Money.ParseResult.Ok).paise, accountId = accountId,
        toAccountId = if (type == TxnType.TRANSFER) toAccountId else null,
        categoryId = if (type == TxnType.TRANSFER) null else categoryId,
        partyId = if (type == TxnType.TRANSFER) null else partyId.takeIf { it > 0 },
        paymentMode = mode, description = description, reference = reference, notes = notes, tags = tags,
        createdAt = System.currentTimeMillis(),
    )

    /** Returns the account and resulting balance if saving would make an account negative. */
    fun negativeCheck(snap: Snapshot) = Ledger.negativeCheck(snap.accounts, snap.txns, buildTxn(), if (editId > 0) editId else null)

    // ---------- attachments ----------
    fun addAttachment(uri: Uri, replacing: String?, onError: (Throwable) -> Unit) {
        busy = true
        viewModelScope.launch {
            try {
                val imported = withContext(Dispatchers.IO) { deps.attachments.import(uri) }
                replacing?.let { removeAttachment(it) }
                pending += imported
                persistPending()
            } catch (e: Throwable) { onError(e) } finally { busy = false }
        }
    }

    /** [key] is "p:<storedName>" for a not-yet-saved file or "e:<id>" for a saved one. */
    fun removeAttachment(key: String) {
        if (key.startsWith("p:")) {
            val name = key.removePrefix("p:")
            pending.removeAll { it.storedName == name }
            deps.attachments.delete(name)
            persistPending()
        } else {
            removedIds = (removed + key.removePrefix("e:").toLong()).joinToString(",")
        }
    }

    fun save(onDone: (Long) -> Unit, onError: (Throwable) -> Unit) {
        busy = true
        viewModelScope.launch {
            try {
                val id = deps.ledger.saveTxn(buildTxn(), pending.toList(), removed.toList())
                saved = true
                onDone(id)
            } catch (e: Throwable) { onError(e) } finally { busy = false }
        }
    }

    /** Clears per-entry fields after "Save and add another"; keeps date, account and mode. */
    fun resetForNext() {
        amount = ""; description = ""; reference = ""; notes = ""; tags = ""; partyId = 0
        pending.clear(); persistPending(); removedIds = ""; existing.clear(); showErrors = false; saved = false
    }

    fun discard() {
        if (!saved) pending.forEach { deps.attachments.delete(it.storedName) }
        pending.clear(); persistPending()
    }
}
