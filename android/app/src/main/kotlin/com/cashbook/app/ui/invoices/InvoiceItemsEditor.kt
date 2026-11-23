package com.cashbook.app.ui.invoices

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.saveable.Saver
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.cashbook.app.R
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.core.Gst
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceTotals
import com.cashbook.core.Money

/** Editable text state of one invoice line. */
data class ItemDraft(
    val description: String = "", val hsn: String = "", val qty: String = "1", val unit: String = "", val rate: String = "",
    val discount: String = "", val gstBp: Int = 1800, val itemId: Long = 0,
) {
    val quantityMilli get() = Gst.parseQuantity(qty)
    val ratePaise get() = (Money.parseOpening(rate) as? Money.ParseResult.Ok)?.paise
    val discountBp get() = Gst.parsePercent(discount)
    val valid get() = description.isNotBlank() && quantityMilli != null && ratePaise != null && discountBp != null
    fun toItem() = InvoiceItem(0, description, hsn, quantityMilli!!, unit, ratePaise!!, discountBp!!, gstBp, itemId.takeIf { it > 0 })

    companion object {
        fun from(i: InvoiceItem) = ItemDraft(i.description, i.hsn, Gst.formatQuantity(i.quantityMilli), i.unit, Money.toPlain(i.rate),
            if (i.discountBp == 0) "" else Gst.formatPercent(i.discountBp), i.gstBp, i.itemId ?: 0)

        /** A new line filled from a saved item, at its sale or purchase rate. */
        fun from(c: com.cashbook.core.CatalogItem, purchase: Boolean) = ItemDraft(c.name, c.hsn, "1", c.unit,
            Money.toPlain(if (purchase) c.purchaseRate else c.saleRate).let { if (it == "0") "" else it }, "", c.gstBp, c.id)

        val ListSaver: Saver<List<ItemDraft>, Any> = Saver(
            save = { l -> l.map { arrayListOf(it.description, it.hsn, it.qty, it.unit, it.rate, it.discount, it.gstBp.toString(), it.itemId.toString()) } },
            restore = { raw -> (raw as List<*>).map { r -> val a = r as List<*>
                ItemDraft(a[0] as String, a[1] as String, a[2] as String, a[3] as String, a[4] as String, a[5] as String, (a[6] as String).toInt(),
                    (a.getOrNull(7) as? String)?.toLongOrNull() ?: 0) } },
        )
    }
}

