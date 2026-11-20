package com.docdesk.app.jobs

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class JobState(val title: String, val message: String, val progress: Float?, val running: Boolean = true)

/**
 * Passed to long operations so they can report progress and notice cancellation.
 * Cancellation is cooperative: [step] throws [OperationCancelled] once the user taps Cancel,
 * unless the operation called [allowPartialResults] – then it checks [cancelRequested] between
 * pages and returns the pages finished so far, clearly marked as incomplete.
 */
class Progress internal constructor(private val update: (String, Float?) -> Unit) {
    @Volatile var cancelRequested = false
        internal set
    private var partial = false

    fun allowPartialResults() { partial = true }

    fun step(message: String, fraction: Float? = null) {
        if (cancelRequested && !partial) throw OperationCancelled()
        update(message, fraction?.coerceIn(0f, 1f))
    }

    fun checkCancelled() { if (cancelRequested && !partial) throw OperationCancelled() }
}

/**
 * Runs one document operation at a time in an application-wide scope, so work continues while
 * the user moves between screens and the progress card on Home stays accurate. The operation
 * runs on a background dispatcher; the UI thread is never blocked.
 *
 * Why not WorkManager for conversions: results are previewed interactively and often need a
 * password held only in memory, which must not be persisted into WorkManager's database.
 * WorkManager is used for periodic temp-file cleanup instead (see CleanupWorker).
 */
class JobRunner {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _state = MutableStateFlow<JobState?>(null)
    val state: StateFlow<JobState?> = _state.asStateFlow()
    private var current: Job? = null
    private var progress: Progress? = null

    val isBusy get() = current?.isActive == true

    /**
     * Starts [block]. [onDone] is called on the main thread with the result, or with the
     * failure/cancellation exception.
     */
    fun <T> start(title: String, block: suspend (Progress) -> T, onDone: (Result<T>) -> Unit): Boolean {
        if (isBusy) return false
        _state.value = JobState(title, "Starting…", null)
        current = scope.launch {
            val p = Progress { msg, f -> _state.value = JobState(title, if (progress?.cancelRequested == true) "Cancelling…" else msg, f) }
            progress = p
            val result = try {
                Result.success(withContext(Dispatchers.IO) { block(p) })
            } catch (e: CancellationException) {
                Result.failure(OperationCancelled())
            } catch (e: OutOfMemoryError) {
                Result.failure(OperationFailed("The device ran out of memory. Try fewer pages at a time or close other apps."))
            } catch (e: Throwable) {
                Result.failure(e)
            }
            _state.value = null
            withContext(Dispatchers.Main) { onDone(result) }
        }
        return true
    }

    fun cancel() {
        progress?.cancelRequested = true
        _state.value = _state.value?.copy(message = "Cancelling…")
    }
}

class OperationCancelled : Exception("Cancelled")
class OperationFailed(message: String) : Exception(message)

/** Turns exceptions into short messages for people (no stack traces, no document content). */
fun Throwable.userMessage(): String = when (this) {
    is OperationFailed, is com.docdesk.core.UnsupportedDocumentException -> message ?: "The operation failed."
    is OperationCancelled -> "Cancelled."
    is com.tom_roush.pdfbox.pdmodel.encryption.InvalidPasswordException -> "The password is incorrect."
    is java.io.FileNotFoundException -> "The file could not be found or is no longer accessible."
    is java.io.IOException -> when {
        message?.contains("ENOSPC") == true || message?.contains("No space") == true -> "There is not enough free storage on the device."
        message?.contains("Missing root object", true) == true || message?.contains("Header doesn't contain", true) == true ||
            message?.contains("Error: End-of-File", true) == true -> "The PDF is damaged or is not a PDF file."
        else -> "The file could not be read: ${message ?: "input/output error"}."
    }
    is SecurityException -> "The app no longer has permission to read this file. Please select it again."
    else -> "Something went wrong (${javaClass.simpleName})."
}
