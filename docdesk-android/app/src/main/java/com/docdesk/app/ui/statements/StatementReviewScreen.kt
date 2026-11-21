package com.docdesk.app.ui.statements

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.Limitations
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.Preview
import com.docdesk.app.pdf.PageRenderer
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PageImage
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.RadioOptions
import com.docdesk.app.ui.components.SectionCard
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.AmountParser
import com.docdesk.core.BankWorkbook
import com.docdesk.core.CheckStatus
import com.docdesk.core.DateParser
import com.docdesk.core.Reconciler
import com.docdesk.core.ReviewSession
import com.docdesk.core.ReviewTxn
import com.docdesk.core.StatementOrder
import com.docdesk.core.StatementRow
import com.docdesk.core.TxnCategory
import com.docdesk.core.XlsxWriter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.math.BigDecimal

private enum class Filter(val label: String) { ALL("All"), REVIEW("Needs review"), BREAKS("Balance breaks"), SUGGESTED("Suggested category") }

private fun fmt(v: BigDecimal?) = v?.let { AmountParser.formatIndian(it) } ?: ""

/** Review extracted transactions next to their source pages, correct them, check balances, then export. */
@Composable
fun StatementReviewScreen(nav: Nav) {
    val review = StatementReviewStore.current
    if (review == null) {
        ToolScaffold("Review statements", nav::back) {
            Notice("There is no statement review open. If Android closed DocDesk in the background, the review was discarded for privacy – read the statements again.", NoteKind.WARNING)
        }
        return
    }
    @Suppress("UNUSED_VARIABLE") val v = review.version // re-read the session after every change
    val s = review.session
    val app = DocDeskApp.instance
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }
    var filter by remember { mutableStateOf(Filter.ALL) }
    var selected by remember { mutableStateOf<Int?>(null) }
    var editing by remember { mutableStateOf<Int?>(null) }
    var confirmExport by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val recon = remember(review.version) { Reconciler.reconcile(s) }
    val failed = remember(review.version) { review.pages.filter { it.status != "Processed" }.map { it.source to "Page ${it.page}: ${it.status}" } }
    val exceptions = remember(review.version) { Reconciler.exceptions(s, recon, failed) }
    val breaks = recon.flatMap { it.runningBreaks }.toSet()
    val exRows = exceptions.mapNotNull { it.rowId }.toSet()

    fun rowsFor(f: Filter) = when (f) {
        Filter.ALL -> s.rows.toList()
        Filter.REVIEW -> s.rows.filter { it.id in exRows }
        Filter.BREAKS -> s.rows.filter { it.id in breaks }
        Filter.SUGGESTED -> s.rows.filter { it.categorySuggested }
    }

    ToolScaffold("Review statements", nav::back, scroll = false) {
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        BoxWithConstraints(Modifier.fillMaxWidth().weight(1f)) {
            val wide = maxWidth >= 840.dp
            val list: @Composable (Modifier) -> Unit = { m ->
                Column(m) {
                    @OptIn(ExperimentalLayoutApi::class)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Filter.entries.forEach { f -> FilterChip(filter == f, { filter = f }, label = { Text("${f.label} (${rowsFor(f).size})") }) }
                    }
                    val rows = rowsFor(filter)
                    if (rows.isEmpty()) Text("Nothing here.", Modifier.padding(12.dp))
                    LazyColumn(Modifier.fillMaxWidth().weight(1f)) {
                        items(rows, key = { it.id }) { r ->
                            TxnCard(r, r.id == selected, r.id in exRows, r.id in breaks) { selected = r.id; editing = r.id }
                        }
                    }
                }
            }
            if (wide) Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                list(Modifier.weight(1f))
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    SourcePage(review, selected?.let { id -> s.rows.firstOrNull { it.id == id } })
                    ChecksPanel(review, recon, exceptions.size)
                }
            } else Column(Modifier.fillMaxSize()) {
                TabRow(tab) {
                    listOf("Transactions", "Checks", "Source page").forEachIndexed { i, t -> Tab(tab == i, { tab = i }, text = { Text(t) }) }
                }
                when (tab) {
                    0 -> list(Modifier.weight(1f))
                    1 -> Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) { ChecksPanel(review, recon, exceptions.size) }
                    else -> Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) { SourcePage(review, selected?.let { id -> s.rows.firstOrNull { it.id == id } }) }
                }
            }
        }
        PrimaryAction("Export to Excel…", enabled = job == null, icon = Icons.Default.FileDownload) { confirmExport = true }
    }

    editing?.let { id ->
        val r = s.rows.firstOrNull { it.id == id }
        if (r == null) editing = null
        else EditDialog(review, r, onShowSource = { selected = id; editing = null; tab = 2 }, onClose = { editing = null })
    }
    if (confirmExport) {
        val incomplete = recon.flatMap { f -> f.lines.filter { it.status == CheckStatus.INCOMPLETE || it.status == CheckStatus.DIFFERENCE }.map { "${f.source}: ${it.label} – ${it.status.label}" } } +
            if (!s.orderConfirmed) listOf("Statement order not confirmed") else emptyList()
        val suggested = s.rows.count { it.categorySuggested }
        AlertDialog(
            onDismissRequest = { confirmExport = false },
            title = { Text("Ready to export?") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Text("${s.rows.size} transactions · ${exceptions.size} open exception(s) · ${s.audit.size} correction(s)")
                    if (exceptions.isNotEmpty()) { Spacer(Modifier.height(8.dp)); Text("Open exceptions", fontWeight = FontWeight.Bold)
                        exceptions.groupBy { it.kind }.forEach { (k, l) -> Text("• $k: ${l.size}") } }
                    if (incomplete.isNotEmpty()) { Spacer(Modifier.height(8.dp)); Text("Checks not complete", fontWeight = FontWeight.Bold); incomplete.take(12).forEach { Text("• $it") } }
                    if (suggested > 0) { Spacer(Modifier.height(8.dp)); Text("$suggested category suggestion(s) not reviewed – they are marked “Suggested” in Excel.") }
                    Spacer(Modifier.height(8.dp))
                    Text("All of this is listed in the Exceptions and Reconciliation sheets. ${Limitations.FINANCIAL}", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton({ confirmExport = false; export(review, nav, { error = it }) }) { Text(if (exceptions.isEmpty() && incomplete.isEmpty()) "Export" else "Export with warnings") } },
            dismissButton = { TextButton({ confirmExport = false }) { Text("Keep reviewing") } },
        )
    }
}

