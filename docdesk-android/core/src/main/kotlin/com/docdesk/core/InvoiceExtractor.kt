package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate

/** Key fields of a GST tax invoice. Each value keeps the line it was read from, for review. */
data class InvoiceRecord(
    val source: String,
    val invoiceNo: String?,
    val date: LocalDate?,
    val dateRaw: String?,
    val supplierGstin: String?,
    val buyerGstin: String?,
    val taxable: BigDecimal?,
    val cgst: BigDecimal?,
    val sgst: BigDecimal?,
    val igst: BigDecimal?,
    val cess: BigDecimal?,
    val total: BigDecimal?,
    val flags: List<String>,
    val evidence: Map<String, String>,
    val supplierName: String? = null,
    val buyerName: String? = null,
    val invoiceType: String? = null,
    val items: List<InvoiceItem> = emptyList(),
    /** 1-based page where the invoice number (or first field) was found. */
    val page: Int = 1,
    val reviewed: Boolean = false,
    val edited: Boolean = false,
)

/** One line item: description, HSN/SAC code and its taxable/amount value, exactly as read. */
data class InvoiceItem(val description: String, val hsnSac: String, val amount: BigDecimal?, val page: Int)

/**
 * Reads invoice fields from labelled text ("Invoice No", "CGST", "Grand Total", …). Values
 * that are not clearly labelled are left blank; nothing is calculated into a field. Checks
 * (GSTIN checksums, tax arithmetic, CGST = SGST, IGST vs intra-state) produce review flags.
 */
object InvoiceExtractor {
    private val money = Regex("""\(?-?(?:₹|Rs\.?|INR)?\s?\d[\d,]*\.\d{1,2}\)?""")
    private val gstinRx = Regex("""\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b""")
    private val invNoRx = Regex("""(?i)\b(?:tax\s+)?(?:invoice|inv|bill)\s*(?:no|number|num|#)\.?\s*[:\-#]?\s*([A-Z0-9][A-Z0-9/\-_.]{1,30})""")
    private val dateRx = Regex("""\b(\d{1,2}[/\-.](?:\d{1,2}|[A-Za-z]{3,9})[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{2,4})\b""")

    private val typeRx = Regex("""(?i)\b(tax\s+invoice|bill\s+of\s+supply|credit\s+note|debit\s+note|export\s+invoice|revised\s+invoice|proforma\s+invoice|delivery\s+challan)\b""")

    /** Line items from a table whose header names an HSN or SAC column. */
    fun items(page: PageText, style: NumberStyle): List<InvoiceItem> {
        val out = mutableListOf<InvoiceItem>()
        for (t in TableExtractor.extract(page)) {
            val h = t.header?.cells?.map { it.raw.lowercase() } ?: continue
            val hsn = h.indexOfFirst { it.contains("hsn") || it.contains("sac") }.takeIf { it >= 0 } ?: continue
            val desc = h.indexOfFirst { Regex("desc|particular|item|goods|service|product").containsMatchIn(it) }.takeIf { it >= 0 }
                ?: h.indices.filter { it != hsn && t.columnTypes.getOrNull(it) == ColumnType.TEXT }.maxByOrNull { c -> t.bodyRows.sumOf { it.cells.getOrNull(c)?.raw?.length ?: 0 } }
            val amt = h.indexOfLast { Regex("taxable|amount|value|total").containsMatchIn(it) }.takeIf { it >= 0 }
            for (r in t.bodyRows) {
                val code = r.cells.getOrNull(hsn)?.raw?.trim().orEmpty()
                if (!Regex("""^\d{4,8}$""").matches(code)) continue
                out.add(InvoiceItem(desc?.let { r.cells.getOrNull(it)?.raw?.trim() }.orEmpty(), code, amt?.let { r.cells.getOrNull(it)?.raw }?.let { AmountParser.parse(it, style)?.value?.abs() }, page.pageIndex + 1))
            }
        }
        return out
    }

    private fun lastAmount(line: String, style: NumberStyle): BigDecimal? =
        money.findAll(line).mapNotNull { AmountParser.parse(it.value.trim(), style)?.value?.abs() }.lastOrNull()

