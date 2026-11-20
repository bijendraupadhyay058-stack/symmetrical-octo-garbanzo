package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.FieldKind
import com.docdesk.app.pdf.FormField
import com.docdesk.app.pdf.FormFiller
import com.docdesk.app.pdf.PdfAction
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfOps
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.Routes
import com.docdesk.app.ui.components.CheckRow
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Fill in interactive PDF forms (AcroForm): text fields, checkboxes, radio buttons, lists. */
@Composable
fun FillFormScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var fields by remember { mutableStateOf<List<FormField>?>(null) }
    val values = remember { mutableStateMapOf<String, String>() }
    var flatten by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(holder.info) {
        val d = holder.doc ?: return@LaunchedEffect
        if (holder.info == null) return@LaunchedEffect
        fields = null; values.clear()
        withContext(Dispatchers.IO) { runCatching { PdfDocs.open(app, d.uri, holder.password).use { FormFiller.read(it) } } }
            .onSuccess { list -> fields = list; list.forEach { values[it.name] = it.value } }
            .onFailure { error = it.userMessage() }
    }

    ToolScaffold("Fill form", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val info = holder.info
        if (d == null || info == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF form", "Fill in fields such as names, dates, amounts and tick boxes", Icons.Default.EditNote) { picker.launch(arrayOf("application/pdf")) }
            return@ToolScaffold
        }
        FileHeader(d.name, "${info.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val list = fields
        if (list == null) { Text("Reading form fields…"); return@ToolScaffold }
        val editable = list.filter { !it.readOnly && it.kind != FieldKind.SIGNATURE && it.kind != FieldKind.OTHER }
        if (editable.isEmpty()) {
            Notice("This PDF has no fillable form fields. To fill a flat (printed-style) form, use Edit PDF › Text box to type on it, and Signature to sign.", NoteKind.WARNING)
            SecondaryAction("Open in Edit PDF") { nav.to(Routes.EDIT, d.uri) }
            return@ToolScaffold
        }
        Text("${editable.size} field(s) to fill.", style = MaterialTheme.typography.bodyMedium)
        editable.groupBy { it.page }.toSortedMap(compareBy { it ?: Int.MAX_VALUE }).forEach { (pg, fs) ->
            SectionCard(if (pg != null) "Page ${pg + 1}" else "Fields") {
                fs.forEach { f ->
                    when (f.kind) {
                        FieldKind.TEXT -> OutlinedTextField(values[f.name] ?: "", { values[f.name] = it }, Modifier.fillMaxWidth(), label = { Text(f.label) }, singleLine = !f.multiline, minLines = if (f.multiline) 3 else 1)
                        FieldKind.CHECKBOX -> CheckRow(f.label, values[f.name] == "true") { values[f.name] = it.toString() }
                        FieldKind.RADIO, FieldKind.CHOICE -> {
                            var open by remember { mutableStateOf(false) }
                            Text(f.label, style = MaterialTheme.typography.labelLarge)
                            Box {
                                OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth()) { Text(values[f.name]?.takeIf { it.isNotBlank() && it != "Off" } ?: "Choose…") }
                                DropdownMenu(open, { open = false }) { f.options.forEach { o -> DropdownMenuItem(text = { Text(o) }, onClick = { values[f.name] = o; open = false }) } }
                            }
                        }
                        else -> Unit
                    }
                }
            }
        }
        if (list.any { it.kind == FieldKind.SIGNATURE }) Notice("This form has a digital signature field. Digital (certificate) signing is not supported; you can add a drawn signature with Edit PDF › Signature after filling.")
        SwitchRow("Flatten form after filling", flatten, "Makes the answers part of the page so they can't be changed. Leave off to keep the form editable.") { flatten = it }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Save filled form", enabled = job == null) {
            val changed = editable.filter { (values[it.name] ?: "") != it.value }.associate { it.name to (values[it.name] ?: "") }
            val pw = holder.password; val fl = flatten
            Operations.run("Fill form", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                p.step("Filling ${changed.size} field(s)…", 0.3f)
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (filled).pdf")
                val notes = mutableListOf("Saved as a new file; the original form was not changed.")
                val res = PdfDocs.open(app, d.uri, pw).use { doc ->
                    PdfDocs.require(doc, PdfAction.MODIFY)
                    val r = FormFiller.fill(doc, changed, fl)
                    PdfOps.keepProtectionForSave(doc, pw)?.let { notes.add(it) }
                    PdfOps.saveAtomically(doc, out); r
                }
                if (fl) notes.add("The form was flattened; answers can no longer be edited.")
                val warnings = if (res.failed.isEmpty()) emptyList() else listOf("Could not fill: ${res.failed.joinToString()}. The form's font may not support these characters (e.g. Hindi) – type them with Edit PDF › Text box instead.")
                OperationResult(OperationReport("Fill form", listOf(d.name), if (res.failed.isEmpty()) Outcome.SUCCESS else Outcome.PARTIAL, warnings = warnings,
                    notes = listOf("${res.filled} field(s) filled.") + notes), listOf(OutputFile(out)), Preview.Pdf(out))
            }
        }
    }
    PasswordPromptFor(holder)
}
