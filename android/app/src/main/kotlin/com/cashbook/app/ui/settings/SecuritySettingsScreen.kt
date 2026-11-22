package com.cashbook.app.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.ui.Alignment
import com.cashbook.app.ui.lock.PinDots
import com.cashbook.app.ui.lock.PinPad
import com.cashbook.app.ui.theme.LocalFinanceColors
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Password
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.NavRow
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.lock.PinSetup
import com.cashbook.app.ui.lock.biometricAvailable
import com.cashbook.app.ui.lock.showBiometric

@Composable
fun autoLockLabel(sec: Int) = when (sec) {
    0 -> stringResource(R.string.lock_immediately)
    in 1..59 -> stringResource(R.string.after_seconds, sec)
    else -> stringResource(R.string.after_minutes, sec / 60)
}

@Composable
fun SecuritySettingsScreen(vm: AppViewModel, nav: NavHostController) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    var setup by remember { mutableStateOf<String?>(null) } // "enable" | "change"
    var verify by remember { mutableStateOf<String?>(null) } // action needing current PIN: "change" | "disable"
    val secure = vm.container.secure
    val bioOk = biometricAvailable(ctx)
    val enabledMsg = stringResource(R.string.pin_enabled)
    val changedMsg = stringResource(R.string.pin_changed)

    Box(Modifier.fillMaxSize()) {
        AppScaffold(title = stringResource(R.string.security), onBack = { nav.popBackStack() }) { pad ->
            Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SectionCard(stringResource(R.string.app_lock)) {
                    SwitchRow(stringResource(R.string.enable_pin), s.lockEnabled && secure.hasPin, { on ->
                        if (on) setup = "enable" else verify = "disable"
                    }, stringResource(R.string.enable_pin_desc))
                    if (s.lockEnabled && secure.hasPin) {
                        NavRow(stringResource(R.string.change_pin), Icons.Filled.Password) { verify = "change" }
                        SwitchRow(stringResource(R.string.biometric_unlock), s.biometricEnabled && bioOk, { on ->
                            if (on) showBiometric(ctx, ctx.getString(R.string.biometric_unlock), ctx.getString(R.string.cancel)) { vm.updateSettings { it.copy(biometricEnabled = true) } }
                            else vm.updateSettings { it.copy(biometricEnabled = false) }
                        }, stringResource(if (bioOk) R.string.biometric_desc else R.string.biometric_unavailable), enabled = bioOk)
                        DropdownField(stringResource(R.string.auto_lock), listOf(0, 30, 60, 300, 900), s.autoLockSeconds, labelOf = { autoLockLabel(it) },
                            onSelect = { v -> vm.updateSettings { it.copy(autoLockSeconds = v) } }, modifier = Modifier.padding(horizontal = 16.dp))
                    }
                }
                SectionCard(stringResource(R.string.privacy)) {
                    SwitchRow(stringResource(R.string.secure_screen), s.secureScreen, { v -> vm.updateSettings { it.copy(secureScreen = v) } }, stringResource(R.string.secure_screen_desc))
                }
                InfoBanner(stringResource(R.string.security_info), icon = Icons.Filled.Info)
            }
        }
        when {
            verify != null -> VerifyPin(vm, onOk = { val a = verify; verify = null
                if (a == "disable") { secure.clearPin(); vm.updateSettings { it.copy(lockEnabled = false, biometricEnabled = false) } } else setup = "change" },
                onCancel = { verify = null })
            setup != null -> PinSetup(stringResource(if (setup == "change") R.string.change_pin else R.string.set_pin), onDone = { pin ->
                secure.setPin(pin); vm.updateSettings { it.copy(lockEnabled = true) }; vm.unlocked()
                vm.toast(if (setup == "change") changedMsg else enabledMsg); setup = null
            }, onCancel = { setup = null })
        }
    }
}

@Composable
private fun VerifyPin(vm: AppViewModel, onOk: () -> Unit, onCancel: () -> Unit) {
    var pin by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val wrong = stringResource(R.string.wrong_pin)
    val fc = LocalFinanceColors.current
    val len = remember { vm.container.secure.pinLength.takeIf { it in 4..6 } ?: 6 }
    Box(Modifier.fillMaxSize().background(fc.header).clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}) {
        Column(Modifier.fillMaxSize().systemBarsPadding().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Text(stringResource(R.string.enter_current_pin), color = fc.onHeader, style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(16.dp))
            PinDots(pin.length, fc.onHeader, len)
            Text(error ?: " ", color = MaterialTheme.colorScheme.errorContainer)
            PinPad(true, fc.onHeader, onDigit = { d ->
                if (pin.length < len) pin += d
                if (pin.length == len) { if (vm.container.secure.verifyPin(pin)) onOk() else { error = wrong; pin = "" } }
            }, onDelete = { pin = pin.dropLast(1) })
            TextButton(onClick = onCancel) { Text(stringResource(R.string.cancel), color = fc.onHeader) }
        }
    }
}
