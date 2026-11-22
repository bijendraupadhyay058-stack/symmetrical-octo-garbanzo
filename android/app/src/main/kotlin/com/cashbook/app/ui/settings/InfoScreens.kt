package com.cashbook.app.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import com.cashbook.app.BuildConfig
import com.cashbook.app.R
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.SectionCard

/** Renders a string-array of alternating "## Heading" and paragraph entries. */
@Composable
private fun Article(title: String, arrayRes: Int, onBack: () -> Unit, footer: String? = null) {
    AppScaffold(title = title, onBack = onBack) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            stringArrayResource(arrayRes).forEach { line ->
                if (line.startsWith("## ")) Text(line.removePrefix("## "), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
                else Text(line, style = MaterialTheme.typography.bodyMedium)
            }
            if (footer != null) Text(footer, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable fun GuideScreen(nav: NavHostController) = Article(stringResource(R.string.user_guide), R.array.guide, { nav.popBackStack() })

@Composable fun PrivacyScreen(nav: NavHostController) = Article(stringResource(R.string.privacy_policy), R.array.privacy, { nav.popBackStack() })

@Composable
fun AboutScreen(nav: NavHostController) {
    AppScaffold(title = stringResource(R.string.about), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionCard {
                Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineSmall)
                Text(stringResource(R.string.version_x, BuildConfig.VERSION_NAME + " (" + BuildConfig.VERSION_CODE + ")"))
                Text(stringResource(R.string.about_tagline), style = MaterialTheme.typography.bodyMedium)
            }
            SectionCard(stringResource(R.string.about_tech)) {
                Text(stringResource(R.string.about_tech_text), style = MaterialTheme.typography.bodySmall)
            }
            SectionCard(stringResource(R.string.about_disclaimer_title)) {
                Text(stringResource(R.string.about_disclaimer), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
