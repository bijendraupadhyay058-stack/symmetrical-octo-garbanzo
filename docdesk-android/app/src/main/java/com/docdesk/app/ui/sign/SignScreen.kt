package com.docdesk.app.ui.sign

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
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
import com.docdesk.app.sign.DigitalSigner
import com.docdesk.app.sign.SignOptions
import com.docdesk.app.sign.SignatureReport
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.ConfirmDialog
import com.docdesk.app.ui.components.FileHeader
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
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
import java.io.File
import java.text.DateFormat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private fun certDir() = File(DocDeskApp.instance.filesDir, "certs").apply { mkdirs() }

/** Digital (certificate) signatures: sign PDFs and check signatures on received PDFs. */
@Composable
fun SignScreen(nav: Nav, input: Uri?) {
    val app = DocDeskApp.instance
    val scope = rememberCoroutineScope()
    val holder = remember { PdfInputHolder(scope, wantRenderer = false) }
    DisposableEffect(Unit) { onDispose { holder.close() } }
    LaunchedEffect(input) { if (input != null && holder.doc == null) holder.select(input) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { it?.let { u -> holder.select(u) } }
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var refresh by remember { mutableIntStateOf(0) }
    val certs = remember(refresh) { certDir().listFiles()?.filter { it.extension in setOf("p12", "pfx") }?.sortedBy { it.name } ?: emptyList() }
    var chosen by remember { mutableStateOf<File?>(null) }
    var creating by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<File?>(null) }
    var askPassword by remember { mutableStateOf(false) }
    var reason by remember { mutableStateOf("I approve this document") }
    var location by remember { mutableStateOf("") }
    var visible by remember { mutableStateOf(true) }
    var lastPage by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    var reports by remember { mutableStateOf<List<SignatureReport>?>(null) }
    LaunchedEffect(certs) { if (chosen == null || chosen !in certs) chosen = certs.firstOrNull() }

    val importer = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u ->
        u ?: return@rememberLauncherForActivityResult
        scope.launch {
            val d = app.files.describe(u)
            val name = FileRepository.sanitize(d.name).let { if (it.endsWith(".p12", true) || it.endsWith(".pfx", true)) it else "$it.p12" }
            runCatching { withContext(Dispatchers.IO) { app.contentResolver.openInputStream(u)!!.use { i -> FileRepository.unique(certDir(), name).outputStream().use { i.copyTo(it) } } } }
                .onSuccess { info = "Certificate imported. You'll enter its password when signing."; refresh++ }.onFailure { error = it.userMessage() }
        }
    }

    // Check existing signatures whenever a PDF is opened.
    LaunchedEffect(holder.info) {
        reports = null
        val d = holder.doc ?: return@LaunchedEffect
        if (holder.info == null || holder.info!!.encrypted) return@LaunchedEffect
        reports = withContext(Dispatchers.IO) {
            runCatching {
                val f = app.files.newWorkFile(".pdf")
                try { app.contentResolver.openInputStream(d.uri)!!.use { i -> f.outputStream().use { i.copyTo(it) } }; DigitalSigner.verify(f) } finally { f.delete() }
            }.getOrNull()
        }
    }

    ToolScaffold("Digital signature", nav::back) {
        holder.error?.let { Notice(it, NoteKind.ERROR) }
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        info?.let { Notice(it) { info = null } }
        val d = holder.doc; val pinfo = holder.info
        if (d == null || pinfo == null) {
            if (holder.loading) Text("Opening…") else FilePickTarget("Choose a PDF to sign or check", "Certificate-based signatures that Adobe Acrobat can verify", Icons.Default.VerifiedUser) { picker.launch(arrayOf("application/pdf")) }
            Notice("A digital signature proves who signed and that the document has not changed since. It is different from a drawn signature (Edit PDF › Signature), which is only a picture. You need a certificate: import your .pfx/.p12 file, or create a personal certificate here.")
            return@ToolScaffold
        }
        FileHeader(d.name, "${pinfo.pageCount} pages", Icons.Default.PictureAsPdf) { picker.launch(arrayOf("application/pdf")) }

        reports?.let { list ->
            SectionCard("Signatures in this PDF") {
                if (list.isEmpty()) Text("This PDF has no digital signatures.", style = MaterialTheme.typography.bodyMedium)
                list.forEachIndexed { i, r ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(if (r.intact) Icons.Default.Verified else Icons.Default.VerifiedUser, null, tint = if (r.intact && r.coversWholeFile) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                        Text("${i + 1}. ${r.signer}", Modifier.padding(start = 8.dp), style = MaterialTheme.typography.titleSmall)
                    }
                    r.date?.let { Text("Signed: ${DateFormat.getDateTimeInstance().format(it)}", style = MaterialTheme.typography.bodySmall) }
                    listOfNotNull(r.reason?.let { "Reason: $it" }, r.location?.let { "Location: $it" }).forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                    Text(when {
                        r.problem != null -> r.problem
                        !r.intact -> "✗ INVALID – the signed content has been altered or the signature is damaged."
                        r.coversWholeFile -> "✓ Document unchanged since this signature."
                        else -> "✓ Signature intact. The document was updated after this signature (e.g. later signatures or annotations) – compare versions if unsure."
                    }, style = MaterialTheme.typography.bodyMedium)
                    Text(if (r.selfSigned) "Identity: personal (self-signed) certificate – the app cannot confirm who this is." else "Certificate issued by ${r.issuer}. DocDesk does not check it against official trust lists; verify in Adobe Acrobat for legal purposes.", style = MaterialTheme.typography.bodySmall)
                    if (r.certValidAtSigning == false) Text("⚠ The certificate was not valid on the signing date.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }
        }

        if (pinfo.encrypted) { Notice("This PDF is password-protected. Remove the protection (save a copy without password) before signing.", NoteKind.WARNING); return@ToolScaffold }

        SectionCard("Your certificate") {
            if (certs.isEmpty()) Text("No certificate yet.", style = MaterialTheme.typography.bodyMedium)
            certs.forEach { f ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        RadioOptions(listOf(f), chosen ?: f, { it.nameWithoutExtension }) { chosen = it }
                    }
                    IconButton(onClick = { deleting = f }) { Icon(Icons.Default.Delete, "Delete certificate ${f.nameWithoutExtension}") }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SecondaryAction("Import .pfx/.p12", icon = Icons.Default.Key, modifier = Modifier.weight(1f)) { importer.launch(arrayOf("application/x-pkcs12", "application/octet-stream", "*/*")) }
                SecondaryAction("Create personal", modifier = Modifier.weight(1f)) { creating = true }
            }
            Text("Certificates are stored only in DocDesk's private storage and are protected by their password.", style = MaterialTheme.typography.bodySmall)
        }
        SectionCard("Signature details") {
            OutlinedTextField(reason, { reason = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Reason") })
            OutlinedTextField(location, { location = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Location (optional)") })
            SwitchRow("Show a signature box on the page", visible, "Bottom-right corner, with your name, date and reason.") { visible = it }
            if (visible) RadioOptions(listOf(true, false), lastPage, { if (it) "On the last page" else "On the first page" }) { lastPage = it }
        }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Sign digitally", enabled = chosen != null && job == null, icon = Icons.Default.VerifiedUser) { askPassword = true }
    }
    PasswordPromptFor(holder)
    if (askPassword) CertPasswordDialog(chosen?.nameWithoutExtension ?: "", onDismiss = { askPassword = false }) { pw ->
        askPassword = false
        val d = holder.doc ?: return@CertPasswordDialog; val cert = chosen ?: return@CertPasswordDialog
        val opts = SignOptions(reason, location, visible, if (lastPage) (holder.info?.pageCount ?: 1) - 1 else 0)
        Operations.run("Digital signature", onError = { error = it }, onResult = nav.resultCallback()) { p ->
            p.step("Opening certificate…", 0.1f)
            val id = DigitalSigner.loadIdentity(cert, pw.toCharArray())
            if (id.cert.notAfter.before(java.util.Date())) throw OperationFailed("This certificate expired on ${DateFormat.getDateInstance().format(id.cert.notAfter)}.")
            p.step("Signing…", 0.5f)
            val src = app.files.newWorkFile(".pdf")
            try {
                app.contentResolver.openInputStream(d.uri)!!.use { i -> src.outputStream().use { i.copyTo(it) } }
                val out = app.files.newOutputFile(FileRepository.baseName(d.name) + " (signed).pdf")
                val notes = DigitalSigner.sign(src, out, id, opts, app.files.workDir)
                val check = DigitalSigner.verify(out).lastOrNull()
                val ok = check?.intact == true && check.coversWholeFile
                OperationResult(OperationReport("Digital signature", listOf(d.name), if (ok) Outcome.SUCCESS else Outcome.FAILED,
                    warnings = if (ok) emptyList() else listOf("The signature could not be verified after signing. Do not rely on this file."),
                    notes = listOf("Signed by ${id.commonName} using SHA-256. Verified immediately after signing: ${if (ok) "valid" else "NOT valid"}.") + notes),
                    listOf(OutputFile(out)), Preview.Pdf(out))
            } finally { src.delete() }
        }
    }
    if (creating) CreateCertDialog(onDismiss = { creating = false }) { name, email, org, pw ->
        creating = false
        scope.launch {
            runCatching { withContext(Dispatchers.Default) { DigitalSigner.createSelfSigned(FileRepository.unique(certDir(), FileRepository.sanitize("$name.p12")), name, email, org, pw.toCharArray()) } }
                .onSuccess { info = "Personal certificate created for $name (valid 3 years). Remember its password – it cannot be recovered."; refresh++ }
                .onFailure { error = it.userMessage() }
        }
    }
    deleting?.let { f -> ConfirmDialog("Delete certificate?", "\"${f.nameWithoutExtension}\" will be removed from DocDesk. PDFs already signed stay valid. If it was created here and you have no copy, you can't sign as this identity again.", "Delete",
        onConfirm = { f.delete(); deleting = null; refresh++ }, onDismiss = { deleting = null }) }
}

@Composable
private fun CertPasswordDialog(name: String, onDismiss: () -> Unit, onOk: (String) -> Unit) {
    var pw by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Certificate password") },
        text = { OutlinedTextField(pw, { pw = it }, label = { Text("Password for $name") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)) },
        confirmButton = { TextButton(onClick = { onOk(pw) }, enabled = pw.isNotEmpty()) { Text("Sign") } }, dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } })
}

@Composable
private fun CreateCertDialog(onDismiss: () -> Unit, onOk: (String, String, String, String) -> Unit) {
    var name by remember { mutableStateOf("") }; var email by remember { mutableStateOf("") }; var org by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf("") }; var pw2 by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Create personal certificate") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("For internal approvals and proving a file is unchanged. It is not a government-recognised DSC.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(name, { name = it }, label = { Text("Your full name") }, singleLine = true)
                OutlinedTextField(email, { email = it }, label = { Text("Email (optional)") }, singleLine = true)
                OutlinedTextField(org, { org = it }, label = { Text("Organisation (optional)") }, singleLine = true)
                val kb = KeyboardOptions(keyboardType = KeyboardType.Password)
                OutlinedTextField(pw, { pw = it }, label = { Text("Password (min 6)") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = kb)
                OutlinedTextField(pw2, { pw2 = it }, label = { Text("Repeat password") }, singleLine = true, isError = pw2.isNotEmpty() && pw != pw2, visualTransformation = PasswordVisualTransformation(), keyboardOptions = kb)
            }
        },
        confirmButton = { TextButton(onClick = { onOk(name.trim(), email.trim(), org.trim(), pw) }, enabled = name.isNotBlank() && pw.length >= 6 && pw == pw2) { Text("Create") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } })
}