    fun extract(pages: List<PageText>, source: String, style: NumberStyle = NumberStyle.INDIAN, order: DateOrder = DateOrder.DMY): InvoiceRecord {
        val linePages = pages.take(3).flatMap { p -> LineGrouper.group(p.words).map { it.text to p.pageIndex + 1 } }
        val lines = linePages.map { it.first }
        val evidence = LinkedHashMap<String, String>()
        val flags = mutableListOf<String>()

        // GSTINs: buyer is the one on/after a "bill to / buyer / recipient" label.
        val gstins = mutableListOf<Pair<String, Int>>()
        lines.forEachIndexed { i, l -> gstinRx.findAll(l).forEach { gstins.add(it.value to i) } }
        val buyerLabel = lines.indexOfFirst { Regex("""(?i)bill(ed)?\s*to|buyer|recipient|customer|consignee|ship(ped)?\s*to""").containsMatchIn(it) }
        val distinct = gstins.distinctBy { it.first }
        var buyer = if (buyerLabel >= 0) distinct.firstOrNull { it.second >= buyerLabel } else null
        var supplier = distinct.firstOrNull { it != buyer }
        if (buyer == null && distinct.size >= 2) buyer = distinct[1]
        if (supplier == buyer) supplier = null
        supplier?.let { evidence["Supplier GSTIN"] = lines[it.second] }
        buyer?.let { evidence["Buyer GSTIN"] = lines[it.second] }
        listOfNotNull(supplier?.first, buyer?.first).forEach { if (!SensitiveFinder.gstinValid(it)) flags.add("GSTIN $it fails the checksum – check for a misread character") }
        if (supplier == null) flags.add("Supplier GSTIN not found")

        val invLine = lines.firstOrNull { invNoRx.containsMatchIn(it) }
        val invNo = invLine?.let { invNoRx.find(it)!!.groupValues[1].trimEnd('.', '-') }?.takeIf { v -> v.any(Char::isDigit) && !v.equals("date", true) }
        if (invNo != null) evidence["Invoice no."] = invLine!! else flags.add("Invoice number not found")

        val dateLine = lines.firstOrNull { Regex("""(?i)(invoice|bill)?\s*date|dated""").containsMatchIn(it) && dateRx.containsMatchIn(it) }
            ?: lines.firstOrNull { dateRx.containsMatchIn(it) }
        val dateRaw = dateLine?.let { dl -> dateRx.findAll(dl).map { it.value }.firstOrNull { DateParser.parse(it, order) != null } }
        val date = dateRaw?.let { DateParser.parse(it, order) }
        if (date != null) evidence["Date"] = dateLine!! else flags.add("Invoice date not found")

        fun labelled(key: String, rx: Regex, exclude: Regex? = null, last: Boolean = false): BigDecimal? {
            val cands = lines.filter { rx.containsMatchIn(it) && (exclude == null || !exclude.containsMatchIn(it)) }.mapNotNull { l -> lastAmount(l, style)?.let { l to it } }
            val pick = if (last) cands.lastOrNull() else cands.firstOrNull()
            pick?.let { evidence[key] = it.first }
            return pick?.second
        }
        val taxable = labelled("Taxable value", Regex("""(?i)taxable\s*(value|amount|amt)|sub[\s-]?total|assessable\s*value"""))
        val cgst = labelled("CGST", Regex("""(?i)\bcgst\b|central\s+tax"""), Regex("""(?i)total.*(cgst.*sgst|tax)"""))
        val sgst = labelled("SGST/UTGST", Regex("""(?i)\b(sgst|utgst)\b|state\s+tax"""), Regex("""(?i)total.*(cgst.*sgst|tax)"""))
        val igst = labelled("IGST", Regex("""(?i)\bigst\b|integrated\s+tax"""), Regex("""(?i)total.*tax"""))
        val cess = labelled("Cess", Regex("""(?i)\bcess\b"""))
        val total = labelled("Total", Regex("""(?i)grand\s*total|invoice\s*(total|value)|total\s*(invoice\s*)?(amount|value)|amount\s*payable|net\s*payable|^\s*total\b"""), Regex("""(?i)taxable|total\s*tax|in\s*words"""), last = true)
        if (total == null) flags.add("Invoice total not found")
        if (taxable == null) flags.add("Taxable value not found")

        // Checks – never used to fill missing fields.
        if (taxable != null && total != null) {
            val sum = taxable + (cgst ?: BigDecimal.ZERO) + (sgst ?: BigDecimal.ZERO) + (igst ?: BigDecimal.ZERO) + (cess ?: BigDecimal.ZERO)
            if ((sum - total).abs() > BigDecimal("1.00")) flags.add("Taxable + taxes = ${AmountParser.formatIndian(sum)} but total is ${AmountParser.formatIndian(total)} (check round-off, discounts or misread values)")
        }
        if (cgst != null && sgst != null && (cgst - sgst).abs() > BigDecimal("0.01")) flags.add("CGST and SGST differ")
        val sState = supplier?.first?.take(2); val bState = buyer?.first?.take(2)
        if (sState != null && bState != null) {
            if (sState == bState && igst != null && igst.signum() != 0) flags.add("IGST charged although supplier and buyer are in the same state ($sState)")
            if (sState != bState && (cgst != null || sgst != null) && igst == null) flags.add("CGST/SGST charged although supplier ($sState) and buyer ($bState) are in different states")
        }
        // Invoice type from its title.
        val typeLine = lines.firstOrNull { typeRx.containsMatchIn(it) }
        val type = typeLine?.let { l -> typeRx.find(l)!!.value.split(Regex("""\s+""")).joinToString(" ") { w -> w.lowercase().replaceFirstChar { it.uppercase() } } }
        if (type != null) evidence["Invoice type"] = typeLine
        // Names come from the layout (near the GSTIN / after "Bill to"), so they are shown for checking, never relied on.
        fun clean(t: String) = t.replace(Regex("""(?i)\bgstin\b.*$"""), "").replace(Regex("""(?i)^.*?(bill(ed)?\s*to|buyer|recipient|customer|consignee)\s*[:\-]?\s*"""), "")
            .substringBefore(',').trim().trim(':', '-', ' ').takeIf { it.count(Char::isLetter) >= 3 && !typeRx.containsMatchIn(it) && !invNoRx.containsMatchIn(it) }
        val supplierName = supplier?.let { (_, li) -> clean(lines[li]) ?: (li - 1 downTo maxOf(0, li - 3)).firstNotNullOfOrNull { j -> clean(lines[j]) } }
            ?: lines.take(4).firstNotNullOfOrNull { clean(it) }
        supplierName?.let { evidence["Supplier name"] = lines.first { l -> l.contains(it) } }
        val buyerName = if (buyerLabel >= 0) (clean(lines[buyerLabel]) ?: lines.getOrNull(buyerLabel + 1)?.let { clean(it) }) else null
        buyerName?.let { evidence["Customer name"] = lines.first { l -> l.contains(it) } }
        val items = pages.take(3).flatMap { items(it, style) }
        val page = invLine?.let { l -> linePages.first { it.first == l }.second } ?: 1
        return InvoiceRecord(source, invNo, date, dateRaw, supplier?.first, buyer?.first, taxable, cgst, sgst, igst, cess, total, flags, evidence,
            supplierName, buyerName, type, items, page)
    }

