package com.docdesk.app.pdf

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale

/**
 * Reads page text aloud with the phone's text-to-speech engine (on-device voices where installed).
 * Hindi is used automatically for Devanagari text if a Hindi voice is available.
 */
class ReadAloud(context: Context, private val onState: (speaking: Boolean, message: String?) -> Unit) {
    private var ready = false
    private var pending: String? = null
    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        ready = status == TextToSpeech.SUCCESS
        if (!ready) onState(false, "Text-to-speech is not available on this phone.")
        pending?.let { pending = null; speak(it) }
    }

    init {
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) { onState(true, null) }
            override fun onDone(id: String?) { if (id == "last") onState(false, null) }
            @Deprecated("Deprecated in Java") override fun onError(id: String?) { onState(false, "Reading stopped because of a speech error.") }
        })
    }

    fun speak(text: String) {
        if (!ready) { pending = text; return }
        val hindi = text.count { it in 'ऀ'..'ॿ' } > text.length / 10
        val locale = if (hindi) Locale("hi", "IN") else Locale("en", "IN")
        val r = tts.setLanguage(locale)
        var note: String? = null
        if (r == TextToSpeech.LANG_MISSING_DATA || r == TextToSpeech.LANG_NOT_SUPPORTED) {
            if (hindi) note = "No Hindi voice is installed. Add one in phone Settings › Accessibility › Text-to-speech." else tts.setLanguage(Locale.ENGLISH)
        }
        val chunks = text.replace(Regex("""[ \t]+"""), " ").split(Regex("""(?<=[.!?।])\s+|\n{2,}""")).map { it.trim() }.filter { it.isNotEmpty() }
            .flatMap { it.chunked(TextToSpeech.getMaxSpeechInputLength() - 10) }
        if (chunks.isEmpty()) { onState(false, "There is no text on this page to read (it may be a scanned image)."); return }
        chunks.forEachIndexed { i, c -> tts.speak(c, if (i == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD, null, if (i == chunks.lastIndex) "last" else "c$i") }
        onState(true, note)
    }

    fun stop() { tts.stop(); onState(false, null) }
    fun release() { tts.stop(); tts.shutdown() }
}
