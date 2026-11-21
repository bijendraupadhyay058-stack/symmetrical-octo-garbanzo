package com.docdesk.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.data.AppSettings
import com.docdesk.app.ui.AppNav
import com.docdesk.app.ui.theme.DocDeskTheme

class MainActivity : FragmentActivity() {
    /** A file opened from another app ("Open with" / "Share › DocDesk"). */
    private val incoming = mutableStateOf<Uri?>(null)
    private val incomingMany = mutableStateOf(false)
    private val locked = mutableStateOf(false)
    private var lockEnabled = false
    private var backgroundAt = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handle(intent)
        val app = application as DocDeskApp
        setContent {
            val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
            LaunchedEffect(settings.secureScreen) {
                if (settings.secureScreen) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE) else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
            }
            LaunchedEffect(settings.appLock) {
                val first = !lockEnabled && settings.appLock && backgroundAt == 0L
                lockEnabled = settings.appLock
                if (first && savedInstanceState == null) { locked.value = true; authenticate() }
                if (!settings.appLock) locked.value = false
            }
            DocDeskTheme(settings.theme) {
                if (locked.value) LockScreen() else AppNav(incoming = incoming.value, onIncomingHandled = { incoming.value = null; incomingMany.value = false }, incomingMany = incomingMany.value)
            }
        }
    }

    override fun onStop() {
        super.onStop()
        backgroundAt = SystemClock.elapsedRealtime()
    }

    override fun onStart() {
        super.onStart()
        // Re-lock after one minute in the background.
        if (lockEnabled && backgroundAt != 0L && SystemClock.elapsedRealtime() - backgroundAt > 60_000) { locked.value = true; authenticate() }
    }

    @androidx.compose.runtime.Composable
    private fun LockScreen() {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Default.Lock, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.primary)
                Text("DocDesk is locked", Modifier.padding(top = 16.dp), style = MaterialTheme.typography.headlineSmall)
                Text("Use your fingerprint, face or screen lock to open your documents.", Modifier.padding(vertical = 12.dp), style = MaterialTheme.typography.bodyMedium)
                Button(onClick = { authenticate() }) { Text("Unlock") }
            }
        }
    }

    private fun authenticate() {
        val auth = BIOMETRIC_WEAK or DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(auth) != BiometricManager.BIOMETRIC_SUCCESS) {
            // No fingerprint/face and no screen lock: locking is impossible, so don't trap the user.
            locked.value = false; return
        }
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) { locked.value = false }
        })
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder().setTitle("Unlock DocDesk").setAllowedAuthenticators(auth).build())
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
