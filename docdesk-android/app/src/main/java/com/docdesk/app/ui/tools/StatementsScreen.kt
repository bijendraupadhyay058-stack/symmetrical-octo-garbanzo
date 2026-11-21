package com.docdesk.app.ui.tools

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import kotlinx.coroutines.launch
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.PdfToExcelEngine
import com.docdesk.app.data.AppSettings
import com.docdesk.app.jobs.OperationFailed
import com.docdesk.app.jobs.userMessage
import com.docdesk.app.ocr.OcrLanguage
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.FilePickTarget
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.MultiPdfList
import com.docdesk.app.ui.components.MultiPdfState
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SecondaryAction
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.SwitchRow
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.DateOrder
import com.docdesk.core.NormalizedStatement
import com.docdesk.core.NumberStyle
import com.docdesk.core.StatementNormalizer
import com.docdesk.core.TableOptions

class StatementsVm : ViewModel() {
    val files = MultiPdfState(viewModelScope)
    var numberStyle by mutableStateOf<NumberStyle?>(null)
    var dateOrder by mutableStateOf<DateOrder?>(null)
    var ocrMode by mutableStateOf(OcrMode.AUTO)
    var csv by mutableStateOf(true)
    var summaries by mutableStateOf(true)
    var tally by mutableStateOf(false)
    var bankLedger by mutableStateOf<String?>(null)
    var defaultLedger by mutableStateOf<String?>(null)
    var rules by mutableStateOf<String?>(null)
    var name by mutableStateOf("Bank statements")
    var pageRange by mutableStateOf("")
    var error by mutableStateOf<String?>(null)
}

