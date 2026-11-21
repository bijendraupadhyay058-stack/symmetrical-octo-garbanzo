package com.docdesk.app.ui.tools

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.docdesk.app.DocDeskApp
import com.docdesk.app.convert.OperationReport
import com.docdesk.app.convert.OperationResult
import com.docdesk.app.convert.OutputFile
import com.docdesk.app.convert.Outcome
import com.docdesk.app.convert.PageIssue
import com.docdesk.app.convert.Preview
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.components.JobProgressCard
import com.docdesk.app.ui.components.Notice
import com.docdesk.app.ui.components.NoteKind
import com.docdesk.app.ui.components.Operations
import com.docdesk.app.ui.components.PrimaryAction
import com.docdesk.app.ui.components.ToolScaffold
import com.docdesk.core.AmountParser
import com.docdesk.core.DateOrder
import com.docdesk.core.DateParser
import com.docdesk.core.InvoiceChecks
import com.docdesk.core.InvoiceExtractor
import com.docdesk.core.InvoiceRecord
import com.docdesk.core.NumberStyle
import com.docdesk.core.SensitiveFinder
import com.docdesk.core.XlsxWriter
import java.math.BigDecimal

/** Invoices read but not yet exported. Memory only. */
class InvoiceReview(
    records: List<InvoiceRecord>, val mandatory: Set<InvoiceChecks.Field>, val failed: List<PageIssue>, val warnings: List<String>,
    val outputName: String, val style: NumberStyle, val order: DateOrder, val inputNames: List<String>,
) {
    var records by mutableStateOf(InvoiceChecks.apply(records, mandatory))
    val corrections = mutableListOf<String>()
    var version by mutableIntStateOf(0)

    /** Re-runs the register checks on the original flags plus edits (edited/reviewed state is kept). */
    fun replace(i: Int, r: InvoiceRecord, what: String) {
        val base = records.toMutableList(); base[i] = r
        val stripped = base.map { x -> x.copy(flags = x.flags.filterNot { it.startsWith("Possible duplicate") || it.startsWith("Required field missing") }) }
        records = InvoiceChecks.apply(stripped, mandatory)
        corrections.add("${r.source}: $what"); version++
    }
}

object InvoiceReviewStore { var current: InvoiceReview? = null }

