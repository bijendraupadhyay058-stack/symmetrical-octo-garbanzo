package com.cashbook.app.ui.reports

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.GridOn
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.export.Exporter
import com.cashbook.app.export.PdfReportWriter
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.UiFormat
import com.cashbook.app.ui.components.paymentModeLabel
import com.cashbook.app.ui.components.periodLabel
import com.cashbook.app.ui.components.reportTitleRes
import com.cashbook.app.ui.components.txnTypeLabel
import com.cashbook.app.ui.currentScope
import com.cashbook.app.ui.scopeName
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.app.ui.transactions.FilterSheet
import com.cashbook.core.Align
import com.cashbook.core.Cell
import com.cashbook.core.DateRange
import com.cashbook.core.FinancialYear
import com.cashbook.core.PeriodPreset
import com.cashbook.core.Periods
import com.cashbook.core.ReportDocument
import com.cashbook.core.ReportEngine
import com.cashbook.core.ReportExcel
import com.cashbook.core.ReportInput
import com.cashbook.core.ReportTable
import com.cashbook.core.ReportType
import com.cashbook.core.RowStyle
import com.cashbook.core.TxnFilter
import com.cashbook.core.XlsxWriter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

private enum class Mode { PRESET, MONTH, YEAR, FY }

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ReportViewScreen(vm: AppViewModel, nav: NavHostController, typeName: String) {
    val type = runCatching { ReportType.valueOf(typeName) }.getOrDefault(ReportType.CUSTOM)
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    val f = LocalUiFormat.current
    val today = LocalDate.now()
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    val mode = when (type) { ReportType.MONTHLY_SUMMARY -> Mode.MONTH; ReportType.YEARLY_SUMMARY -> Mode.YEAR; ReportType.FINANCIAL_YEAR -> Mode.FY; else -> Mode.PRESET }
    val allTime = remember { vm.pendingReportAllTime.also { vm.pendingReportAllTime = false } }
    val initialFilter = remember { vm.pendingReportFilter.also { vm.pendingReportFilter = null } }
    var preset by rememberSaveable { mutableStateOf(when { allTime -> PeriodPreset.ALL_TIME; type == ReportType.DAILY_CASHBOOK -> PeriodPreset.TODAY; else -> PeriodPreset.THIS_MONTH }) }
    var customStart by rememberSaveable { mutableLongStateOf(today.withDayOfMonth(1).toEpochDay()) }
    var customEnd by rememberSaveable { mutableLongStateOf(today.toEpochDay()) }
    var month by rememberSaveable { mutableStateOf(YearMonth.from(today).toString()) }
    var year by rememberSaveable { mutableStateOf(today.year) }
    var fy by rememberSaveable { mutableStateOf(FinancialYear.of(today).startYear) }
    var accountIds by rememberSaveable { mutableStateOf(listOf<Long>()) }
    var detailFilter by remember { mutableStateOf(initialFilter ?: TxnFilter()) }
    var showFilters by remember { mutableStateOf(false) }
    var exportMenu by remember { mutableStateOf(false) }

    val cbIds = currentScope(snap, s)
    val accounts = snap.accountsOf(cbIds)
    val earliest = (snap.txnsOf(cbIds).minOfOrNull { it.date } ?: today).let { e -> accounts.minOfOrNull { it.openingDate }?.let { minOf(it, e) } ?: e }
    val range: DateRange = when (mode) {
        Mode.MONTH -> YearMonth.parse(month).let { DateRange(it.atDay(1), it.atEndOfMonth()) }
        Mode.YEAR -> DateRange(LocalDate.of(year, 1, 1), LocalDate.of(year, 12, 31))
        Mode.FY -> FinancialYear(fy).range
        Mode.PRESET -> Periods.resolve(preset, today, s.weekStart,
            DateRange(LocalDate.ofEpochDay(minOf(customStart, customEnd)), LocalDate.ofEpochDay(maxOf(customStart, customEnd))), earliest)
            .let { if (preset == PeriodPreset.ALL_TIME) DateRange(earliest, maxOf(today, snap.txnsOf(cbIds).maxOfOrNull { it.date } ?: today)) else it }
    }
    val cashbookLabel = scopeName(snap, s, stringResource(R.string.all_cashbooks))
    val filtersText = buildFilterText(ctx, accountIds.mapNotNull { snap.accountById[it]?.name }, detailFilter, snap)
    val labels = remember(s.language) { reportLabels(ctx) }

    val doc by produceState<ReportDocument?>(null, snap, range, accountIds, detailFilter, cbIds, s.dateFormat, labels) {
        value = withContext(Dispatchers.Default) {
            ReportEngine(ReportInput(
                type = type, cashbookName = cashbookLabel, currency = snap.cashbookById[cbIds.firstOrNull()]?.currency ?: "INR",
                accounts = accounts, selectedAccountIds = accountIds.toSet(), categories = snap.categoryById, parties = snap.partyById,
                txns = snap.txnsOf(cbIds), range = range, filter = detailFilter, filtersLabel = filtersText,
                generatedAt = s.dateFormat.format(LocalDate.now()) + " " + LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm")),
                dateFormat = s.dateFormat, labels = labels, cashbookNames = snap.cashbooks.associate { it.id to it.name },
                locale = Locale.getDefault(), txnsWithAttachments = snap.withAttachments,
            )).build()
        }
    }

    val baseName = Exporter.safeFileName("${ctx.getString(reportTitleRes(type))}_${cashbookLabel}_${range.start}_${range.end}")
    val pdfStrings = PdfReportWriter.Strings(ctx.getString(R.string.app_name), ctx.getString(R.string.cashbook), ctx.getString(R.string.period),
        ctx.getString(R.string.filters), ctx.getString(R.string.generated), ctx.getString(R.string.currency), ctx.getString(R.string.page_x_of_y),
        ctx.getString(R.string.continued), ctx.getString(R.string.no_data_period))
    fun writePdf(d: ReportDocument, out: java.io.OutputStream) = PdfReportWriter(f.money, s.dateFormat, pdfStrings).write(d, out)
    fun writeXlsx(d: ReportDocument, out: java.io.OutputStream) = XlsxWriter.write(ReportExcel.sheets(d, s.dateFormat, d.currency), out)
    val okSaved = stringResource(R.string.export_saved)
    val failed = stringResource(R.string.export_failed)

    fun export(block: suspend () -> Unit) {
        scope.launch {
            try { withContext(Dispatchers.IO) { block() } } catch (e: Throwable) { snackbar.showSnackbar(failed) }
        }
    }
    val savePdf = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument(Exporter.MIME_PDF)) { uri ->
        val d = doc; if (uri != null && d != null) export { Exporter.writeTo(ctx, uri) { writePdf(d, it) }; snackbar.showSnackbar(okSaved) }
    }
    val saveXlsx = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument(Exporter.MIME_XLSX)) { uri ->
        val d = doc; if (uri != null && d != null) export { Exporter.writeTo(ctx, uri) { writeXlsx(d, it) }; snackbar.showSnackbar(okSaved) }
    }

    AppScaffold(
        title = stringResource(reportTitleRes(type)), onBack = { nav.popBackStack() }, snackbar = snackbar,
        bottomBar = {
            BottomAppBar {
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.allowExternalActivity(); savePdf.launch("$baseName.pdf") }, enabled = doc != null, modifier = Modifier.weight(1f)) {
                        Icon(Icons.Filled.PictureAsPdf, null); Text(" PDF") }
                    OutlinedButton(onClick = { vm.allowExternalActivity(); saveXlsx.launch("$baseName.xlsx") }, enabled = doc != null, modifier = Modifier.weight(1f)) {
                        Icon(Icons.Filled.GridOn, null); Text(" Excel") }
                    Column {
                        OutlinedButton(onClick = { exportMenu = true }, enabled = doc != null) { Icon(Icons.Filled.Share, stringResource(R.string.share)) }
                        DropdownMenu(exportMenu, { exportMenu = false }) {
                            DropdownMenuItem(text = { Text(stringResource(R.string.share_pdf)) }, leadingIcon = { Icon(Icons.Filled.PictureAsPdf, null) }, onClick = {
                                exportMenu = false; val d = doc ?: return@DropdownMenuItem
                                export { val uri = Exporter.writeShareable(ctx, "$baseName.pdf") { writePdf(d, it) }
                                    withContext(Dispatchers.Main) { vm.allowExternalActivity(); Exporter.share(ctx, uri, Exporter.MIME_PDF, d.title) } }
                            })
                            DropdownMenuItem(text = { Text(stringResource(R.string.share_excel)) }, leadingIcon = { Icon(Icons.Filled.GridOn, null) }, onClick = {
                                exportMenu = false; val d = doc ?: return@DropdownMenuItem
                                export { val uri = Exporter.writeShareable(ctx, "$baseName.xlsx") { writeXlsx(d, it) }
                                    withContext(Dispatchers.Main) { vm.allowExternalActivity(); Exporter.share(ctx, uri, Exporter.MIME_XLSX, d.title) } }
                            })
                        }
                    }
                }
            }
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            // ----- parameters -----
            SectionCard(stringResource(R.string.report_options)) {
                when (mode) {
                    Mode.MONTH -> {
                        val months = (0 until 36).map { YearMonth.from(today).minusMonths(it.toLong()).toString() }
                        DropdownField(stringResource(R.string.rl_month), months, month, labelOf = { YearMonth.parse(it).format(DateTimeFormatter.ofPattern("MMMM yyyy", Locale.getDefault())) },
                            onSelect = { month = it }, modifier = Modifier.fillMaxWidth())
                    }
                    Mode.YEAR -> DropdownField(stringResource(R.string.year), (today.year downTo minOf(earliest.year, today.year - 5)).toList(), year,
                        labelOf = { it.toString() }, onSelect = { year = it }, modifier = Modifier.fillMaxWidth())
                    Mode.FY -> DropdownField(stringResource(R.string.financial_year), (FinancialYear.of(today).startYear downTo minOf(FinancialYear.of(earliest).startYear, FinancialYear.of(today).startYear - 5)).toList(),
                        fy, labelOf = { FinancialYear(it).label }, onSelect = { fy = it }, modifier = Modifier.fillMaxWidth())
                    Mode.PRESET -> {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            listOf(PeriodPreset.TODAY, PeriodPreset.THIS_WEEK, PeriodPreset.THIS_MONTH, PeriodPreset.LAST_MONTH, PeriodPreset.THIS_FY,
                                PeriodPreset.LAST_FY, PeriodPreset.ALL_TIME, PeriodPreset.CUSTOM).forEach { p ->
                                FilterChip(preset == p, { preset = p }, { Text(periodLabel(p)) })
                            }
                        }
                        if (preset == PeriodPreset.CUSTOM) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            DateField(stringResource(R.string.from_date), LocalDate.ofEpochDay(customStart), { customStart = it.toEpochDay() }, Modifier.weight(1f))
                            DateField(stringResource(R.string.to_date), LocalDate.ofEpochDay(customEnd), { customEnd = it.toEpochDay() }, Modifier.weight(1f))
                        }
                    }
                }
                if (accounts.size > 1) {
                    Text(stringResource(R.string.accounts), style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 8.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        FilterChip(accountIds.isEmpty(), { accountIds = emptyList() }, { Text(stringResource(R.string.all_accounts)) })
                        accounts.forEach { a ->
                            FilterChip(a.id in accountIds, { accountIds = if (a.id in accountIds) accountIds - a.id else accountIds + a.id }, { Text(a.name) })
                        }
                    }
                }
                if (type.supportsDetailFilters) {
                    TextButton(onClick = { showFilters = true }) { Icon(Icons.Filled.FilterList, null); Text(" " + stringResource(R.string.more_filters) +
                        if (detailFilter.isActive) " ✓" else "") }
                }
            }
            // ----- preview -----
            val d = doc
            if (d == null) { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator() } }
            else ReportPreview(d, f)
            Spacer(Modifier.height(16.dp))
        }
    }

    if (showFilters) {
        ModalBottomSheet(onDismissRequest = { showFilters = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            FilterSheet(snap, cbIds, detailFilter, s.weekStart, showRange = false) { detailFilter = it.copy(range = null, accountIds = emptySet()); showFilters = false }
        }
    }
}

