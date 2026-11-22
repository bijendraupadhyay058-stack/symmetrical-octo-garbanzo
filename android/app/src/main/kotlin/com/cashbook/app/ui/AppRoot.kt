package com.cashbook.app.ui

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cashbook.app.AppContainer
import com.cashbook.app.R
import com.cashbook.app.data.ThemeMode
import com.cashbook.app.ui.components.FullScreenMessage
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.UiFormat
import com.cashbook.app.ui.lock.LockScreen
import com.cashbook.app.ui.nav.MainNav
import com.cashbook.app.ui.onboarding.OnboardingScreen
import com.cashbook.app.ui.theme.CashbookTheme

@Composable
fun AppRoot(vm: AppViewModel, openTarget: String?) {
    val settings by vm.settings.collectAsStateWithLifecycle()
    val state by vm.state.collectAsStateWithLifecycle()
    val locked by vm.locked.collectAsStateWithLifecycle()
    val s = settings
    CashbookTheme(s?.theme ?: ThemeMode.SYSTEM) {
        CompositionLocalProvider(LocalUiFormat provides UiFormat(s?.currencyDisplay ?: com.cashbook.core.CurrencyDisplay.SYMBOL,
            s?.dateFormat ?: com.cashbook.core.DateFormatOption.DD_MM_YYYY)) {
            Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                when {
                    state is AppContainer.State.Failed -> StorageError()
                    s == null || state is AppContainer.State.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                    !s.onboarded -> OnboardingScreen(vm)
                    else -> Box(Modifier.fillMaxSize()) {
                        // The app stays composed underneath the lock so navigation and form state survive.
                        MainNav(vm, openTarget)
                        if (locked && s.lockEnabled) LockScreen(vm)
                    }
                }
            }
        }
    }
}

@Composable
private fun StorageError() {
    val ctx = LocalContext.current
    FullScreenMessage(stringResource(R.string.storage_error)) {
        Button(onClick = {
            ctx.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(android.net.Uri.fromParts("package", ctx.packageName, null)))
        }) { Text(stringResource(R.string.open_app_settings)) }
    }
}