    fun toSheets(records: List<InvoiceRecord>): List<XSheet> {
        val f = ExcelExport.INDIAN_FORMAT
        fun n(v: BigDecimal?) = XStyledCell(v?.let { XCell.Number(it, f) } ?: XCell.Blank)
        fun t(v: String?, hl: Boolean = false) = XStyledCell(XCell.Text(v ?: ""), highlight = hl)
        val head = listOf("Invoice type", "Invoice no.", "Date", "Supplier name", "Supplier GSTIN", "Customer name", "Customer GSTIN", "Taxable value", "CGST", "SGST/UTGST", "IGST", "Cess", "Total",
            "Source file", "Page", "Review notes", "Reviewed", "Edited").map { XStyledCell(XCell.Text(it), bold = true) }
        val rows = records.map { r -> listOf(
            t(r.invoiceType), t(r.invoiceNo, r.invoiceNo == null),
            XStyledCell(r.date?.let { XCell.Date(DateParser.toExcelSerial(it)) } ?: XCell.Text(r.dateRaw ?: ""), highlight = r.date == null),
            t(r.supplierName), t(r.supplierGstin), t(r.buyerName), t(r.buyerGstin),
            n(r.taxable), n(r.cgst), n(r.sgst), n(r.igst), n(r.cess), n(r.total),
            t(r.source), XStyledCell(XCell.Number(BigDecimal(r.page))), t(r.flags.joinToString("; "), r.flags.isNotEmpty() && !r.reviewed),
            t(if (r.reviewed) "Yes" else ""), t(if (r.edited) "Yes" else ""),
        ) }
        fun sum(sel: (InvoiceRecord) -> BigDecimal?) = records.mapNotNull(sel).fold(BigDecimal.ZERO, BigDecimal::add)
        val blank = XStyledCell(XCell.Blank)
        val totals = listOf(XStyledCell(XCell.Text("Total (${records.size} invoices)"), bold = true)) + List(6) { blank } + listOf(
            XStyledCell(XCell.Number(sum { it.taxable }, f), bold = true), XStyledCell(XCell.Number(sum { it.cgst }, f), bold = true), XStyledCell(XCell.Number(sum { it.sgst }, f), bold = true),
            XStyledCell(XCell.Number(sum { it.igst }, f), bold = true), XStyledCell(XCell.Number(sum { it.cess }, f), bold = true), XStyledCell(XCell.Number(sum { it.total }, f), bold = true))
        val items = listOf(listOf("Source file", "Invoice no.", "Description", "HSN/SAC", "Amount", "Page").map { XStyledCell(XCell.Text(it), bold = true) }) +
            records.flatMap { r -> r.items.map { listOf(t(r.source), t(r.invoiceNo), t(it.description), t(it.hsnSac), n(it.amount), XStyledCell(XCell.Number(BigDecimal(it.page)))) } }
        val evidence = listOf(listOf("Source file", "Field", "Read from this line").map { XStyledCell(XCell.Text(it), bold = true) }) +
            records.flatMap { r -> r.evidence.map { (k, v) -> listOf(t(r.source), t(k), t(v)) } }
        val notes = listOf(
            "GSTIN check: only the format and check digit are tested. This does not confirm that a GSTIN is registered or active – verify on the GST portal.",
            "Duplicate check: invoices with the same supplier, invoice number and financial year are flagged for you to confirm; genuine repeats can be marked reviewed.",
            "Total check: taxable value + CGST + SGST/UTGST + IGST + cess is compared with the invoice total (₹1 tolerance for round-off).",
            "Supplier and customer names are read from the layout and may be incomplete. Values not clearly labelled are left blank – never calculated or guessed.",
            "DocDesk does not decide input tax credit eligibility or whether an invoice is valid.",
        ).map { listOf(t(it)) }
        return listOf(
            XSheet("Invoice register", listOf(head) + rows + listOf(emptyList(), totals), listOf(14.0, 18.0, 12.0, 26.0, 18.0, 26.0, 18.0, 15.0, 12.0, 12.0, 12.0, 10.0, 15.0, 28.0, 6.0, 60.0, 9.0, 8.0), freezeTopRow = true, autoFilter = true),
            XSheet("Line items", items, listOf(28.0, 18.0, 50.0, 10.0, 15.0, 6.0), freezeTopRow = true, autoFilter = items.size > 1),
            XSheet("Where values came from", evidence, listOf(28.0, 16.0, 90.0)),
            XSheet("About the checks", listOf(listOf(t("Notes"))) + notes, listOf(120.0)),
        )
    }
}

