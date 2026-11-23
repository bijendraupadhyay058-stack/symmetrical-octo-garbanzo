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
    val discount: String = "", val gstBp: Int = 1800,
) {
    val quantityMilli get() = Gst.parseQuantity(qty)
    val ratePaise get() = (Money.parseOpening(rate) as? Money.ParseResult.Ok)?.paise
    val discountBp get() = Gst.parsePercent(discount)
    val valid get() = description.isNotBlank() && quantityMilli != null && ratePaise != null && discountBp != null
    fun toItem() = InvoiceItem(0, description, hsn, quantityMilli!!, unit, ratePaise!!, discountBp!!, gstBp)

    companion object {
        fun from(i: InvoiceItem) = ItemDraft(i.description, i.hsn, Gst.formatQuantity(i.quantityMilli), i.unit, Money.toPlain(i.rate),
            if (i.discountBp == 0) "" else Gst.formatPercent(i.discountBp), i.gstBp)

        val ListSaver: Saver<List<ItemDraft>, Any> = Saver(
            save = { l -> l.map { arrayListOf(it.description, it.hsn, it.qty, it.unit, it.rate, it.discount, it.gstBp.toString()) } },
            restore = { raw -> (raw as List<*>).map { r -> val a = r as List<*>
                ItemDraft(a[0] as String, a[1] as String, a[2] as String, a[3] as String, a[4] as String, a[5] as String, (a[6] as String).toInt()) } },
        )
    }
}

/** Line items edited in place (no dialogs): description, HSN/SAC, qty, unit, rate, discount and GST rate per line. */
@Composable
fun InvoiceItemsEditor(items: List<ItemDraft>, onChange: (List<ItemDraft>) -> Unit, showErrors: Boolean, totals: InvoiceTotals?) {
    val f = LocalUiFormat.current
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.forEachIndexed { i, d ->
            fun upd(n: ItemDraft) = onChange(items.toMutableList().also { it[i] = n })
            SectionCard(stringResource(R.string.item_n, i + 1), action = {
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
    }
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
