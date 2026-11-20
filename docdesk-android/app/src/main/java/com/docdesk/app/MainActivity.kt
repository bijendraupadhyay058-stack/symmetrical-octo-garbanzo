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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handle(intent)
        val app = application as DocDeskApp
        setContent {
            val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
            DocDeskTheme(settings.theme) {
                AppNav(incoming = incoming.value, onIncomingHandled = { incoming.value = null })
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        if (intent?.action == Intent.ACTION_VIEW) intent.data?.let { incoming.value = it }
    }
}
