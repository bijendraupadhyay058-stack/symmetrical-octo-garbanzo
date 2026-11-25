package com.cashbook.app.ui.manage

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.MiscellaneousServices
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.ConfirmDialog
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.EmptyState
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.nav.Routes
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.CatalogItem
import com.cashbook.core.Gst
import com.cashbook.core.ItemKind
import com.cashbook.core.Money
import kotlinx.coroutines.launch
import java.time.LocalDate

private fun qtyText(milli: Long, unit: String) = Gst.formatQuantity(milli) + if (unit.isNotBlank()) " $unit" else ""

@Composable
fun CatalogScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    var query by rememberSaveable { mutableStateOf("") }
    var lowOnly by rememberSaveable { mutableStateOf(false) }
    val list = snap.catalog.filter { (query.isBlank() || it.name.contains(query, true) || it.hsn.contains(query)) }
        .filter { !lowOnly || (it.tracksStock && it.reorderLevelMilli > 0 && snap.onHand(it) <= it.reorderLevelMilli) }
    AppScaffold(title = stringResource(R.string.products_services), onBack = { nav.popBackStack() }, floating = {
        com.cashbook.app.ui.components.AppFab(stringResource(R.string.new_item), onClick = { nav.navigate(Routes.catalogItem(0)) })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            OutlinedTextField(query, { query = it }, leadingIcon = { Icon(Icons.Filled.Search, null) }, placeholder = { Text(stringResource(R.string.search_items)) },
                singleLine = true, modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp))
            Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) { FilterChip(lowOnly, { lowOnly = !lowOnly }, { Text(stringResource(R.string.low_stock_only)) }) }
            if (list.isEmpty()) EmptyState(Icons.Filled.Inventory2, stringResource(if (snap.catalog.isEmpty()) R.string.no_items else R.string.no_matches))
            LazyColumn {
                items(list, key = { it.id }) { c ->
                    val have = if (c.tracksStock) snap.onHand(c) else 0
                    val low = c.tracksStock && c.reorderLevelMilli > 0 && have <= c.reorderLevelMilli
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate(Routes.catalogItem(c.id)) }.padding(horizontal = 16.dp, vertical = 12.dp).alpha(if (c.archived) 0.55f else 1f),
                        verticalAlignment = Alignment.CenterVertically) {
                        Icon(if (c.tracksStock) Icons.Filled.Inventory2 else Icons.Filled.MiscellaneousServices, null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(c.name, style = MaterialTheme.typography.bodyLarge)
                            Text(listOfNotNull(c.hsn.takeIf { it.isNotBlank() }?.let { "HSN/SAC $it" }, "GST ${Gst.rateLabel(c.gstBp)}",
                                f.amount(c.saleRate) + if (c.unit.isNotBlank()) " / ${c.unit}" else "").joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (c.tracksStock) Column(horizontalAlignment = Alignment.End) {
                            Text(qtyText(have, c.unit), style = MaterialTheme.typography.titleSmall, color = if (low || have < 0) fc.expense else MaterialTheme.colorScheme.onSurface)
                            if (low) Text(stringResource(R.string.low_stock), style = MaterialTheme.typography.labelSmall, color = fc.expense)
                        }
                    }
                    HorizontalDivider()
                }
                item { Box(Modifier.padding(40.dp)) }
            }
        }
    }
}

