package com.docdesk.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.data.AppSettings
import com.docdesk.app.ui.AppNav
import com.docdesk.app.ui.theme.DocDeskTheme

class MainActivity : ComponentActivity() {
    /** A PDF opened from another app ("Open with DocDesk"). */
    private val incoming = mutableStateOf<Uri?>(null)
    private val incomingMany = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handle(intent)
        val app = application as DocDeskApp
        setContent {
            val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
            DocDeskTheme(settings.theme) {
                AppNav(incoming = incoming.value, onIncomingHandled = { incoming.value = null; incomingMany.value = false }, incomingMany = incomingMany.value)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** "Open with DocDesk" (VIEW) and "Share › DocDesk" (SEND / SEND_MULTIPLE). */
    @Suppress("DEPRECATION")
    private fun handle(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_VIEW -> intent.data?.let { incoming.value = it }
            Intent.ACTION_SEND -> (intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))?.let { incoming.value = it }
            Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.takeIf { it.isNotEmpty() }?.let { list ->
                if (list.size == 1) incoming.value = list[0]
                else { (application as DocDeskApp).setPendingInputs(list); incomingMany.value = true; incoming.value = list[0] }
            }
        }
    }
}