/** Line items edited in place (no dialogs): description, HSN/SAC, qty, unit, rate, discount and GST rate per line. */
@Composable
fun InvoiceItemsEditor(items: List<ItemDraft>, onChange: (List<ItemDraft>) -> Unit, showErrors: Boolean, totals: InvoiceTotals?,
                       catalog: List<com.cashbook.core.CatalogItem> = emptyList(), purchase: Boolean = false,
                       onHand: (com.cashbook.core.CatalogItem) -> Long = { 0 }, stockOut: Boolean = false) {
    val f = LocalUiFormat.current
    var pickFor by androidx.compose.runtime.saveable.rememberSaveable { androidx.compose.runtime.mutableStateOf(-1) }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.forEachIndexed { i, d ->
            fun upd(n: ItemDraft) = onChange(items.toMutableList().also { it[i] = n })
            SectionCard(stringResource(R.string.item_n, i + 1), action = {
                if (catalog.isNotEmpty()) IconButton(onClick = { pickFor = i }) { Icon(Icons.Filled.Inventory2, stringResource(R.string.pick_item)) }
                IconButton(onClick = { onChange(items.toMutableList().also { it.removeAt(i) }) }) { Icon(Icons.Filled.Delete, stringResource(R.string.remove_item)) }
            }) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(d.description, { upd(d.copy(description = it)) }, label = { Text(stringResource(R.string.item_description)) },
                        isError = showErrors && d.description.isBlank(), singleLine = true, modifier = Modifier.fillMaxWidth(),
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(d.hsn, { upd(d.copy(hsn = it.filter(Char::isDigit).take(8))) }, label = { Text(stringResource(R.string.item_hsn)) }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                        OutlinedTextField(d.unit, { upd(d.copy(unit = it.take(8))) }, label = { Text(stringResource(R.string.item_unit)) }, singleLine = true,
                            modifier = Modifier.weight(1f))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(d.qty, { upd(d.copy(qty = it.filter { c -> c.isDigit() || c == '.' }.take(12))) }, label = { Text(stringResource(R.string.item_qty)) },
                            singleLine = true, isError = showErrors && d.quantityMilli == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            modifier = Modifier.weight(0.8f))
                        OutlinedTextField(d.rate, { upd(d.copy(rate = it.filter { c -> c.isDigit() || c == '.' || c == ',' }.take(15))) }, label = { Text(stringResource(R.string.item_rate)) },
                            prefix = { Text("₹ ") }, singleLine = true, isError = showErrors && d.ratePaise == null,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1.2f))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                        OutlinedTextField(d.discount, { upd(d.copy(discount = it.filter { c -> c.isDigit() || c == '.' }.take(6))) }, label = { Text(stringResource(R.string.item_discount)) },
                            suffix = { Text("%") }, singleLine = true, isError = d.discountBp == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            modifier = Modifier.weight(0.8f))
                        DropdownField(stringResource(R.string.gst_rate), Gst.RATES_BP, d.gstBp, labelOf = { Gst.rateLabel(it) }, onSelect = { upd(d.copy(gstBp = it)) },
                            modifier = Modifier.weight(1.2f))
                    }
                    // selling more goods than are in stock: warn, but allow (stock may simply not be recorded yet)
                    val saved = catalog.firstOrNull { it.id == d.itemId }
                    if (stockOut && saved != null && saved.tracksStock) {
                        val have = onHand(saved); val want = d.quantityMilli ?: 0
                        Text(if (want > have) stringResource(R.string.stock_short, Gst.formatQuantity(have), saved.unit) else stringResource(R.string.in_stock_x, Gst.formatQuantity(have), saved.unit),
                            style = MaterialTheme.typography.labelSmall,
                            color = if (want > have) com.cashbook.app.ui.theme.LocalFinanceColors.current.warning else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    totals?.lines?.getOrNull(i)?.takeIf { d.valid }?.let { l ->
                        Text(stringResource(R.string.item_line_total, f.amount(l.taxable), f.amount(l.tax), f.amount(l.total)), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        OutlinedButton(onClick = { onChange(items + ItemDraft(gstBp = items.lastOrNull()?.gstBp ?: 1800)) }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.Add, null); Text(" " + stringResource(R.string.add_item))
        }
        if (catalog.isNotEmpty()) OutlinedButton(onClick = { pickFor = items.size }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.Inventory2, null); Text(" " + stringResource(R.string.add_saved_item))
        }
    }
    if (pickFor >= 0) com.cashbook.app.ui.components.SearchPickerSheet(stringResource(R.string.pick_item),
        catalog.filter { !it.archived }.map { c ->
            com.cashbook.app.ui.components.PickItem(c.id, c.name, listOfNotNull(f.amount(if (purchase) c.purchaseRate else c.saleRate) + (if (c.unit.isNotBlank()) " / ${c.unit}" else ""),
                Gst.rateLabel(c.gstBp), if (c.tracksStock) stringResource(R.string.in_stock_x, Gst.formatQuantity(onHand(c)), c.unit) else null).joinToString(" · "))
        },
        onPick = { p ->
            val c = catalog.firstOrNull { it.id == p?.id }
            if (c != null) {
                val draft = ItemDraft.from(c, purchase)
                // replace an empty line in place, otherwise append
                val target = pickFor
                onChange(if (target < items.size) items.toMutableList().also { it[target] = draft.copy(qty = items[target].qty.ifBlank { "1" }) } else items + draft)
            }
            pickFor = -1
        }, onDismiss = { pickFor = -1 })
}

/** Taxable value, CGST/SGST or IGST, round off and grand total. */
@Composable
fun TotalsCard(t: InvoiceTotals) {
    val f = LocalUiFormat.current
    SectionCard(stringResource(if (t.interState) R.string.supply_inter else R.string.supply_intra)) {
        @Composable fun line(label: String, v: Long, bold: Boolean = false) = Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
            Text(label, Modifier.weight(1f), fontWeight = if (bold) FontWeight.SemiBold else null)
            Text(f.amount(v), fontWeight = if (bold) FontWeight.SemiBold else null)
        }
        line(stringResource(R.string.taxable_value), t.taxable)
        t.breakup.filter { it.tax > 0 }.forEach { b ->
            if (t.interState) line("IGST @ ${Gst.rateLabel(b.gstBp)}", b.igst)
            else { line("CGST @ ${Gst.rateLabel(b.gstBp / 2)}", b.cgst); line("SGST @ ${Gst.rateLabel(b.gstBp / 2)}", b.sgst) }
        }
        if (t.roundOff != 0L) line(stringResource(R.string.round_off), t.roundOff)
        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        line(stringResource(R.string.grand_total), t.grandTotal, bold = true)
    }
}
