package com.cashbook.core

import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate

enum class ItemKind { GOODS, SERVICE }

/** A saved product or service. Quantities are in thousandths; rates in paise; GST in basis points. */
data class CatalogItem(
    val id: Long,
    val name: String,
    val kind: ItemKind = ItemKind.GOODS,
    val hsn: String = "",
    val unit: String = "",
    val saleRate: Long = 0,
    val purchaseRate: Long = 0,
    val gstBp: Int = 1800,
    val description: String = "",
    val openingStockMilli: Long = 0,
    val openingDate: LocalDate = LocalDate.of(2000, 1, 1),
    /** Low-stock threshold (0 = no alert). */
    val reorderLevelMilli: Long = 0,
    val archived: Boolean = false,
) {
    val tracksStock: Boolean get() = kind == ItemKind.GOODS
}

/** Manual stock change (damage, counting difference, own use…). Positive adds stock. */
data class StockAdjustment(val id: Long, val itemId: Long, val date: LocalDate, val quantityMilli: Long, val reason: String = "")

/** One stock movement of an item, from a document line or an adjustment. */
data class StockMove(val itemId: Long, val date: LocalDate, val quantityMilli: Long, val docId: Long?, val label: String)

data class StockLine(val item: CatalogItem, val opening: Long, val inward: Long, val outward: Long, val adjusted: Long) {
    val closing: Long get() = opening + inward - outward + adjusted
    /** Closing quantity valued at the item's purchase rate (paise). */
    val value: Long get() = BigDecimal.valueOf(closing).multiply(BigDecimal.valueOf(item.purchaseRate)).divide(BigDecimal.valueOf(1000), 0, RoundingMode.HALF_UP).longValueExact()
    val low: Boolean get() = item.reorderLevelMilli > 0 && closing <= item.reorderLevelMilli
}

data class ItemSales(val key: String, val itemId: Long?, val name: String, val unit: String, val quantityMilli: Long, val taxable: Long, val tax: Long)

object Stock {
    /**
     * Stock effect of a document line: purchase bills add, sales invoices remove, a sales credit note
     * (goods returned to you) adds back, a purchase credit note (goods returned to the supplier) removes.
     * Debit notes are price adjustments and don't move stock. Cancelled documents don't count.
     */
    fun sign(doc: InvoiceInfo): Int = if (doc.cancelled) 0 else when (doc.docType) {
        DocType.INVOICE -> if (doc.kind == InvoiceKind.PURCHASE) 1 else -1
        DocType.CREDIT_NOTE -> if (doc.kind == InvoiceKind.SALE) 1 else -1
        DocType.DEBIT_NOTE, DocType.QUOTATION -> 0
    }

    fun moves(docs: List<InvoiceInfo>, docItems: Map<Long, List<InvoiceItem>>, adjustments: List<StockAdjustment>): List<StockMove> {
        val fromDocs = docs.flatMap { d ->
            val s = sign(d)
            if (s == 0) emptyList() else docItems[d.id].orEmpty().mapNotNull { li ->
                li.itemId?.let { StockMove(it, d.issueDate, s * li.quantityMilli, d.id, d.number) }
            }
        }
        return (fromDocs + adjustments.map { StockMove(it.itemId, it.date, it.quantityMilli, null, it.reason) }).sortedBy { it.date }
    }

    /** Opening / in / out / adjusted / closing for goods over [range] (opening = everything before the start). */
    fun summary(items: List<CatalogItem>, moves: List<StockMove>, range: DateRange): List<StockLine> {
        val byItem = moves.groupBy { it.itemId }
        return items.filter { it.tracksStock }.map { item ->
            val m = byItem[item.id].orEmpty()
            val openingBase = if (item.openingDate.isBefore(range.start)) item.openingStockMilli else 0
            val introduced = if (item.openingDate in range) item.openingStockMilli else 0
            val before = m.filter { it.date.isBefore(range.start) }.sumOf { it.quantityMilli }
            val within = m.filter { it.date in range }
            StockLine(item, openingBase + before,
                inward = within.filter { it.docId != null && it.quantityMilli > 0 }.sumOf { it.quantityMilli } + introduced,
                outward = within.filter { it.docId != null && it.quantityMilli < 0 }.sumOf { -it.quantityMilli },
                adjusted = within.filter { it.docId == null }.sumOf { it.quantityMilli })
        }
    }

    fun onHand(item: CatalogItem, moves: List<StockMove>, asOf: LocalDate = LocalDate.now()): Long =
        (if (!item.openingDate.isAfter(asOf)) item.openingStockMilli else 0) +
            moves.filter { it.itemId == item.id && !it.date.isAfter(asOf) }.sumOf { it.quantityMilli }

    /**
     * Item-wise sales for sales invoices in [range], net of sales credit notes. Lines not linked to a saved
     * item are grouped by description. Taxable value and tax use the same GST rules as the invoice.
     */
    fun itemSales(docs: List<InvoiceInfo>, docItems: Map<Long, List<InvoiceItem>>, catalog: Map<Long, CatalogItem>, sellerState: String, range: DateRange): List<ItemSales> {
        val acc = LinkedHashMap<String, ItemSales>()
        docs.filter { it.kind == InvoiceKind.SALE && !it.cancelled && it.issueDate in range && it.docType != DocType.DEBIT_NOTE && it.docType != DocType.QUOTATION }.forEach { d ->
            val lines = docItems[d.id].orEmpty()
            if (lines.isEmpty()) return@forEach
            val s = if (d.docType == DocType.CREDIT_NOTE) -1 else 1
            GstCalc.totals(lines, GstCalc.isInterState(sellerState, d.placeOfSupply), false).lines.forEach { l ->
                val item = l.item.itemId?.let { catalog[it] }
                val key = item?.let { "#${it.id}" } ?: l.item.description.trim().lowercase()
                val prev = acc[key] ?: ItemSales(key, item?.id, item?.name ?: l.item.description.trim(), item?.unit ?: l.item.unit, 0, 0, 0)
                acc[key] = prev.copy(quantityMilli = prev.quantityMilli + s * l.item.quantityMilli, taxable = prev.taxable + s * l.taxable, tax = prev.tax + s * l.tax)
            }
        }
        return acc.values.sortedByDescending { it.taxable }
    }
}
