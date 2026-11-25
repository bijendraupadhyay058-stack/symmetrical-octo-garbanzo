package com.cashbook.app.ui.manage

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.LedgerImport
import com.cashbook.core.LedgerImport.Field
import com.cashbook.core.TxnType
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Composable
private fun fieldLabel(f: Field) = stringResource(when (f) {
    Field.DATE -> R.string.date; Field.DESCRIPTION -> R.string.description; Field.AMOUNT -> R.string.imp_amount_signed
    Field.DEBIT -> R.string.imp_money_out; Field.CREDIT -> R.string.imp_money_in; Field.TYPE -> R.string.imp_type
    Field.CATEGORY -> R.string.category; Field.PARTY -> R.string.party; Field.ACCOUNT -> R.string.account
    Field.MODE -> R.string.payment_mode; Field.REFERENCE -> R.string.reference_number; Field.NOTES -> R.string.notes
})

@Composable
private fun reasonLabel(r: LedgerImport.Reason) = stringResource(when (r) {
    LedgerImport.Reason.NO_DATE -> R.string.imp_no_date; LedgerImport.Reason.NO_AMOUNT -> R.string.imp_no_amount
    LedgerImport.Reason.ZERO_AMOUNT -> R.string.imp_zero_amount; LedgerImport.Reason.TRANSFER -> R.string.imp_transfer
    LedgerImport.Reason.UNKNOWN_TYPE -> R.string.imp_unknown_type
})

/**
 * Import entries from another app's export or a spreadsheet (CSV, Excel .xlsx or a bank's HTML ".xls"): choose the
 * file, check which column is which, pick where they go, preview, import. Each import is tagged and can be undone.
 */
