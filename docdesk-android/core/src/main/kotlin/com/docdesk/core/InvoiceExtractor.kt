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
)

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

    private fun lastAmount(line: String, style: NumberStyle): BigDecimal? =
        money.findAll(line).mapNotNull { AmountParser.parse(it.value.trim(), style)?.value?.abs() }.lastOrNull()

    fun extract(pages: List<PageText>, source: String, style: NumberStyle = NumberStyle.INDIAN, order: DateOrder = DateOrder.DMY): InvoiceRecord {
        val lines = pages.take(3).flatMap { p -> LineGrouper.group(p.words).map { it.text } }
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
        return InvoiceRecord(source, invNo, date, dateRaw, supplier?.first, buyer?.first, taxable, cgst, sgst, igst, cess, total, flags, evidence)
    }

    fun toSheets(records: List<InvoiceRecord>): List<XSheet> {
        val f = ExcelExport.INDIAN_FORMAT
        fun n(v: BigDecimal?) = XStyledCell(v?.let { XCell.Number(it, f) } ?: XCell.Blank)
        val head = listOf("Invoice no.", "Date", "Supplier GSTIN", "Buyer GSTIN", "Taxable value", "CGST", "SGST/UTGST", "IGST", "Cess", "Total", "Source file", "Review").map { XStyledCell(XCell.Text(it), bold = true) }
        val rows = records.map { r -> listOf(
            XStyledCell(XCell.Text(r.invoiceNo ?: ""), highlight = r.invoiceNo == null),
            XStyledCell(r.date?.let { XCell.Date(DateParser.toExcelSerial(it)) } ?: XCell.Text(r.dateRaw ?: ""), highlight = r.date == null),
            XStyledCell(XCell.Text(r.supplierGstin ?: "")), XStyledCell(XCell.Text(r.buyerGstin ?: "")),
            n(r.taxable), n(r.cgst), n(r.sgst), n(r.igst), n(r.cess), n(r.total),
            XStyledCell(XCell.Text(r.source)), XStyledCell(XCell.Text(r.flags.joinToString("; ")), highlight = r.flags.isNotEmpty()),
        ) }
        fun sum(sel: (InvoiceRecord) -> BigDecimal?) = records.mapNotNull(sel).fold(BigDecimal.ZERO, BigDecimal::add)
        val totals = listOf(XStyledCell(XCell.Text("Total (${records.size} invoices)"), bold = true), XStyledCell(XCell.Blank), XStyledCell(XCell.Blank), XStyledCell(XCell.Blank),
            XStyledCell(XCell.Number(sum { it.taxable }, f), bold = true), XStyledCell(XCell.Number(sum { it.cgst }, f), bold = true), XStyledCell(XCell.Number(sum { it.sgst }, f), bold = true),
            XStyledCell(XCell.Number(sum { it.igst }, f), bold = true), XStyledCell(XCell.Number(sum { it.cess }, f), bold = true), XStyledCell(XCell.Number(sum { it.total }, f), bold = true))
        val evidence = listOf(listOf("Source file", "Field", "Read from this line").map { XStyledCell(XCell.Text(it), bold = true) }) +
            records.flatMap { r -> r.evidence.map { (k, v) -> listOf(XStyledCell(XCell.Text(r.source)), XStyledCell(XCell.Text(k)), XStyledCell(XCell.Text(v))) } }
        return listOf(
            XSheet("Invoice register", listOf(head) + rows + listOf(emptyList(), totals), listOf(18.0, 12.0, 18.0, 18.0, 15.0, 12.0, 12.0, 12.0, 10.0, 15.0, 28.0, 60.0), freezeTopRow = true),
            XSheet("Where values came from", evidence, listOf(28.0, 16.0, 90.0)),
        )
    }
}
