package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Compare
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.CompareEngine
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold

/** Compare two versions of a PDF (agreements, statements, quotations). */
@Composable
fun CompareScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val old = remember { PdfInputHolder(scope, wantRenderer = false) }
    val new = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { old.close(); new.close() } }
    LaunchedEffect(input) { if (input != null && old.doc == null) old.select(input) }
    val pickOld = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> old.select(u) } }
    val pickNew = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> new.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var ignoreCase by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    val pdf = arrayOf("application/pdf")

    ToolScaffold("Compare PDFs", nav::back) {
        listOf(old.error, new.error, error).filterNotNull().forEach { Notice(it, NoteKind.ERROR) }
        Text("Finds what changed between two versions – for example a draft and a final agreement.")
        val o = old.doc; val n = new.doc
        if (o == null) FilePickTarget("1. Choose the ORIGINAL (older) PDF", "", Icons.Default.PictureAsPdf) { pickOld.launch(pdf) }
        else FileHeader(o.name, "Original · ${old.info?.pageCount ?: "…"} pages", Icons.Default.PictureAsPdf) { pickOld.launch(pdf) }
        if (n == null) FilePickTarget("2. Choose the NEW (changed) PDF", "", Icons.Default.PictureAsPdf) { pickNew.launch(pdf) }
        else FileHeader(n.name, "New version · ${new.info?.pageCount ?: "…"} pages", Icons.Default.PictureAsPdf) { pickNew.launch(pdf) }
        SwitchRow("Ignore capital/small letters", ignoreCase) { ignoreCase = it }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Compare", enabled = old.ready && new.ready && job == null, icon = Icons.Default.Compare) {
            val od = old.doc!!; val nd = new.doc!!; val op = old.password; val np = new.password; val ic = ignoreCase
            Operations.run("Compare PDFs", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                CompareEngine.compare(app, od, op, nd, np, ic, { app.files.newOutputFile(it) }, p)
            }
        }
        Notice("Works on text-based PDFs. Scanned pages must be made searchable first. Only text is compared, not images or layout.")
    }
    PasswordPromptFor(old)
    PasswordPromptFor(new)
}