private fun buildFilterText(ctx: android.content.Context, accounts: List<String>, f: TxnFilter, snap: com.cashbook.app.data.Snapshot): String {
    val parts = ArrayList<String>()
    if (accounts.isNotEmpty()) parts += ctx.getString(R.string.accounts) + ": " + accounts.joinToString(", ")
    if (f.types.isNotEmpty()) parts += f.types.joinToString(", ") { it.name.lowercase().replaceFirstChar { c -> c.uppercase() } }
    if (f.categoryIds.isNotEmpty()) parts += ctx.getString(R.string.categories) + ": " + f.categoryIds.joinToString(", ") { snap.categoryName(it) }
    if (f.partyIds.isNotEmpty()) parts += ctx.getString(R.string.parties) + ": " + f.partyIds.joinToString(", ") { snap.names.party(it) }
    if (f.paymentModes.isNotEmpty()) parts += ctx.getString(R.string.payment_mode) + ": " + f.paymentModes.joinToString(", ") { it.name }
    if (f.query.isNotBlank()) parts += "\"${f.query}\""
    if (f.withAttachmentsOnly) parts += ctx.getString(R.string.with_attachments)
    return parts.joinToString(" · ")
}

/** On-screen preview mirroring the PDF layout. Tables scroll horizontally on small screens. */
@Composable
fun ReportPreview(d: ReportDocument, f: UiFormat) {
    val fc = LocalFinanceColors.current
    SectionCard {
        Text(d.title, style = MaterialTheme.typography.titleLarge)
        Text("${stringResource(R.string.cashbook)}: ${d.cashbookName}", style = MaterialTheme.typography.bodySmall)
        Text("${stringResource(R.string.period)}: ${d.periodLabel}", style = MaterialTheme.typography.bodySmall)
        if (d.filtersLabel.isNotBlank()) Text("${stringResource(R.string.filters)}: ${d.filtersLabel}", style = MaterialTheme.typography.bodySmall)
        Text("${stringResource(R.string.currency)}: ${d.currency} · ${stringResource(R.string.generated)}: ${d.generatedAt}", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (d.summary.isNotEmpty()) {
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            d.summary.forEach { item ->
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(item.label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                    Text(cellText(item.value, f), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold,
                        color = if ((item.value as? Cell.Amount)?.paise?.let { it < 0 } == true) fc.expense else MaterialTheme.colorScheme.onSurface)
                }
            }
        }
    }
    if (d.isEmpty) InfoBanner(stringResource(R.string.no_data_period))
    d.tables.filter { it.rows.isNotEmpty() }.forEach { PreviewTable(it, f) }
    d.notes.forEach { InfoBanner(it) }
}

private fun cellText(c: Cell, f: UiFormat): String = when (c) {
    is Cell.Text -> c.value; is Cell.Amount -> f.amount(c.paise); is Cell.Count -> c.value.toString(); is Cell.Day -> f.date(c.date); Cell.Empty -> ""
}

@Composable
private fun PreviewTable(t: ReportTable, f: UiFormat) {
    val fc = LocalFinanceColors.current
    val unit = 62.dp
    SectionCard(t.title) {
        Column(Modifier.horizontalScroll(rememberScrollState())) {
            Row(Modifier.background(fc.header).padding(vertical = 6.dp)) {
                t.columns.forEach { c ->
                    Text(c.title, Modifier.width(unit * c.weight).padding(horizontal = 4.dp), color = fc.onHeader, style = MaterialTheme.typography.labelMedium,
                        textAlign = if (c.align == Align.END) TextAlign.End else TextAlign.Start)
                }
            }
            t.rows.take(500).forEach { r ->
                val bg = when (r.style) { RowStyle.HEADING -> MaterialTheme.colorScheme.surfaceVariant; RowStyle.TOTAL -> MaterialTheme.colorScheme.secondaryContainer; else -> MaterialTheme.colorScheme.surface }
                Row(Modifier.background(bg).padding(vertical = 5.dp), verticalAlignment = Alignment.Top) {
                    r.cells.forEachIndexed { i, c ->
                        val col = t.columns.getOrNull(i) ?: return@forEachIndexed
                        Text(cellText(c, f), Modifier.width(unit * col.weight).padding(horizontal = 4.dp), style = MaterialTheme.typography.bodySmall,
                            fontWeight = if (r.style != RowStyle.NORMAL) FontWeight.SemiBold else null,
                            textAlign = if (col.align == Align.END) TextAlign.End else TextAlign.Start)
                    }
                }
                HorizontalDivider()
            }
            if (t.rows.size > 500) Text(stringResource(R.string.preview_truncated, t.rows.size), style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(8.dp))
        }
    }
}
