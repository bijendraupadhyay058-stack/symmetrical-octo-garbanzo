package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.Preview
import com.docdesk.app.data.FileRepository
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.pdf.Allowed
import com.docdesk.app.pdf.PasswordRequiredException
import com.docdesk.app.pdf.PdfDocs
import com.docdesk.app.pdf.PdfSecurity
import com.docdesk.app.pdf.SecurityInfo
import com.docdesk.app.pdf.Strength
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.CheckRow
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.KeyValue
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PasswordPromptFor
import com.docdesk.app.ui.components.PdfInputHolder
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
private fun PasswordField(value: String, onChange: (String) -> Unit, label: String, isError: Boolean = false, help: String? = null) {
    var show by remember { mutableStateOf(false) }
    OutlinedTextField(value, onChange, Modifier.fillMaxWidth(), singleLine = true, label = { Text(label) }, isError = isError,
        supportingText = help?.let { { Text(it) } },
        visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        trailingIcon = { IconButton(onClick = { show = !show }) { Icon(if (show) Icons.Default.VisibilityOff else Icons.Default.Visibility, if (show) "Hide password" else "Show password") } })
}

/** Protect (encrypt) a PDF or remove its password. [unlock] selects the mode. */
@Composable
fun SecurityScreen(nav: Nav, input: Uri?, unlock: Boolean) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var info by remember { mutableStateOf<SecurityInfo?>(null) }
    // Password that gives full (owner) rights: needed to remove or change existing protection.
    var ownerPw by remember { mutableStateOf<String?>(null) }
    var permEntry by remember { mutableStateOf("") }
    var permWrong by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    // Protect options
    var requireOpen by remember { mutableStateOf(true) }
    var openPw by remember { mutableStateOf("") }; var openPw2 by remember { mutableStateOf("") }
    var restrict by remember { mutableStateOf(false) }
    var permPw by remember { mutableStateOf("") }
    var allowed by remember { mutableStateOf(Allowed()) }
    var strength by remember { mutableStateOf(Strength.AES256) }

    LaunchedEffect(holder.info) {
        info = null; ownerPw = null; permEntry = ""; permWrong = false
        val d = holder.doc ?: return@LaunchedEffect
        if (holder.info == null) return@LaunchedEffect
        withContext(Dispatchers.IO) { runCatching { PdfDocs.open(app, d.uri, holder.password).use { PdfSecurity.describe(it) } } }
            .onSuccess { info = it; if (it.ownerRights) ownerPw = holder.password ?: "" }
            .onFailure { error = it.userMessage() }
    }

    fun tryPermissionsPassword() {
        val d = holder.doc ?: return
        scope.launch {
            val ok = withContext(Dispatchers.IO) {
                runCatching { PdfDocs.open(app, d.uri, permEntry).use { it.currentAccessPermission.isOwnerPermission } }.getOrElse { if (it is PasswordRequiredException) false else { error = it.userMessage(); false } }
            }
            if (ok) { ownerPw = permEntry; permWrong = false } else permWrong = true
        }
    }

    ToolScaffold(if (unlock) "Remove password" else "Protect PDF", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        val d = holder.doc; val pinfo = holder.info
        if (d == null || pinfo == null) {
            if (holder.loading) Text("Opening…")
            else if (unlock) FilePickTarget("Choose a protected PDF", "You'll need its password", Icons.Default.LockOpen) { picker.launch(arrayOf("application/pdf")) }
            else FilePickTarget("Choose a PDF to protect", "Add a password and choose what others may do", Icons.Default.Lock) { picker.launch(arrayOf("application/pdf")) }
            Notice(if (unlock) "Removes the open password and the restrictions from a PDF, creating an unprotected copy. You must know the password – DocDesk never bypasses passwords. If the author restricted printing/copying, the permissions password is needed."
                else "Encrypts a copy of the PDF. An open password is needed to view it; a permissions password controls printing, copying and editing. The original stays unchanged.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pinfo.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }
        val si = info
        if (si == null) { Text("Checking protection…"); return@ToolScaffold }
        SectionCard("Current protection") {
            KeyValue("Encryption", si.method)
            KeyValue("Open password", if (!si.encrypted) "No" else if (!holder.password.isNullOrEmpty()) "Yes (entered)" else "No")
            if (si.restrictions.isEmpty()) KeyValue("Restrictions", if (si.encrypted && !si.ownerRights) "–" else "None")
            else si.restrictions.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) }
        }
        if (si.encrypted && ownerPw == null) {
            SectionCard("Permissions password needed") {
                Text("This PDF has restrictions set by its author. To ${if (unlock) "remove them" else "change its protection"}, enter the permissions (owner) password.", style = MaterialTheme.typography.bodyMedium)
                PasswordField(permEntry, { permEntry = it; permWrong = false }, "Permissions password", isError = permWrong, help = if (permWrong) "That is not the permissions password." else null)
                SecondaryAction("Check password", enabled = permEntry.isNotEmpty()) { tryPermissionsPassword() }
            }
            return@ToolScaffold
        }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        if (unlock) {
            if (!si.encrypted) { Notice("This PDF has no password or restrictions – nothing to remove."); return@ToolScaffold }
            PrimaryAction("Remove password", enabled = job == null, icon = Icons.Default.LockOpen) {
                val pw = ownerPw
                Operations.run("Remove password", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                    p.step("Removing protection…", 0.5f)
                    val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (unlocked).pdf")
                    PdfDocs.open(app, d.uri, pw).use { doc -> PdfSecurity.removeAll(doc, out) }
                    OperationResult(OperationReport("Remove password", listOf(d.name), Outcome.SUCCESS,
                        notes = listOf("An unprotected copy was created; the original is unchanged.", "Anyone with this copy can open, print and copy it. Store and share it carefully.")),
                        listOf(OutputFile(out)), Preview.Pdf(out))
                }
            }
        } else {
            SectionCard("Open password") {
                SwitchRow("Require a password to open", requireOpen) { requireOpen = it }
                if (requireOpen) {
                    PasswordField(openPw, { openPw = it }, "Open password (min 6 characters)")
                    PasswordField(openPw2, { openPw2 = it }, "Repeat open password", isError = openPw2.isNotEmpty() && openPw != openPw2)
                }
            }
            SectionCard("Permissions") {
                SwitchRow("Restrict printing, copying and editing", restrict, "Others can open the PDF but only do what you allow below.") { restrict = it }
                if (restrict) {
                    CheckRow("Allow printing", allowed.print) { allowed = allowed.copy(print = it) }
                    CheckRow("Allow copying text and images", allowed.copy) { allowed = allowed.copy(copy = it) }
                    CheckRow("Allow editing", allowed.edit) { allowed = allowed.copy(edit = it) }
                    CheckRow("Allow comments and annotations", allowed.comment) { allowed = allowed.copy(comment = it) }
                    CheckRow("Allow filling forms and signing", allowed.fillForms) { allowed = allowed.copy(fillForms = it) }
                    CheckRow("Allow page changes (insert, delete, rotate)", allowed.assemble) { allowed = allowed.copy(assemble = it) }
                    PasswordField(permPw, { permPw = it }, "Permissions password (min 6)", isError = permPw.isNotEmpty() && permPw == openPw,
                        help = if (permPw.isNotEmpty() && permPw == openPw) "Use a different password from the open password, otherwise anyone who can open the file can change the permissions." else "Needed later to change or remove the restrictions.")
                    Text("Note: restrictions are respected by Adobe Reader and most PDF apps, but some apps ignore them. Use an open password for real confidentiality.", style = MaterialTheme.typography.bodySmall)
                }
            }
            SectionCard("Encryption") { RadioOptions(Strength.entries, strength, { it.label }, { it.help }) { strength = it } }
            val openOk = !requireOpen || (openPw.length >= 6 && openPw == openPw2)
            val permOk = !restrict || (permPw.length >= 6 && permPw != openPw)
            val something = requireOpen || restrict
            if (!something) Notice("Choose an open password, restrictions, or both.", NoteKind.WARNING)
            Notice("Keep your passwords safe: DocDesk can't recover them and nobody can open a forgotten open password.", NoteKind.WARNING)
            PrimaryAction("Protect PDF", enabled = job == null && something && openOk && permOk, icon = Icons.Default.Lock) {
                val src = ownerPw; val op = if (requireOpen) openPw else ""; val pp = if (restrict) permPw else null; val al = allowed; val st = strength
                Operations.run("Protect PDF", onError = { error = it }, onResult = nav.resultCallback()) { p ->
                    p.step("Encrypting with ${st.label}…", 0.5f)
                    val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (protected).pdf")
                    PdfDocs.open(app, d.uri, src).use { doc -> PdfSecurity.protect(doc, out, op, pp, al, st) }
                    // Verify: the result must refuse to open without the password and open with it.
                    if (op.isNotEmpty()) {
                        val locked = runCatching { PdfDocs.open(out).close(); false }.getOrElse { it is PasswordRequiredException }
                        if (!locked) throw OperationFailed("Verification failed: the protected file opened without a password. It was not saved.")
                    }
                    PdfDocs.open(out, op).use { check(it.isEncrypted) }
                    val notes = mutableListOf("Encrypted with ${st.label}. The original is unchanged.")
                    if (op.isNotEmpty()) notes.add("Opening requires the open password.") else notes.add("Anyone can open it; the restrictions apply without the permissions password.")
                    if (pp != null) notes.add("Allowed without the permissions password: " + listOfNotNull("printing".takeIf { al.print }, "copying".takeIf { al.copy }, "editing".takeIf { al.edit }, "comments".takeIf { al.comment }, "forms".takeIf { al.fillForms }, "page changes".takeIf { al.assemble }).ifEmpty { listOf("viewing only") }.joinToString())
                    OperationResult(OperationReport("Protect PDF", listOf(d.name), Outcome.SUCCESS, notes = notes), listOf(OutputFile(out)), null)
                }
            }
        }
    }
    PasswordPromptFor(holder)
}