@Composable
fun CatalogItemScreen(vm: AppViewModel, nav: NavHostController, id: Long) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val f = LocalUiFormat.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    var name by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf(ItemKind.GOODS) }
    var hsn by rememberSaveable { mutableStateOf("") }
    var unit by rememberSaveable { mutableStateOf("") }
    var saleRate by rememberSaveable { mutableStateOf("") }
    var purchaseRate by rememberSaveable { mutableStateOf("") }
    var gstBp by rememberSaveable { mutableStateOf(1800) }
    var description by rememberSaveable { mutableStateOf("") }
    var opening by rememberSaveable { mutableStateOf("") }
    var openingDate by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var reorder by rememberSaveable { mutableStateOf("") }
    var archived by rememberSaveable { mutableStateOf(false) }
    var loaded by rememberSaveable { mutableStateOf(id == 0L) }
    var showErrors by rememberSaveable { mutableStateOf(false) }
    var adjusting by rememberSaveable { mutableStateOf(false) }
    var adjQty by rememberSaveable { mutableStateOf("") }
    var adjAdd by rememberSaveable { mutableStateOf(false) }
    var adjReason by rememberSaveable { mutableStateOf("") }
    var adjDate by rememberSaveable { mutableStateOf(LocalDate.now().toEpochDay()) }
    var confirmDelete by remember { mutableStateOf(false) }
    val existing = snap.catalogById[id]
    LaunchedEffect(existing) {
        if (!loaded && existing != null) {
            name = existing.name; kind = existing.kind; hsn = existing.hsn; unit = existing.unit
            saleRate = if (existing.saleRate == 0L) "" else Money.toPlain(existing.saleRate)
            purchaseRate = if (existing.purchaseRate == 0L) "" else Money.toPlain(existing.purchaseRate)
            gstBp = existing.gstBp; description = existing.description
            opening = if (existing.openingStockMilli == 0L) "" else Gst.formatQuantity(existing.openingStockMilli)
            openingDate = existing.openingDate.toEpochDay(); reorder = if (existing.reorderLevelMilli == 0L) "" else Gst.formatQuantity(existing.reorderLevelMilli)
            archived = existing.archived; loaded = true
        }
    }
    fun rate(t: String) = (Money.parseOpening(t) as? Money.ParseResult.Ok)?.paise
    fun qtyOrZero(t: String) = if (t.isBlank()) 0L else Gst.parseQuantity(t)
    val ok = name.isNotBlank() && rate(saleRate) != null && rate(purchaseRate) != null && qtyOrZero(opening) != null && qtyOrZero(reorder) != null
    val dupMsg = stringResource(R.string.item_err_duplicate)
    val inUseMsg = stringResource(R.string.item_err_in_use)

    AppScaffold(title = stringResource(if (id == 0L) R.string.new_item else R.string.edit_item), onBack = { nav.popBackStack() }, snackbar = snackbar) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                ItemKind.entries.forEachIndexed { i, k ->
                    SegmentedButton(kind == k, { kind = k }, SegmentedButtonDefaults.itemShape(i, 2)) {
                        Text(stringResource(if (k == ItemKind.GOODS) R.string.item_goods else R.string.item_service)) }
                }
            }
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.item_name)) }, singleLine = true, isError = showErrors && name.isBlank(), modifier = Modifier.fillMaxWidth())
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(hsn, { hsn = it.filter(Char::isDigit).take(8) }, label = { Text(stringResource(R.string.item_hsn)) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                OutlinedTextField(unit, { unit = it.take(8) }, label = { Text(stringResource(R.string.item_unit)) }, singleLine = true, modifier = Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MoneyField(saleRate, { saleRate = it }, stringResource(R.string.sale_rate), Modifier.weight(1f))
                MoneyField(purchaseRate, { purchaseRate = it }, stringResource(R.string.purchase_rate), Modifier.weight(1f))
            }
            DropdownField(stringResource(R.string.gst_rate), Gst.RATES_BP, gstBp, labelOf = { Gst.rateLabel(it) }, onSelect = { gstBp = it }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.description_optional)) }, maxLines = 3, modifier = Modifier.fillMaxWidth())
            if (kind == ItemKind.GOODS) SectionCard(stringResource(R.string.stock)) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    existing?.takeIf { it.tracksStock }?.let { Text(stringResource(R.string.in_stock_x, Gst.formatQuantity(snap.onHand(it)), it.unit), style = MaterialTheme.typography.titleMedium) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(opening, { opening = it.filter { c -> c.isDigit() || c == '.' } }, label = { Text(stringResource(R.string.opening_stock)) }, singleLine = true,
                            isError = qtyOrZero(opening) == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f))
                        OutlinedTextField(reorder, { reorder = it.filter { c -> c.isDigit() || c == '.' } }, label = { Text(stringResource(R.string.reorder_level)) }, singleLine = true,
                            isError = qtyOrZero(reorder) == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f))
                    }
                    DateField(stringResource(R.string.opening_stock_date), LocalDate.ofEpochDay(openingDate), { openingDate = it.toEpochDay() })
                    Text(stringResource(R.string.stock_explain), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (id != 0L) SwitchRow(stringResource(R.string.archived), archived, { archived = it }, stringResource(R.string.item_archive_desc))
            Button(onClick = {
                showErrors = true
                if (!ok) return@Button
                val item = CatalogItem(id, name, kind, hsn, unit, rate(saleRate)!!, rate(purchaseRate)!!, gstBp, description, qtyOrZero(opening)!!,
                    LocalDate.ofEpochDay(openingDate), qtyOrZero(reorder)!!, archived)
                vm.run(onError = { e -> scope.launch { snackbar.showSnackbar(if (e is LedgerRepository.CatalogException) dupMsg else e.localizedMessage ?: "") } }) {
                    ledger.saveCatalogItem(item)
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { nav.popBackStack() }
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }

            // ----- stock history & adjustments (existing goods) -----
            if (existing != null && existing.tracksStock) {
                SectionCard(stringResource(R.string.stock_history), action = {
                    if (!adjusting) OutlinedButton(onClick = { adjusting = true }) { Text(stringResource(R.string.adjust_stock)) }
                }) {
                    if (adjusting) Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 8.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            FilterChip(!adjAdd, { adjAdd = false }, { Text(stringResource(R.string.adj_reduce)) })
                            FilterChip(adjAdd, { adjAdd = true }, { Text(stringResource(R.string.adj_add)) })
                        }
                        OutlinedTextField(adjQty, { adjQty = it.filter { c -> c.isDigit() || c == '.' } }, label = { Text(stringResource(R.string.item_qty)) }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(adjReason, { adjReason = it }, label = { Text(stringResource(R.string.note_reason)) }, singleLine = true,
                            placeholder = { Text(stringResource(R.string.adj_reason_hint)) }, modifier = Modifier.fillMaxWidth())
                        DateField(stringResource(R.string.date), LocalDate.ofEpochDay(adjDate), { adjDate = it.toEpochDay() })
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { adjusting = false }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.cancel)) }
                            Button(enabled = Gst.parseQuantity(adjQty) != null, onClick = {
                                val q = Gst.parseQuantity(adjQty)!! * (if (adjAdd) 1 else -1)
                                vm.run { ledger.addStockAdjustment(id, LocalDate.ofEpochDay(adjDate), q, adjReason) }
                                adjusting = false; adjQty = ""; adjReason = ""
                            }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.save)) }
                        }
                    }
                    val moves = snap.stockMoves.filter { it.itemId == id }.sortedByDescending { it.date }.take(50)
                    if (moves.isEmpty() && existing.openingStockMilli == 0L) Text(stringResource(R.string.no_stock_moves), style = MaterialTheme.typography.bodySmall)
                    moves.forEach { m ->
                        val adj = if (m.docId == null) snap.stockAdjustments.firstOrNull { a -> a.itemId == id && a.date == m.date && a.quantityMilli == m.quantityMilli } else null
                        Row(Modifier.fillMaxWidth().let { mod -> if (m.docId != null) mod.clickable { nav.navigate(Routes.invoice(m.docId!!)) } else mod }.padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(m.label.ifBlank { stringResource(R.string.adjust_stock) }, style = MaterialTheme.typography.bodyMedium)
                                Text(f.date(m.date) + if (m.docId == null) " · " + stringResource(R.string.adjust_stock) else "", style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text((if (m.quantityMilli > 0) "+" else "") + Gst.formatQuantity(m.quantityMilli), style = MaterialTheme.typography.titleSmall)
                            if (adj != null) IconButton(onClick = { vm.run { ledger.deleteStockAdjustment(adj.id) } }) { Icon(Icons.Filled.Close, stringResource(R.string.remove)) }
                        }
                        HorizontalDivider()
                    }
                    if (existing.openingStockMilli != 0L) Text(stringResource(R.string.opening_stock_on, qtyText(existing.openingStockMilli, existing.unit), f.date(existing.openingDate)),
                        style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
                }
            }
            if (id != 0L) OutlinedButton(onClick = { confirmDelete = true }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
        }
    }
    if (confirmDelete) ConfirmDialog(stringResource(R.string.delete_item_title), stringResource(R.string.delete_item_text), stringResource(R.string.delete),
        onConfirm = { vm.run(onError = { vm.toast(inUseMsg) }) { ledger.deleteCatalogItem(id); kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main) { nav.popBackStack() } } },
        onDismiss = { confirmDelete = false }, destructive = true)
}