@Composable
fun InvoiceReviewScreen(nav: Nav) {
    val review = InvoiceReviewStore.current
    if (review == null) { ToolScaffold("Review invoices", nav::back) { Notice("There is no invoice review open. Read the invoices again.", NoteKind.WARNING) }; return }
    @Suppress("UNUSED_VARIABLE") val v = review.version
    val app = DocDeskApp.instance
    val job by app.jobs.state.collectAsStateWithLifecycle()
    var editing by remember { mutableStateOf<Int?>(null) }
    var confirm by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val open = review.records.count { it.flags.isNotEmpty() && !it.reviewed }
    ToolScaffold("Review invoices", nav::back) {
        error?.let { Notice(it, NoteKind.ERROR) { error = null } }
        Text("${review.records.size} invoice(s) · $open need review · tap an invoice to check or correct it", style = MaterialTheme.typography.bodyMedium)
        review.failed.forEach { Notice("Not read: ${it.message}", NoteKind.WARNING) }
        review.records.forEachIndexed { i, r ->
            val warn = r.flags.isNotEmpty() && !r.reviewed
            Card(Modifier.fillMaxWidth().clickable { editing = i },
                colors = CardDefaults.cardColors(containerColor = if (warn) MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.45f) else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))) {
                Column(Modifier.padding(10.dp)) {
                    Text("${r.invoiceNo ?: "No invoice no."} · ${r.date?.let { it.format(com.docdesk.core.ReviewSession.DMY) } ?: r.dateRaw ?: "no date"}", fontWeight = FontWeight.Bold)
                    Text("${r.supplierName ?: "Supplier ?"} (${r.supplierGstin ?: "no GSTIN"}) → ${r.buyerName ?: "Customer ?"}", style = MaterialTheme.typography.bodySmall)
                    Text("Taxable ${r.taxable?.let { AmountParser.formatIndian(it) } ?: "–"} · Tax ${listOfNotNull(r.cgst, r.sgst, r.igst, r.cess).fold(BigDecimal.ZERO, BigDecimal::add).let { AmountParser.formatIndian(it) }} · Total ${r.total?.let { AmountParser.formatIndian(it) } ?: "–"}")
                    Text("${r.source} · page ${r.page} · ${r.items.size} line item(s)", style = MaterialTheme.typography.labelSmall)
                    if (warn) r.flags.forEach { Text("⚠ $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error) }
                    if (r.reviewed) Text("✓ Reviewed", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
        Text("GSTIN checks test only the format and check digit – they don't confirm a GSTIN is active. DocDesk doesn't decide input tax credit eligibility.", style = MaterialTheme.typography.bodySmall)
        job?.let { JobProgressCard(it) { app.jobs.cancel() } }
        PrimaryAction("Export register…", enabled = job == null, icon = Icons.AutoMirrored.Filled.ReceiptLong) { confirm = true }
    }
    editing?.let { i -> InvoiceEditDialog(review, i) { editing = null } }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false }, title = { Text("Export register?") },
        text = { Text(if (open == 0) "All invoices are reviewed or have no warnings." else "$open invoice(s) still have unreviewed warnings. They are highlighted in the register.") },
        confirmButton = { TextButton({ confirm = false; exportInvoices(review, nav) { error = it } }) { Text(if (open == 0) "Export" else "Export with warnings") } },
        dismissButton = { TextButton({ confirm = false }) { Text("Keep reviewing") } })
}

@Composable
private fun InvoiceEditDialog(review: InvoiceReview, i: Int, onClose: () -> Unit) {
    val r = review.records[i]
    fun a(v: BigDecimal?) = v?.toPlainString() ?: ""
    var no by remember { mutableStateOf(r.invoiceNo ?: "") }; var date by remember { mutableStateOf(r.date?.let { it.format(com.docdesk.core.ReviewSession.DMY) } ?: r.dateRaw ?: "") }
    var type by remember { mutableStateOf(r.invoiceType ?: "") }
    var sName by remember { mutableStateOf(r.supplierName ?: "") }; var sG by remember { mutableStateOf(r.supplierGstin ?: "") }
    var bName by remember { mutableStateOf(r.buyerName ?: "") }; var bG by remember { mutableStateOf(r.buyerGstin ?: "") }
    var tx by remember { mutableStateOf(a(r.taxable)) }; var cg by remember { mutableStateOf(a(r.cgst)) }; var sg by remember { mutableStateOf(a(r.sgst)) }
    var ig by remember { mutableStateOf(a(r.igst)) }; var ce by remember { mutableStateOf(a(r.cess)) }; var tot by remember { mutableStateOf(a(r.total)) }
    fun amt(s: String) = if (s.isBlank()) null else AmountParser.parse(s, review.style)?.value
    fun bad(s: String) = s.isNotBlank() && amt(s) == null
    val dateP = if (date.isBlank()) null else DateParser.parse(date, review.order)
    val gstinNote = { g: String -> if (g.isNotBlank() && !SensitiveFinder.gstinValid(g.trim().uppercase())) "Format/check digit doesn't match a GSTIN" else null }
    val ok = listOf(tx, cg, sg, ig, ce, tot).none(::bad) && (date.isBlank() || dateP != null)
    AlertDialog(onDismissRequest = onClose, title = { Text(r.source) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            r.flags.forEach { Text("⚠ $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            OutlinedTextField(type, { type = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Invoice type") })
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(no, { no = it }, Modifier.weight(1f), singleLine = true, label = { Text("Invoice no.") })
                OutlinedTextField(date, { date = it }, Modifier.weight(1f), singleLine = true, label = { Text("Date") }, isError = date.isNotBlank() && dateP == null)
            }
            OutlinedTextField(sName, { sName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Supplier name") })
            OutlinedTextField(sG, { sG = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Supplier GSTIN") }, supportingText = gstinNote(sG)?.let { { Text(it) } })
            OutlinedTextField(bName, { bName = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Customer name") })
            OutlinedTextField(bG, { bG = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Customer GSTIN") }, supportingText = gstinNote(bG)?.let { { Text(it) } })
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(tx, { tx = it }, Modifier.weight(1f), singleLine = true, label = { Text("Taxable") }, isError = bad(tx))
                OutlinedTextField(tot, { tot = it }, Modifier.weight(1f), singleLine = true, label = { Text("Total") }, isError = bad(tot))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(cg, { cg = it }, Modifier.weight(1f), singleLine = true, label = { Text("CGST") }, isError = bad(cg))
                OutlinedTextField(sg, { sg = it }, Modifier.weight(1f), singleLine = true, label = { Text("SGST") }, isError = bad(sg))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(ig, { ig = it }, Modifier.weight(1f), singleLine = true, label = { Text("IGST") }, isError = bad(ig))
                OutlinedTextField(ce, { ce = it }, Modifier.weight(1f), singleLine = true, label = { Text("Cess") }, isError = bad(ce))
            }
            if (r.items.isNotEmpty()) { Text("Line items (as read)", fontWeight = FontWeight.Bold); r.items.forEach { Text("• ${it.hsnSac} ${it.description} ${it.amount?.let { a -> AmountParser.formatIndian(a) } ?: ""}", style = MaterialTheme.typography.bodySmall) } }
            if (r.evidence.isNotEmpty()) { Text("Read from", fontWeight = FontWeight.Bold); r.evidence.forEach { (k, v) -> Text("$k: $v", style = MaterialTheme.typography.bodySmall) } }
        } },
        confirmButton = { TextButton({
            val taxable = amt(tx); val total = amt(tot)
            // Re-check the arithmetic on the corrected values; other flags are cleared by the user's review.
            val sum = taxable?.let { t -> listOfNotNull(amt(cg), amt(sg), amt(ig), amt(ce)).fold(t, BigDecimal::add) }
            val arith = if (sum != null && total != null && (sum - total).abs() > BigDecimal("1.00")) listOf("Taxable + taxes = ${AmountParser.formatIndian(sum)} but total is ${AmountParser.formatIndian(total)}") else emptyList()
            val edited = r.copy(invoiceNo = no.trim().ifEmpty { null }, date = dateP, dateRaw = date.trim().ifEmpty { null }, invoiceType = type.trim().ifEmpty { null },
                supplierName = sName.trim().ifEmpty { null }, supplierGstin = sG.trim().uppercase().ifEmpty { null }, buyerName = bName.trim().ifEmpty { null }, buyerGstin = bG.trim().uppercase().ifEmpty { null },
                taxable = taxable, cgst = amt(cg), sgst = amt(sg), igst = amt(ig), cess = amt(ce), total = total,
                flags = arith + listOfNotNull(gstinNote(sG)?.let { "Supplier GSTIN: $it" }, gstinNote(bG)?.let { "Customer GSTIN: $it" }), reviewed = true)
            val changed = edited.copy(flags = r.flags, reviewed = r.reviewed, edited = r.edited) != r
            review.replace(i, edited.copy(edited = r.edited || changed), if (changed) "corrected and reviewed" else "reviewed")
            onClose()
        }, enabled = ok) { Text("Save · mark reviewed") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } })
}

private fun exportInvoices(review: InvoiceReview, nav: Nav, onError: (String) -> Unit) {
    val app = DocDeskApp.instance
    val records = review.records
    Operations.run("GST invoice register", onError = onError, onResult = nav.resultCallback()) { p ->
        p.step("Writing register…", 0.5f)
        val sheets = InvoiceExtractor.toSheets(records)
        val out = app.files.newOutputFile("${review.outputName}.xlsx")
        out.outputStream().buffered().use { XlsxWriter.write(sheets, it) }
        val open = records.count { it.flags.isNotEmpty() && !it.reviewed }
        OperationResult(OperationReport("GST invoice register", review.inputNames, if (review.failed.isNotEmpty() || open > 0) Outcome.PARTIAL else Outcome.SUCCESS,
            failedPages = review.failed, warnings = review.warnings + if (open > 0) listOf("$open invoice(s) exported with unreviewed warnings (highlighted).") else emptyList(),
            notes = listOf("${records.size} invoice(s); ${review.corrections.size} review action(s). Values are read only from clearly labelled lines. GSTIN checks cover format and check digit only.")),
            listOf(OutputFile(out)), Preview.Sheets(sheets))
    }
}