@Composable
fun ImportEntriesScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val rows by vm.importRows.collectAsStateWithLifecycle()
    val s = settings ?: return
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val ctx = LocalContext.current
    val msgUnreadable = stringResource(R.string.statement_unreadable, "")
    val picker = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) runCatching { ctx.contentResolver.openInputStream(uri)!!.use { it.readBytes() } }
            .onSuccess { vm.loadImportFile(it) }.onFailure { vm.toast(msgUnreadable) }
    }
    val cashbooks = snap.cashbooks.filter { !it.archived && it.id in currentScope(snap, s) }.ifEmpty { snap.cashbooks.filter { !it.archived } }
    var cashbookId by rememberSaveable { mutableStateOf(cashbooks.firstOrNull()?.id ?: 0L) }
    val accounts = snap.accounts.filter { it.cashbookId == cashbookId && !it.archived }
    var accountId by rememberSaveable(cashbookId) { mutableStateOf(accounts.firstOrNull()?.id ?: 0L) }
    var createMissing by rememberSaveable { mutableStateOf(true) }
    var result by remember { mutableStateOf<LedgerRepository.ImportResult?>(null) }
    var undone by remember { mutableStateOf<Int?>(null) }
    // the guessed column for each field; the user can change any of them
    var mapping by remember(rows) { mutableStateOf(rows?.let { LedgerImport.guess(it) }) }

    AppScaffold(title = stringResource(R.string.import_entries), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            InfoBanner(stringResource(R.string.import_intro), icon = Icons.Filled.Info)
            OutlinedButton(onClick = {
                vm.allowExternalActivity(); result = null; undone = null
                picker.launch(arrayOf("text/csv", "text/comma-separated-values", "text/plain", "text/tab-separated-values", "text/html", "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"))
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(if (rows == null) R.string.imp_choose_file else R.string.imp_choose_other)) }

            result?.let { r ->
                SectionCard(stringResource(R.string.imp_done)) {
                    Text(stringResource(R.string.imp_result_x, r.created, r.duplicates, r.newCategories, r.newParties), style = MaterialTheme.typography.bodyMedium)
                    Text(stringResource(R.string.imp_tag_x, r.tag), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (undone == null && r.created > 0) OutlinedButton(onClick = { vm.run { val n = ledger.undoImport(r.tag); undone = n } },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp)) { Text(stringResource(R.string.imp_undo)) }
                    undone?.let { Text(stringResource(R.string.imp_undone_x, it), color = fc.expense, style = MaterialTheme.typography.bodyMedium) }
                }
            }

            val r = rows ?: return@Column
            val m = mapping
            if (m == null) { InfoBanner(stringResource(R.string.imp_no_header)); return@Column }
            val header = r.getOrNull(m.headerRow).orEmpty()
            val columnOptions = listOf(-1) + header.indices.toList()
            SectionCard(stringResource(R.string.imp_columns)) {
                Text(stringResource(R.string.imp_columns_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Field.entries.forEach { fld ->
                    DropdownField(fieldLabel(fld), columnOptions, m[fld] ?: -1,
                        labelOf = { c -> if (c < 0) stringResource(R.string.imp_not_in_file) else header.getOrNull(c)?.ifBlank { "#${c + 1}" } ?: "#${c + 1}" },
                        onSelect = { c -> mapping = m.copy(columns = if (c < 0) m.columns - fld else m.columns + (fld to c)) },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                }
            }
            if (!m.usable) { InfoBanner(stringResource(R.string.imp_need_date_amount)); return@Column }

            if (cashbooks.size > 1) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                cashbooks.forEach { c -> FilterChip(c.id == cashbookId, { cashbookId = c.id }, { Text(c.name) }) }
            }
            Text(stringResource(R.string.imp_default_account), style = MaterialTheme.typography.labelLarge)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                accounts.forEach { a -> FilterChip(a.id == accountId, { accountId = a.id }, { Text(a.name) }) }
            }
            SwitchRow(stringResource(R.string.imp_create_missing), createMissing, { createMissing = it }, stringResource(R.string.imp_create_missing_desc))

            val parsed = remember(r, m) { LedgerImport.parse(r, m) }
            val existing = snap.txns.filter { it.cashbookId == cashbookId }
            val dupCount = parsed.rows.count { row ->
                val acc = accounts.firstOrNull { row.account.isNotBlank() && it.name.equals(row.account.trim(), true) }?.id ?: accountId
                LedgerImport.isDuplicate(row, existing, acc)
            }
            SectionCard(stringResource(R.string.imp_preview)) {
                Text(stringResource(R.string.imp_summary_x, parsed.rows.size, dupCount, parsed.problems.size), style = MaterialTheme.typography.bodyMedium)
                parsed.rows.take(8).forEach { row ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                        Column(Modifier.weight(1f)) {
                            Text(row.description.ifBlank { row.category.ifBlank { "—" } }, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(listOf(f.date(row.date), row.category, row.party).filter { it.isNotBlank() }.joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        val inc = row.type == TxnType.INCOME
                        Text((if (inc) "+" else "−") + f.amount(row.amount), color = if (inc) fc.income else fc.expense, style = MaterialTheme.typography.titleSmall)
                    }
                    HorizontalDivider()
                }
                if (parsed.rows.size > 8) Text(stringResource(R.string.imp_more_x, parsed.rows.size - 8), style = MaterialTheme.typography.bodySmall)
            }
            if (parsed.problems.isNotEmpty()) SectionCard(stringResource(R.string.imp_problems_x, parsed.problems.size)) {
                parsed.problems.take(20).forEach { p ->
                    Text(stringResource(R.string.imp_problem_x, p.row, reasonLabel(p.reason)) + (if (p.text.isNotBlank()) " — ${p.text}" else ""),
                        style = MaterialTheme.typography.bodySmall)
                }
            }
            val toImport = parsed.rows.size - dupCount
            Button(enabled = toImport > 0 && accountId != 0L, onClick = {
                val tag = "import-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"))
                vm.run {
                    val res = ledger.importEntries(cashbookId, accountId, parsed.rows, createMissing, tag)
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { result = res; undone = null; vm.importRows.value = null }
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.imp_import_x, toImport)) }
            Box(Modifier.padding(16.dp))
        }
    }
}
