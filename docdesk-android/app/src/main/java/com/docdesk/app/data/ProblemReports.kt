package com.docdesk.app.data

import android.content.Context
import android.content.Intent
import android.os.Build
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Local crash and error log that the user can choose to send (Settings › Send problem report).
 * Nothing is sent automatically. File names, paths, URIs and e-mail addresses are removed so the
 * report contains no document content or personal data – only technical details.
 */
object ProblemReports {
    private lateinit var dir: File
    private val crashFile get() = File(dir, "last_crash.txt")
    private val errorsFile get() = File(dir, "recent_errors.txt")
    private var version = ""

    fun install(context: Context) {
        dir = File(context.filesDir, "reports").apply { mkdirs() }
        version = runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "" }.getOrDefault("")
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            runCatching { crashFile.writeText(header() + "Crash in thread ${t.name}\n" + trace(e)) }
            previous?.uncaughtException(t, e)
        }
    }

    /** Records an unexpected (non-user) error from an operation; keeps the last 10. */
    fun recordError(operation: String, e: Throwable) {
        if (!::dir.isInitialized) return
        runCatching {
            val entry = "=== ${stamp()} · $operation\n" + trace(e)
            val old = if (errorsFile.exists()) errorsFile.readText().split("=== ").filter { it.isNotBlank() }.takeLast(9).joinToString("") { "=== $it" } else ""
            errorsFile.writeText(old + entry)
        }
    }

    fun hasCrash() = ::dir.isInitialized && crashFile.exists()
    fun dismissCrash() { if (::dir.isInitialized) crashFile.delete() }
    fun clear() { if (::dir.isInitialized) { crashFile.delete(); errorsFile.delete() } }

    fun report(): String = buildString {
        append(header())
        if (crashFile.exists()) append("\n--- Last crash ---\n").append(crashFile.readText().substringAfter("\n\n"))
        if (errorsFile.exists()) append("\n--- Recent errors ---\n").append(errorsFile.readText())
        if (!crashFile.exists() && !errorsFile.exists()) append("\nNo crashes or unexpected errors recorded.\n")
    }

    fun shareIntent(): Intent = Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_SUBJECT, "DocDesk problem report")
        putExtra(Intent.EXTRA_TEXT, report().take(90_000))
    }, "Send problem report")

    private fun stamp() = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(Date())

    private fun header() = "DocDesk $version · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL} · ${stamp()}\n" +
        "Max memory ${Runtime.getRuntime().maxMemory() / (1024 * 1024)} MB\n\n"

    private fun trace(e: Throwable): String {
        val sw = StringWriter(); e.printStackTrace(PrintWriter(sw))
        return sanitize(sw.toString()).lines().take(80).joinToString("\n") + "\n"
    }

    /** Removes anything that could identify files or people. */
    fun sanitize(s: String): String = s
        .replace(Regex("""content://\S+"""), "<uri>")
        .replace(Regex("""file://\S+"""), "<uri>")
        .replace(Regex("""(?i)/(data|storage|sdcard|mnt|tmp)/[^\n:)'"]*?\.(pdf|docx?|xlsx?|jpe?g|png|txt|csv|p12|pfx)(?![.\w])"""), "<path>")
        .replace(Regex("""(/(data|storage|sdcard|mnt|tmp)/[^\s:)'"]*)"""), "<path>")
        .replace(Regex("""[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"""), "<email>")
        .replace(Regex("""(?i)"[^"\n]{1,200}\.(pdf|docx?|xlsx?|jpe?g|png|txt|csv|p12|pfx)""""), "\"<file>\"")
        .replace(Regex("""(?i)\b[^\s/\\"(]{1,120}\.(pdf|docx?|xlsx?|jpe?g|png|csv|p12|pfx)(?![.\w])"""), "<file>")
}