/** Optional register-level checks. They add review flags; they never change values. */
object InvoiceChecks {
    enum class Field(val label: String, val get: (InvoiceRecord) -> Any?) {
        INVOICE_NO("Invoice number", { it.invoiceNo }), DATE("Invoice date", { it.date }), SUPPLIER_GSTIN("Supplier GSTIN", { it.supplierGstin }),
        CUSTOMER_GSTIN("Customer GSTIN", { it.buyerGstin }), SUPPLIER_NAME("Supplier name", { it.supplierName }), TAXABLE("Taxable value", { it.taxable }),
        TOTAL("Invoice total", { it.total }), HSN("HSN/SAC on items", { r -> r.items.takeIf { it.isNotEmpty() } }),
    }

    private fun fy(d: LocalDate?) = d?.let { Workspace.financialYear(it) } ?: "unknown year"
    private fun norm(s: String?) = s?.uppercase()?.replace(Regex("[^A-Z0-9]"), "")

    /** Adds duplicate and mandatory-field flags. Already-reviewed records keep their flags list unchanged. */
    fun apply(records: List<InvoiceRecord>, mandatory: Set<Field>): List<InvoiceRecord> {
        val seen = HashMap<String, InvoiceRecord>()
        return records.map { r ->
            val extra = mutableListOf<String>()
            mandatory.filter { f -> f.get(r) == null }.forEach { extra.add("Required field missing: ${it.label}") }
            val supplierKey = norm(r.supplierGstin) ?: norm(r.supplierName)
            val inv = norm(r.invoiceNo)
            if (supplierKey != null && inv != null) {
                val key = "$supplierKey|$inv|${fy(r.date)}"
                val prev = seen[key]
                if (prev != null) extra.add("Possible duplicate of ${prev.source} (same supplier, invoice no. and ${fy(r.date)}) – confirm before using")
                else seen[key] = r
            }
            if (extra.isEmpty()) r else r.copy(flags = (r.flags + extra).distinct())
        }
    }
}
