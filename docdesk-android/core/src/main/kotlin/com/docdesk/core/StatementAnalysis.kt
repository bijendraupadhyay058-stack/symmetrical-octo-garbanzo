package com.docdesk.core

import java.math.BigDecimal
import java.time.format.DateTimeFormatter

/** A user rule: narration contains [keyword] → [ledger] (used as category and as Tally ledger). */
data class LedgerRule(val keyword: String, val ledger: String) {
    companion object {
        /** Parses lines like "SALARY => Salary A/c" (also "=" or ":"); ignores blanks and #comments. */
        fun parse(text: String): List<LedgerRule> = text.lines().map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }.mapNotNull { l ->
            val parts = l.split(Regex("""\s*(=>|->|=|:)\s*"""), limit = 2)
            if (parts.size == 2 && parts[0].isNotBlank() && parts[1].isNotBlank()) LedgerRule(parts[0].trim(), parts[1].trim()) else null
        }
    }
}

/** Month-wise, party-wise and category summaries of normalised bank transactions. */
object StatementAnalysis {
    private val noise = setOf("UPI", "DR", "CR", "P2A", "P2M", "IMPS", "NEFT", "RTGS", "MMT", "INB", "BIL", "ONL", "ACH", "ECS", "NACH", "POS", "ATM", "TRF", "TO", "BY", "FROM",
        "TRANSFER", "PAYMENT", "PAY", "CHQ", "CHEQUE", "CLG", "INW", "OUTW", "REF", "TXN", "YESB", "HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "PUNB", "BARB", "CNRB", "IDIB", "UBIN", "INDB", "FDRL", "PAYTM", "YBL", "OKAXIS", "OKHDFCBANK", "OKSBI", "OKICICI", "IBL", "AXL", "APL")

    /**
     * Best guess of the other party from a narration, e.g. "UPI/DR/412345678901/RAMESH TRADERS/YESB/…" → "RAMESH TRADERS".
     * Clearly labelled as a guess in outputs; the original narration is always kept.
     */
    fun counterparty(narration: String): String {
        val n = narration.uppercase().replace(Regex("""\s+"""), " ").trim()
        if (n.isEmpty()) return "(blank)"
        val parts = n.split(Regex("""[/\-:|]""")).map { it.trim() }.filter { it.isNotEmpty() }
        val candidate = parts.firstOrNull { p ->
            val letters = p.count(Char::isLetter)
            letters >= 3 && p.count(Char::isDigit) <= 2 && p.split(" ").all { it !in noise } && !p.contains('@') && p !in noise
        } ?: parts.firstOrNull { it.count(Char::isLetter) >= 3 && it !in noise }
        val name = (candidate ?: n).replace(Regex("""\d"""), "").replace(Regex("""\s+"""), " ").trim()
        // Drop masked card/account fragments such as "XXXXXX" or "****".
        return name.split(" ").filter { it !in noise && !Regex("""^[X*#]{2,}$""").matches(it) }.take(4).joinToString(" ").ifEmpty { "(unclear)" }
    }

    fun category(narration: String, rules: List<LedgerRule>): String? = rules.firstOrNull { narration.contains(it.keyword, ignoreCase = true) }?.ledger

    data class Bucket(val key: String, var count: Int = 0, var debit: BigDecimal = BigDecimal.ZERO, var credit: BigDecimal = BigDecimal.ZERO)

    private fun summarise(rows: List<StatementRow>, key: (StatementRow) -> String): List<Bucket> {
        val m = LinkedHashMap<String, Bucket>()
        for (r in rows) {
            val b = m.getOrPut(key(r)) { Bucket(key(r)) }
            b.count++; r.debit?.let { b.debit += it }; r.credit?.let { b.credit += it }
        }
        return m.values.toList()
    }

    fun monthly(rows: List<StatementRow>): List<Bucket> {
        val f = DateTimeFormatter.ofPattern("yyyy-MM MMM yyyy")
        return summarise(rows.filter { it.date != null }) { it.date!!.format(f) }.sortedBy { it.key }.map { it.copy(key = it.key.substringAfter(' ')) }
    }

    fun parties(rows: List<StatementRow>): List<Bucket> = summarise(rows) { counterparty(it.narration) }.sortedByDescending { it.debit + it.credit }

    fun categories(rows: List<StatementRow>, rules: List<LedgerRule>): List<Bucket> = summarise(rows) { category(it.narration, rules) ?: "Uncategorised" }.sortedByDescending { it.debit + it.credit }

    /** Extra worksheets for the bank-statement workbook. */
    fun sheets(rows: List<StatementRow>, rules: List<LedgerRule>): List<XSheet> {
        val f = ExcelExport.INDIAN_FORMAT
        fun table(title: String, keyName: String, buckets: List<Bucket>, note: String?): List<List<XStyledCell>> {
            val head = listOf(keyName, "Transactions", "Debits (out)", "Credits (in)", "Net (in − out)").map { XStyledCell(XCell.Text(it), bold = true) }
            val body = buckets.map { b -> listOf(XStyledCell(XCell.Text(b.key)), XStyledCell(XCell.Number(BigDecimal(b.count))), XStyledCell(XCell.Number(b.debit, f)), XStyledCell(XCell.Number(b.credit, f)), XStyledCell(XCell.Number(b.credit - b.debit, f))) }
            val tot = listOf(XStyledCell(XCell.Text("Total"), bold = true), XStyledCell(XCell.Number(BigDecimal(buckets.sumOf { it.count })), bold = true),
                XStyledCell(XCell.Number(buckets.fold(BigDecimal.ZERO) { a, b -> a + b.debit }, f), bold = true), XStyledCell(XCell.Number(buckets.fold(BigDecimal.ZERO) { a, b -> a + b.credit }, f), bold = true),
                XStyledCell(XCell.Number(buckets.fold(BigDecimal.ZERO) { a, b -> a + b.credit - b.debit }, f), bold = true))
            return listOf(listOf(XStyledCell(XCell.Text(title), bold = true))) + listOfNotNull(note?.let { listOf(XStyledCell(XCell.Text(it))) }) + listOf(emptyList(), head) + body + listOf(tot)
        }
        val widths = listOf(40.0, 13.0, 16.0, 16.0, 16.0)
        val out = mutableListOf(
            XSheet("Month-wise", table("Month-wise summary", "Month", monthly(rows), null), widths),
            XSheet("Party-wise", table("Party-wise summary", "Party (guessed from narration)", parties(rows), "Party names are read from UPI/NEFT/IMPS narrations and may be incomplete; check the Transactions sheet for the full narration."), widths),
        )
        if (rules.isNotEmpty()) out.add(XSheet("Category-wise", table("Category-wise summary (your rules)", "Category / ledger", categories(rows, rules), null), widths))
        return out
    }
}

/**
 * Tally XML for bank transactions (import via Gateway of Tally › Import › Transactions).
 * Debits become Payment vouchers (Dr expense/party ledger, Cr bank), credits become Receipt
 * vouchers (Dr bank, Cr party/income ledger); rules pointing to the cash ledger produce Contra.
 * Tally convention: debit ledger entries have ISDEEMEDPOSITIVE=Yes and a negative AMOUNT.
 */
object TallyXml {
    data class Options(val bankLedger: String, val defaultLedger: String = "Suspense A/c", val cashLedger: String = "Cash", val rules: List<LedgerRule> = emptyList(), val company: String = "")

