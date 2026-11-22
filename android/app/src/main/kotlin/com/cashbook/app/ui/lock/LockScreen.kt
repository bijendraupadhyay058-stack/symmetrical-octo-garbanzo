package com.cashbook.app.ui.lock

import android.content.Context
import android.content.ContextWrapper
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Backspace
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.theme.LocalFinanceColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

fun Context.findActivity(): FragmentActivity? {
    var c: Context? = this
    while (c is ContextWrapper) { if (c is FragmentActivity) return c; c = c.baseContext }
    return null
}

fun biometricAvailable(ctx: Context) =
    BiometricManager.from(ctx).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK) == BiometricManager.BIOMETRIC_SUCCESS

fun showBiometric(ctx: Context, title: String, cancel: String, onSuccess: () -> Unit) {
    val activity = ctx.findActivity() ?: return
    val prompt = BiometricPrompt(activity, ContextCompat.getMainExecutor(ctx), object : BiometricPrompt.AuthenticationCallback() {
        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = onSuccess()
    })
    prompt.authenticate(BiometricPrompt.PromptInfo.Builder().setTitle(title).setNegativeButtonText(cancel)
        .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_WEAK).build())
}

/** Full-screen PIN / biometric lock shown above the app content. */
@Composable
fun LockScreen(vm: AppViewModel) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    var pin by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var attempts by remember { mutableIntStateOf(0) }
    var lockedUntil by remember { mutableLongStateOf(0L) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val bioTitle = stringResource(R.string.unlock_cashbook)
    val cancel = stringResource(R.string.use_pin)
    val wrong = stringResource(R.string.wrong_pin)
    val bio = settings?.biometricEnabled == true && biometricAvailable(ctx)

    LaunchedEffect(Unit) { if (bio) showBiometric(ctx, bioTitle, cancel) { vm.unlocked() } }
    LaunchedEffect(lockedUntil) { while (System.currentTimeMillis() < lockedUntil) { now = System.currentTimeMillis(); delay(500) }; now = System.currentTimeMillis() }

    val pinLength = remember { vm.container.secure.pinLength.takeIf { it in 4..6 } ?: 6 }
    LaunchedEffect(pin) {
        if (pin.length >= 4) {
            val ok = withContext(Dispatchers.Default) { vm.container.secure.verifyPin(pin) }
            if (ok) { vm.unlocked(); pin = "" }
            else if (pin.length >= pinLength) {
                attempts++; pin = ""
                error = wrong
                if (attempts % 5 == 0) lockedUntil = System.currentTimeMillis() + 30_000L
            }
        }
    }
    val waiting = now < lockedUntil
    val fc = LocalFinanceColors.current
    Box(Modifier.fillMaxSize().background(fc.header).clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}) {
        Column(Modifier.fillMaxSize().systemBarsPadding().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(Icons.Filled.Lock, null, tint = fc.onHeader, modifier = Modifier.size(48.dp))
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.app_name), color = fc.onHeader, style = MaterialTheme.typography.headlineSmall)
            Text(stringResource(R.string.enter_pin), color = fc.onHeader.copy(alpha = 0.8f))
            Spacer(Modifier.height(20.dp))
            PinDots(pin.length, fc.onHeader, pinLength)
            Spacer(Modifier.height(8.dp))
            Text(when { waiting -> stringResource(R.string.too_many_attempts, ((lockedUntil - now) / 1000 + 1).toInt()); else -> error ?: " " },
                color = MaterialTheme.colorScheme.errorContainer, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(16.dp))
            PinPad(enabled = !waiting, color = fc.onHeader, onDigit = { if (pin.length < pinLength) { pin += it; error = null } }, onDelete = { pin = pin.dropLast(1) },
                extra = if (bio) ({ IconButton(onClick = { showBiometric(ctx, bioTitle, cancel) { vm.unlocked() } }, Modifier.size(72.dp)) {
                    Icon(Icons.Filled.Fingerprint, stringResource(R.string.use_biometric), tint = fc.onHeader, modifier = Modifier.size(36.dp)) } }) else null)
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.forgot_pin_hint), color = fc.onHeader.copy(alpha = 0.7f), style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
fun PinDots(count: Int, color: androidx.compose.ui.graphics.Color, max: Int = 6) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.semantics { contentDescription = "$count / $max" }) {
        repeat(max) { i ->
            Box(Modifier.size(14.dp).background(if (i < count) color else color.copy(alpha = 0.25f), CircleShape))
        }
    }
}

@Composable
fun PinPad(enabled: Boolean, color: androidx.compose.ui.graphics.Color, onDigit: (Char) -> Unit, onDelete: () -> Unit, extra: (@Composable () -> Unit)? = null) {
    val rows = listOf("123", "456", "789")
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        rows.forEach { r ->
            Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) { r.forEach { d -> Key(d.toString(), enabled, color) { onDigit(d) } } }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(18.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(72.dp), contentAlignment = Alignment.Center) { extra?.invoke() }
            Key("0", enabled, color) { onDigit('0') }
            IconButton(onClick = onDelete, enabled = enabled, modifier = Modifier.size(72.dp)) {
                Icon(Icons.AutoMirrored.Filled.Backspace, stringResource(R.string.delete), tint = color)
            }
        }
    }
}

@Composable
private fun Key(label: String, enabled: Boolean, color: androidx.compose.ui.graphics.Color, onClick: () -> Unit) {
    FilledTonalButton(onClick = onClick, enabled = enabled, modifier = Modifier.size(72.dp), shape = CircleShape) {
        Text(label, fontSize = 24.sp)
    }
}

/** Dialog-style PIN entry used when setting or confirming a PIN. Returns the PIN when 4–6 digits are confirmed. */
@Composable
fun PinSetup(title: String, onDone: (String) -> Unit, onCancel: () -> Unit) {
    var first by remember { mutableStateOf<String?>(null) }
    var pin by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val mismatch = stringResource(R.string.pin_mismatch)
    val fc = LocalFinanceColors.current
    Box(Modifier.fillMaxSize().background(fc.header).clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}) {
        Column(Modifier.fillMaxSize().systemBarsPadding().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Text(title, color = fc.onHeader, style = MaterialTheme.typography.headlineSmall)
            Text(stringResource(if (first == null) R.string.choose_pin else R.string.confirm_pin), color = fc.onHeader.copy(alpha = 0.8f))
            Spacer(Modifier.height(20.dp))
            PinDots(pin.length, fc.onHeader)
            Text(error ?: " ", color = MaterialTheme.colorScheme.errorContainer, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(16.dp))
            PinPad(true, fc.onHeader, onDigit = { if (pin.length < 6) { pin += it; error = null } }, onDelete = { pin = pin.dropLast(1) })
            Spacer(Modifier.height(12.dp))
            Row {
                TextButton(onClick = onCancel) { Text(stringResource(R.string.cancel), color = fc.onHeader) }
                TextButton(enabled = pin.length >= 4, onClick = {
                    val f = first
                    if (f == null) { first = pin; pin = "" }
                    else if (f == pin) onDone(pin)
                    else { error = mismatch; first = null; pin = "" }
                }) { Text(stringResource(R.string.next), color = fc.onHeader) }
            }
            Text(stringResource(R.string.pin_rules), color = fc.onHeader.copy(alpha = 0.7f), style = MaterialTheme.typography.labelSmall)
        }
    }
}