/** Several bank statements → one standard transaction list (Excel + CSV) with checks. */
@Composable
fun StatementsScreen(nav: Nav, input: Uri?) {
    val vm: StatementsVm = viewModel()
    val app = DocDeskApp.instance
    val settings by app.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val job by app.jobs.state.collectAsStateWithLifecycle()
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    LaunchedEffect(input) { if (input != null && vm.files.items.isEmpty()) vm.files.add(listOf(input)) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.files.add(it) }
    val style = vm.numberStyle ?: settings.numberStyle
    val order = vm.dateOrder ?: settings.dateOrder

    ToolScaffold("Bank statements to Excel", nav::back) {
        vm.error?.let { Notice(it, NoteKind.ERROR) { vm.error = null } }
        vm.files.skipped?.let { Notice(it, NoteKind.WARNING) { vm.files.skipped = null } }
        if (vm.files.items.isEmpty()) {
            FilePickTarget("Choose one or more bank statements", "e.g. April to March – combined into one Excel sheet", Icons.Default.AccountBalance) { picker.launch(arrayOf("application/pdf")) }
            Notice("You review every transaction before export: DocDesk shows each row next to its source page, checks opening + credits − debits against the closing balance and the running balance, flags doubtful values and possible duplicates, and suggests categories you can change. The Excel file has Transactions, Monthly Summary, Category Summary, Reconciliation, Exceptions and Processing Report sheets. For unusual layouts use PDF to Excel.")
            return@ToolScaffold
        }
        SectionCard("${vm.files.items.size} statement(s)") {
            MultiPdfList(vm.files)
            SecondaryAction("Add statements", icon = Icons.Default.Add) { picker.launch(arrayOf("application/pdf")) }
        }
        SectionCard("Formats") {
            RadioOptions(NumberStyle.entries, style, { it.label }) { vm.numberStyle = it }
            RadioOptions(DateOrder.entries, order, { it.label }) { vm.dateOrder = it }
        }
        SectionCard("Scanned statements") { RadioOptions(OcrMode.entries, vm.ocrMode, { it.label }) { vm.ocrMode = it } }
        SwitchRow("Also create a CSV file", vm.csv, "For Zoho Books, accounting or bank-reconciliation software.") { vm.csv = it }
        SwitchRow("Add month-wise, party-wise and category summaries", vm.summaries, "Extra sheets. Parties are read from UPI/NEFT/IMPS narrations; categories come from your keyword rules below.") { vm.summaries = it }
        val rulesText = vm.rules ?: settings.ledgerRules
        SwitchRow("Create Tally import file (XML)", vm.tally, "Payment / Receipt / Contra vouchers for Gateway of Tally › Import › Transactions.") { vm.tally = it }
        if (vm.tally || vm.summaries) SectionCard("Ledgers and rules") {
            if (vm.tally) {
                OutlinedTextField(vm.bankLedger ?: settings.tallyBankLedger, { vm.bankLedger = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Bank ledger name in Tally") }, placeholder = { Text("e.g. HDFC Bank A/c 1234") })
                OutlinedTextField(vm.defaultLedger ?: settings.tallyDefaultLedger, { vm.defaultLedger = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Ledger when no rule matches") })
            }
            OutlinedTextField(rulesText, { vm.rules = it }, Modifier.fillMaxWidth(), minLines = 5, label = { Text("Rules: keyword => ledger") })
            Text("First matching keyword (anywhere in the narration, any case) decides the ledger. A rule pointing to your cash ledger (\"Cash\") makes a Contra voucher. Ledger names must already exist in Tally. Import into a test company first.", style = MaterialTheme.typography.bodySmall)
        }
        OutlinedTextField(vm.name, { vm.name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("File name") })
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        OutlinedTextField(vm.pageRange, { vm.pageRange = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Pages (blank = all pages)") }, placeholder = { Text("e.g. 1-5, 8") },
            supportingText = { Text("Applies to each statement. Pages beyond a file's length are ignored for that file.") })
        PrimaryAction("Read statements and review", enabled = vm.files.allReady && job == null, icon = Icons.Default.AccountBalance) {
            val items = vm.files.items.map { Triple(it.doc, it.password, it.pages!!) }
            val ocr = vm.ocrMode; val lang: OcrLanguage = settings.ocrLanguage; val wantCsv = vm.csv; val name = vm.name.ifBlank { "Bank statements" }
            val wantSummaries = vm.summaries; val wantTally = vm.tally; val range = vm.pageRange.trim()
            val rulesText = vm.rules ?: settings.ledgerRules
            val bank = (vm.bankLedger ?: settings.tallyBankLedger).trim(); val deflt = (vm.defaultLedger ?: settings.tallyDefaultLedger).trim().ifEmpty { "Suspense A/c" }
            if (wantTally && bank.isEmpty()) { vm.error = "Enter your bank ledger name exactly as it appears in Tally."; return@PrimaryAction }
            if (range.isNotEmpty()) runCatching { com.docdesk.core.PageRanges.parse(range, 100000) }.onFailure { vm.error = "Pages: ${it.message}"; return@PrimaryAction }
            scope.launch { app.settings.setTally(rulesText, bank.ifEmpty { settings.tallyBankLedger }, deflt) }
            val rules = com.docdesk.core.LedgerRule.parse(rulesText)
            val started = app.jobs.start("Reading bank statements", { p ->
                val per = mutableListOf<NormalizedStatement>()
                val pageStatus = mutableListOf<com.docdesk.core.PageStatus>()
                val sources = LinkedHashMap<String, Pair<Uri, String?>>()
                val warnings = mutableListOf<String>()
                items.forEachIndexed { i, (d, pw, pages) ->
                    if (p.cancelRequested) throw com.docdesk.app.jobs.OperationCancelled()
                    // Unique name per file so rows, checks and source pages never mix up two files called the same.
                    var src = d.name; var k = 2; while (src in sources) src = "${d.name} ($k)".also { k++ }
                    sources[src] = d.uri to pw
                    val sel = if (range.isEmpty()) (0 until pages).toList() else com.docdesk.core.PageRanges.parse(range, 100000).filter { it < pages }.distinct()
                    if (sel.isEmpty()) { pageStatus.add(com.docdesk.core.PageStatus(src, 0, "–", "Not processed", "The page range doesn't include any page of this file ($pages pages)")); return@forEachIndexed }
                    p.step("Reading ${d.name} (${i + 1} of ${items.size})", i.toFloat() / items.size * 0.9f)
                    try {
                        val ex = PdfToExcelEngine.extract(app, d.uri, pw, sel, ocr, lang, TableOptions(style, order), app.files.workDir, p)
                        val failedP = ex.failed.associate { it.page to it.message }
                        for (pg in sel) {
                            val type = when (ex.sources[pg]) { com.docdesk.core.TextSource.PDF_TEXT -> "Text"; com.docdesk.core.TextSource.OCR -> "Scanned (read with OCR)"; com.docdesk.core.TextSource.NONE -> "No readable text"; null -> "Unknown" }
                            val (status, note) = when {
                                failedP.containsKey(pg + 1) -> "Failed" to failedP[pg + 1]!!
                                pg in ex.pagesWithoutTables -> "No transactions found" to "No table was recognised on this page – check it isn't missing transactions"
                                pg in ex.pagesDone -> "Processed" to ""
                                else -> "Not processed" to "Stopped before this page"
                            }
                            pageStatus.add(com.docdesk.core.PageStatus(src, pg + 1, type, status, note))
                        }
                        val n = StatementNormalizer.normalize(ex.tables, style, order, src)
                        if (n == null || n.rows.isEmpty()) pageStatus.add(com.docdesk.core.PageStatus(src, 0, "–", "Failed", "Transaction columns (date, debit/credit or amount) were not recognised. Use PDF to Excel for this file."))
                        else { per.add(n); if (ex.ocrWords > 0) warnings.add("$src: read with OCR – check amounts carefully.") }
                    } catch (e: Exception) {
                        if (e is com.docdesk.app.jobs.OperationCancelled) throw e
                        pageStatus.add(com.docdesk.core.PageStatus(src, 0, "–", "Failed", e.userMessage()))
                    }
                }
                if (per.isEmpty()) throw OperationFailed("No transactions could be read. " + pageStatus.filter { it.status == "Failed" }.joinToString("; ") { "${it.source}: ${it.note}" })
                p.step("Preparing review…", 0.95f)
                val session = com.docdesk.core.ReviewSession(per.flatMap { it.rows })
                val notes = listOf("Number format: ${style.label}", "Date format: ${order.label}", "Scanned pages: ${ocr.label}", "Pages: ${range.ifEmpty { "all" }}") +
                    per.flatMap { st -> st.notes.map { "${st.rows.firstOrNull()?.source}: $it" } }
                com.docdesk.app.ui.statements.StatementReview(session, sources, pageStatus, notes, name, style, order, wantCsv,
                    if (wantTally) com.docdesk.app.ui.statements.TallyChoice(bank, deflt) else null, rules, wantSummaries, items.map { it.first.name }, warnings)
            }) { r ->
                r.onSuccess { com.docdesk.app.ui.statements.StatementReviewStore.current = it; nav.to(com.docdesk.app.ui.Routes.STATEMENT_REVIEW) }
                    .onFailure { if (it !is com.docdesk.app.jobs.OperationCancelled) vm.error = it.userMessage() }
            }
            if (!started) vm.error = "Another operation is still running. Wait for it to finish or cancel it from the Home screen."
        }
        if (com.docdesk.app.ui.statements.StatementReviewStore.current != null && job == null)
            SecondaryAction("Return to the open review") { nav.to(com.docdesk.app.ui.Routes.STATEMENT_REVIEW) }
        Text(Limitations.GENERAL, style = MaterialTheme.typography.bodySmall)
    }
}