    data class Result(val xml: String, val vouchers: Int, val skipped: Int, val suspense: Int)

    private fun esc(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")

    fun build(rows: List<StatementRow>, o: Options): Result {
        val sb = StringBuilder()
        sb.append("<ENVELOPE>\n <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n <BODY>\n  <IMPORTDATA>\n   <REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>")
        if (o.company.isNotBlank()) sb.append("<STATICVARIABLES><SVCURRENTCOMPANY>${esc(o.company)}</SVCURRENTCOMPANY></STATICVARIABLES>")
        sb.append("</REQUESTDESC>\n   <REQUESTDATA>\n")
        var count = 0; var skipped = 0; var suspense = 0
        val fmt = DateTimeFormatter.ofPattern("yyyyMMdd")
        for (r in rows) {
            val date = r.date
            val debit = r.debit?.takeIf { it.signum() > 0 }; val credit = r.credit?.takeIf { it.signum() > 0 }
            if (date == null || (debit == null) == (credit == null)) { skipped++; continue } // need a date and exactly one of debit/credit
            val ruleLedger = StatementAnalysis.category(r.narration, o.rules)
            val other = ruleLedger ?: o.defaultLedger.also { suspense++ }
            val amount = (debit ?: credit)!!.setScale(2, java.math.RoundingMode.HALF_UP).toPlainString()
            val type = when { other.equals(o.cashLedger, true) -> "Contra"; debit != null -> "Payment"; else -> "Receipt" }
            // Money out: Dr other / Cr bank. Money in: Dr bank / Cr other.
            val (drLedger, crLedger) = if (debit != null) other to o.bankLedger else o.bankLedger to other
            val narration = listOf(r.narration, r.reference.takeIf { it.isNotBlank() }?.let { "Ref $it" }).filterNotNull().joinToString(" · ")
            sb.append("    <TALLYMESSAGE xmlns:UDF=\"TallyUDF\">\n     <VOUCHER VCHTYPE=\"$type\" ACTION=\"Create\">\n")
            sb.append("      <DATE>${date.format(fmt)}</DATE>\n      <VOUCHERTYPENAME>$type</VOUCHERTYPENAME>\n      <NARRATION>${esc(narration)}</NARRATION>\n")
            sb.append("      <ALLLEDGERENTRIES.LIST><LEDGERNAME>${esc(drLedger)}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-$amount</AMOUNT></ALLLEDGERENTRIES.LIST>\n")
            sb.append("      <ALLLEDGERENTRIES.LIST><LEDGERNAME>${esc(crLedger)}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>$amount</AMOUNT></ALLLEDGERENTRIES.LIST>\n")
            sb.append("     </VOUCHER>\n    </TALLYMESSAGE>\n")
            count++
        }
        sb.append("   </REQUESTDATA>\n  </IMPORTDATA>\n </BODY>\n</ENVELOPE>\n")
        return Result(sb.toString(), count, skipped, suspense)
    }
}
