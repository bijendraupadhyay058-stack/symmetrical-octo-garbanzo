package com.cashbook.app

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.cashbook.app.ui.AppRoot
import com.cashbook.app.ui.AppViewModel
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    // Explicit factory: uses this activity's Application rather than a process-wide cached one.
    private val vm: AppViewModel by viewModels { viewModelFactory { initializer { AppViewModel(application) } } }

    private val processObserver = object : DefaultLifecycleObserver {
        override fun onStop(owner: LifecycleOwner) = vm.onAppBackground()
        override fun onStart(owner: LifecycleOwner) = vm.onAppForeground()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        ProcessLifecycleOwner.get().lifecycle.addObserver(processObserver)
        intent?.getStringExtra(EXTRA_OPEN)?.let { vm.requestOpen(it) }
        lifecycleScope.launch {
            vm.settings.collect { s ->
                if (s?.secureScreen == true) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
            }
        }
        setContent { AppRoot(vm) }
    }

    /** Widget buttons and notifications re-use the running activity (singleTop). */
    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_OPEN)?.let { vm.requestOpen(it) }
    }

    override fun onDestroy() {
        ProcessLifecycleOwner.get().lifecycle.removeObserver(processObserver)
        super.onDestroy()
    }

    companion object { const val EXTRA_OPEN = "open" }
}