@Composable
private fun TxnCard(r: ReviewTxn, selected: Boolean, exception: Boolean, broken: Boolean, onClick: () -> Unit) {
    val warn = exception || broken
    Card(
        Modifier.fillMaxWidth().padding(vertical = 3.dp).clickable(onClick = onClick).semantics { contentDescription = "Transaction ${r.id}, ${r.dateRaw}, ${r.description}. Tap to edit." },
        colors = CardDefaults.cardColors(containerColor = when { selected -> MaterialTheme.colorScheme.secondaryContainer; warn -> MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.45f); else -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f) }),
    ) {
        Column(Modifier.padding(10.dp)) {
            Row { Text(r.date?.format(ReviewSession.DMY) ?: r.dateRaw.ifEmpty { "No date" }, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f)); Text("p. ${r.page}", style = MaterialTheme.typography.bodySmall) }
            Text(r.description.ifEmpty { "(no description)" }, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                if (r.debit != null) Text("Dr ${fmt(r.debit)}", color = MaterialTheme.colorScheme.error)
                if (r.credit != null) Text("Cr ${fmt(r.credit)}", color = MaterialTheme.colorScheme.primary)
                Text("Bal ${r.balance?.let { fmt(it) } ?: r.balanceRaw.ifEmpty { "–" }}", style = MaterialTheme.typography.bodySmall)
            }
            Text(r.category.label + if (r.categorySuggested) " · suggested" else "", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (broken) Text("⚠ Balance doesn't follow from the previous row", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
            if (r.needsReview) r.flags.forEach { Text("⚠ $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error) }
            if (r.reviewed) Text("✓ Reviewed", style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun SourcePage(review: StatementReview, row: ReviewTxn?) {
    val app = DocDeskApp.instance
    if (row == null) { Notice("Tap a transaction to see the page it came from."); return }
    val src = review.sources[row.source]
    if (src == null) { Notice("The source file isn't available."); return }
    val renderer by produceState<Result<PageRenderer>?>(null, row.source) {
        value = withContext(Dispatchers.IO) {
            runCatching { if (src.second != null) PageRenderer.openDecryptedCopy(app, src.first, src.second!!, app.files.workDir) else PageRenderer.open(app, src.first, app.files.workDir) }
        }
    }
    DisposableEffect(renderer) { onDispose { renderer?.getOrNull()?.close() } }
    Text("${row.source} · page ${row.page}", fontWeight = FontWeight.Bold)
    val r = renderer
    when {
        r == null -> Text("Opening page…")
        r.isFailure -> Notice("Couldn't open the source file – it may have been moved or deleted. You can still review and export the extracted data.", NoteKind.WARNING)
        else -> Box(Modifier.fillMaxWidth()) {
            PageImage(r.getOrThrow(), row.page - 1, 1400, description = "Page ${row.page} of ${row.source}")
            val top = row.top; val bottom = row.bottom
            if (top != null && bottom != null) Canvas(Modifier.matchParentSize()) {
                val y0 = (top * size.height - 3f).coerceAtLeast(0f); val y1 = (bottom * size.height + 3f).coerceAtMost(size.height)
                drawRect(Color(0x33FFC107), Offset(0f, y0), Size(size.width, y1 - y0))
                drawRect(Color(0xFFE65100), Offset(0f, y0), Size(size.width, y1 - y0), style = Stroke(3f))
            }
        }
    }
    if (row.top == null) Text("The exact position of this row isn't known (added or split by hand).", style = MaterialTheme.typography.bodySmall)
    Text("Extracted text: ${row.original}", style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun ChecksPanel(review: StatementReview, recon: List<com.docdesk.core.FileReconciliation>, exceptionCount: Int) {
    val s = review.session
    SectionCard("Statement order") {
        RadioOptions(StatementOrder.entries, s.order, { it.label }) { s.setOrder(it); review.changed() }
        if (!s.orderConfirmed) {
            Notice("DocDesk couldn't tell the order from the dates. Check the statement and choose or confirm the order – balance checks stay incomplete until then.", NoteKind.WARNING)
            OutlinedButton({ s.setOrder(s.order); review.changed() }) { Text("Confirm: ${s.order.label}") }
        }
    }
    recon.forEach { f ->
        SectionCard(f.source) {
            BalanceField("Opening balance", s.opening(f.source), review) { s.confirmOpening(f.source, it) }
            BalanceField("Closing balance (from the statement)", s.closing(f.source), review) { s.confirmClosing(f.source, it) }
            HorizontalDivider()
            f.lines.forEach { l ->
                val color = when (l.status) { CheckStatus.OK -> MaterialTheme.colorScheme.primary; CheckStatus.DIFFERENCE -> MaterialTheme.colorScheme.error; CheckStatus.INCOMPLETE -> MaterialTheme.colorScheme.tertiary; CheckStatus.INFO -> MaterialTheme.colorScheme.onSurface }
                Row(Modifier.fillMaxWidth()) {
                    Text(l.label, Modifier.weight(1f))
                    Text(if (l.label == "Running-balance checks") "${l.value?.toInt() ?: 0} break(s)" else fmt(l.value), fontWeight = FontWeight.Bold)
                }
                Text("${l.status.label}${if (l.note.isNotEmpty()) " – ${l.note}" else ""}", style = MaterialTheme.typography.bodySmall, color = color)
            }
        }
    }
    val pages = review.pages
    SectionCard("Pages") {
        pages.groupBy { it.source }.forEach { (src, ps) ->
            val bad = ps.filter { it.status != "Processed" }
            Text("$src: ${ps.count { it.status == "Processed" }} processed" + if (bad.isNotEmpty()) ", ${bad.size} not processed" else "")
            bad.forEach { Text("• ${if (it.page > 0) "Page ${it.page}: " else ""}${it.status}${if (it.note.isNotEmpty()) " – ${it.note}" else ""}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            val types = ps.filter { it.page > 0 }.groupBy { it.type }.map { (t, l) -> "${l.size} ${t.lowercase()}" }
            if (types.isNotEmpty()) Text("Page types: ${types.joinToString()}", style = MaterialTheme.typography.bodySmall)
        }
        review.warnings.forEach { Text("⚠ $it", style = MaterialTheme.typography.bodySmall) }
    }
    SectionCard("Corrections in this session (${s.audit.size})") {
        if (s.audit.isEmpty()) Text("No corrections yet.", style = MaterialTheme.typography.bodySmall)
        s.audit.takeLast(100).reversed().forEach { a -> Text("${a.seq}. ${a.action}${a.rowId?.let { " (row $it)" } ?: ""}${if (a.detail.isNotEmpty()) ": ${a.detail}" else ""}", style = MaterialTheme.typography.bodySmall) }
    }
    Text("$exceptionCount open exception(s). A balance check that agrees doesn't prove every transaction was read correctly.", style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun BalanceField(label: String, value: com.docdesk.core.BalanceValue, review: StatementReview, confirm: (BigDecimal?) -> Unit) {
    var text by remember(value.value, value.confirmed) { mutableStateOf(value.value?.toPlainString() ?: "") }
    val parsed = AmountParser.parse(text, review.style)
    val signed = parsed?.let { if (it.drCr == com.docdesk.core.DrCr.DR) it.value.abs().negate() else it.value }
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(text, { text = it }, Modifier.weight(1f), singleLine = true, label = { Text(label) },
            isError = text.isNotBlank() && parsed == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            supportingText = { Text(if (value.confirmed) "Confirmed" else value.source) })
        Spacer(Modifier.width(8.dp))
        OutlinedButton({ confirm(signed); review.changed() }, enabled = text.isBlank() || parsed != null) { Text(if (value.confirmed) "Update" else "Confirm") }
    }
}

@Composable
private fun EditDialog(review: StatementReview, r: ReviewTxn, onShowSource: () -> Unit, onClose: () -> Unit) {
    val s = review.session
    var date by remember { mutableStateOf(r.date?.format(ReviewSession.DMY) ?: r.dateRaw) }
    var vdate by remember { mutableStateOf(r.valueDate?.format(ReviewSession.DMY) ?: r.valueDateRaw) }
    var desc by remember { mutableStateOf(r.description) }
    var ref by remember { mutableStateOf(r.reference) }
    var dr by remember { mutableStateOf(r.debit?.toPlainString() ?: "") }
    var cr by remember { mutableStateOf(r.credit?.toPlainString() ?: "") }
    var bal by remember { mutableStateOf(r.balance?.toPlainString() ?: r.balanceRaw) }
    var cat by remember { mutableStateOf(r.category) }
    var catSuggested by remember { mutableStateOf(r.categorySuggested) }
    var catMenu by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf<String?>(null) }
    // Dates typed here are day-month-year (as shown); other formats follow the statement's setting.
    fun parseDate(t: String) = if (t.isBlank()) null else DateParser.parse(t, com.docdesk.core.DateOrder.DMY) ?: DateParser.parse(t, review.dateOrder)
    fun amt(t: String) = if (t.isBlank()) null else AmountParser.parse(t, review.style)
    val dErr = date.isNotBlank() && parseDate(date) == null
    val vErr = vdate.isNotBlank() && parseDate(vdate) == null
    val drP = amt(dr); val crP = amt(cr); val balP = amt(bal)
    val drErr = dr.isNotBlank() && (drP == null || drP.value.signum() < 0); val crErr = cr.isNotBlank() && (crP == null || crP.value.signum() < 0)
    val balErr = bal.isNotBlank() && balP == null
    val ok = !dErr && !vErr && !drErr && !crErr && !balErr
    fun done(change: () -> Unit) { change(); review.changed(); onClose() }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Row ${r.id} · ${r.source} p. ${r.page}") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (r.flags.isNotEmpty()) r.flags.forEach { Text("⚠ $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                Text("Extracted: ${r.original}", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(date, { date = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Date (dd-mm-yyyy)") }, isError = dErr)
                OutlinedTextField(vdate, { vdate = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Value date") }, isError = vErr)
                OutlinedTextField(desc, { desc = it }, Modifier.fillMaxWidth(), label = { Text("Description") })
                OutlinedTextField(ref, { ref = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Reference / cheque / UTR") })
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(dr, { dr = it }, Modifier.weight(1f), singleLine = true, label = { Text("Debit") }, isError = drErr, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                    OutlinedTextField(cr, { cr = it }, Modifier.weight(1f), singleLine = true, label = { Text("Credit") }, isError = crErr, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                }
                OutlinedTextField(bal, { bal = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Balance (Dr for overdraft)") }, isError = balErr)
                if (drErr || crErr) Text("Enter debit and credit as positive amounts.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                Box {
                    OutlinedButton({ catMenu = true }, Modifier.fillMaxWidth()) { Text("Category: ${cat.label}${if (catSuggested) " (suggested)" else ""}") }
                    DropdownMenu(catMenu, { catMenu = false }) { TxnCategory.entries.forEach { c -> DropdownMenuItem(text = { Text(c.label) }, onClick = { cat = c; catSuggested = false; catMenu = false }) } }
                }
                @OptIn(ExperimentalLayoutApi::class)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    TextButton(onShowSource) { Text("Show on page") }
                    TextButton({ done { s.insertAfter(r.id) } }) { Text("Add row below") }
                    TextButton({ done { s.split(r.id) } }) { Text("Split") }
                    TextButton({ if (s.mergeWithNext(r.id)) { review.changed(); onClose() } else msg = "Can't combine: the next row is from another file, is missing, or both rows have amounts." }) { Text("Combine with next") }
                    TextButton({ done { s.delete(r.id) } }) { Text("Delete", color = MaterialTheme.colorScheme.error) }
                }
                msg?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                Text("Combine works when only one of the two rows has amounts (a narration that continued on the next line).", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton({
                done {
                    val bv = balP?.let { if (it.drCr == com.docdesk.core.DrCr.DR) it.value.abs().negate() else it.value }
                    s.update(r.id, r.copy(date = parseDate(date), dateRaw = date.trim(), valueDate = parseDate(vdate), valueDateRaw = vdate.trim(), description = desc.trim(), reference = ref.trim(),
                        debit = drP?.value, credit = crP?.value, balance = bv, balanceRaw = bal.trim(), category = cat, categorySuggested = catSuggested))
                }
            }, enabled = ok) { Text("Save · mark reviewed") }
        },
        dismissButton = { TextButton(onClose) { Text("Cancel") } },
    )
}

private fun export(review: StatementReview, nav: Nav, onError: (String) -> Unit) {
    val app = DocDeskApp.instance
    val s = review.session
    Operations.run("Bank statements to Excel", onError = onError, onResult = nav.resultCallback()) { p ->
        p.step("Building workbook…", 0.3f)
        val sheets = BankWorkbook.build(s, review.pages, review.settingsNotes) +
            if (review.partySummaries) listOf(com.docdesk.core.StatementAnalysis.sheets(rowsAsStatement(s), review.rules).first { it.name.contains("Part", true) }) else emptyList()
        val xlsx = app.files.newOutputFile("${review.outputName}.xlsx")
        xlsx.outputStream().buffered().use { XlsxWriter.write(sheets, it) }
        val outputs = mutableListOf(OutputFile(xlsx))
        val stmtRows = rowsAsStatement(s)
        if (review.csv) { val c = app.files.newOutputFile("${review.outputName}.csv"); c.writeText(com.docdesk.core.StatementNormalizer.toCsv(stmtRows)); outputs.add(OutputFile(c)) }
        val notes = mutableListOf<String>()
        review.tally?.let { t ->
            val x = com.docdesk.core.TallyXml.build(stmtRows, com.docdesk.core.TallyXml.Options(t.bankLedger, t.defaultLedger, rules = review.rules))
            val f = app.files.newOutputFile("${review.outputName} (Tally import).xml"); f.writeText(x.xml); outputs.add(OutputFile(f))
            notes.add("Tally XML: ${x.vouchers} voucher(s); ${x.suspense} posted to \"${t.defaultLedger}\". Import into a test company first.")
        }
        val recon = Reconciler.reconcile(s)
        val failedPages = review.pages.filter { it.status != "Processed" }
        val ex = Reconciler.exceptions(s, recon, failedPages.map { it.source to "Page ${it.page}: ${it.status}" })
        val checks = recon.map { f -> "${f.source}: " + f.lines.filter { it.label == "Difference" || it.label == "Running-balance checks" }.joinToString("; ") { "${it.label} ${it.status.label}" } }
        OperationResult(OperationReport("Bank statements to Excel", review.inputNames, if (failedPages.isNotEmpty()) Outcome.PARTIAL else Outcome.SUCCESS,
            pagesSelected = review.pages.count { it.page > 0 }, pagesProcessed = review.pages.count { it.status == "Processed" },
            failedPages = failedPages.map { PageIssue(it.page, "${it.source}: ${it.status}${if (it.note.isNotEmpty()) " – ${it.note}" else ""}") },
            warnings = review.warnings + if (ex.isNotEmpty()) listOf("${ex.size} open exception(s) – see the Exceptions sheet.") else emptyList(),
            checks = checks + Limitations.FINANCIAL,
            notes = listOf("${s.rows.size} transactions, ${s.audit.size} correction(s) recorded in the Processing Report sheet.") + notes),
            outputs, Preview.Sheets(sheets))
    }
}

/** Reviewed rows (oldest first) in the standard layout for CSV, Tally and party summaries. */
private fun rowsAsStatement(s: ReviewSession): List<StatementRow> = BankWorkbook.ordered(s).map { r ->
    StatementRow(r.date, r.dateRaw, r.description, r.reference, r.debit, r.credit, r.balance, r.balanceRaw, r.source, r.page, if (r.needsReview) r.flags else emptyList(), r.valueDate, r.valueDateRaw, r.original)
}
