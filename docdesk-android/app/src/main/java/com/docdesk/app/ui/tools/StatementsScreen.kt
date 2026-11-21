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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OcrMode
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.PdfToExcelEngine
import com.docdesk.app.convert.Preview
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
import com.docdesk.app.ui.components.Operations
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
import com.docdesk.core.XlsxWriter

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
            Notice("Creates a standard layout: Date · Narration · Reference · Debit · Credit · Balance · Source file. Rows from all statements are sorted by date; each file's balances are checked; transactions that appear in two overlapping statements are flagged (not removed). For unusual layouts use PDF to Excel, where you can review every cell.")
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
        PrimaryAction("Create Excel", enabled = vm.files.allReady && job == null, icon = Icons.Default.AccountBalance) {
            val items = vm.files.items.map { Triple(it.doc, it.password, it.pages!!) }
            val ocr = vm.ocrMode; val lang: OcrLanguage = settings.ocrLanguage; val wantCsv = vm.csv; val name = vm.name.ifBlank { "Bank statements" }
            val wantSummaries = vm.summaries; val wantTally = vm.tally
            val rulesText = vm.rules ?: settings.ledgerRules
            val bank = (vm.bankLedger ?: settings.tallyBankLedger).trim(); val deflt = (vm.defaultLedger ?: settings.tallyDefaultLedger).trim().ifEmpty { "Suspense A/c" }
            if (wantTally && bank.isEmpty()) { vm.error = "Enter your bank ledger name exactly as it appears in Tally."; return@PrimaryAction }
            scope.launch { app.settings.setTally(rulesText, bank.ifEmpty { settings.tallyBankLedger }, deflt) }
            val rules = com.docdesk.core.LedgerRule.parse(rulesText)
            Operations.run("Bank statements to Excel", onError = { vm.error = it }, onResult = nav.resultCallback()) { p ->
                p.allowPartialResults()
                val per = mutableListOf<Pair<String, NormalizedStatement>>()
                val failed = mutableListOf<PageIssue>()
                val warnings = mutableListOf<String>()
                var cancelled = false
                items.forEachIndexed { i, (d, pw, pages) ->
                    if (p.cancelRequested) { cancelled = true; return@forEachIndexed }
                    p.step("Reading ${d.name} (${i + 1} of ${items.size})", i.toFloat() / items.size * 0.85f)
                    try {
                        val ex = PdfToExcelEngine.extract(app, d.uri, pw, (0 until pages).toList(), ocr, lang, TableOptions(style, order), app.files.workDir, p)
                        ex.failed.forEach { f -> failed.add(f.copy(message = "${d.name}: ${f.message}")) }
                        val n = StatementNormalizer.normalize(ex.tables, style, order, d.name)
                        if (n == null || n.rows.isEmpty()) failed.add(PageIssue(i + 1, "${d.name}: transaction columns (date, debit/credit or amount) were not recognised. Use PDF to Excel for this file."))
                        else { per.add(d.name to n); if (ex.ocrWords > 0) warnings.add("${d.name}: read with OCR – check amounts carefully.") }
                    } catch (e: Exception) {
                        if (e is com.docdesk.app.jobs.OperationCancelled) throw e
                        failed.add(PageIssue(i + 1, "${d.name}: ${e.userMessage()}"))
                    }
                }
                if (per.isEmpty()) throw OperationFailed("No transactions could be read. " + failed.joinToString("; ") { it.message })
                p.step("Combining and checking…", 0.9f)
                val rows = StatementNormalizer.combine(per.map { it.second })
                val sheets = StatementNormalizer.toSheets(rows, per) + if (wantSummaries) com.docdesk.core.StatementAnalysis.sheets(rows, rules) else emptyList()
                val xlsx = app.files.newOutputFile("$name.xlsx")
                xlsx.outputStream().buffered().use { XlsxWriter.write(sheets, it) }
                val outputs = mutableListOf(OutputFile(xlsx))
                if (wantCsv) { val c = app.files.newOutputFile("$name.csv"); c.writeText(StatementNormalizer.toCsv(rows)); outputs.add(OutputFile(c)) }
                val tallyNotes = mutableListOf<String>()
                if (wantTally) {
                    val t = com.docdesk.core.TallyXml.build(rows, com.docdesk.core.TallyXml.Options(bank, deflt, rules = rules))
                    val x = app.files.newOutputFile("$name (Tally import).xml"); x.writeText(t.xml); outputs.add(OutputFile(x))
                    tallyNotes.add("Tally XML: ${t.vouchers} voucher(s); ${t.suspense} posted to \"$deflt\" (no rule matched)" + if (t.skipped > 0) "; ${t.skipped} row(s) skipped (no date or unclear debit/credit)." else ".")
                    tallyNotes.add("Import into a test company first. Ledgers must already exist in Tally with exactly these names.")
                }
                val checks = per.map { (n, st) ->
                    val m = StatementNormalizer.balanceMismatches(st.rows)
                    "$n: ${st.rows.size} transactions; " + when { m == null -> "no balance column"; m.isEmpty() -> "running balance reconciles"; else -> "${m.size} row(s) don't reconcile (rows ${m.take(8).joinToString()})" }
                }
                val flagged = rows.count { it.flags.isNotEmpty() }
                if (flagged > 0) warnings.add("$flagged row(s) need review – see the Review column (highlighted).")
                OperationResult(OperationReport("Bank statements to Excel", items.map { it.first.name },
                    when { cancelled -> Outcome.CANCELLED; failed.isNotEmpty() -> Outcome.PARTIAL; else -> Outcome.SUCCESS },
                    failedPages = failed, warnings = warnings, checks = checks + Limitations.FINANCIAL,
                    notes = listOf("${rows.size} transactions from ${per.size} statement(s), sorted by date.") + tallyNotes + per.flatMap { it.second.notes.map { n -> "${it.first}: $n" } }),
                    outputs, Preview.Sheets(sheets))
            }
        }
        Text(Limitations.GENERAL, style = MaterialTheme.typography.bodySmall)
    }
}
