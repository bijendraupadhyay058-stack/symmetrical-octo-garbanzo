package com.cashbook.core

import java.math.BigDecimal
import java.math.RoundingMode

/** Indian GST helpers: state codes, GSTIN check digit, and rate list. */
object Gst {
    /**
     * Rates in basis points (1800 = 18 %). Includes the slabs in force from 22 Sep 2025 (5, 18, 40)
     * and the earlier 12 / 28 % so older invoices can still be entered.
     */
    val RATES_BP = listOf(0, 25, 300, 500, 1200, 1800, 2800, 4000)

    /** GST state / UT codes (first two digits of a GSTIN). */
    val STATES: Map<String, String> = linkedMapOf(
        "01" to "Jammu and Kashmir", "02" to "Himachal Pradesh", "03" to "Punjab", "04" to "Chandigarh", "05" to "Uttarakhand",
        "06" to "Haryana", "07" to "Delhi", "08" to "Rajasthan", "09" to "Uttar Pradesh", "10" to "Bihar", "11" to "Sikkim",
        "12" to "Arunachal Pradesh", "13" to "Nagaland", "14" to "Manipur", "15" to "Mizoram", "16" to "Tripura", "17" to "Meghalaya",
        "18" to "Assam", "19" to "West Bengal", "20" to "Jharkhand", "21" to "Odisha", "22" to "Chhattisgarh", "23" to "Madhya Pradesh",
        "24" to "Gujarat", "26" to "Dadra and Nagar Haveli and Daman and Diu", "27" to "Maharashtra", "29" to "Karnataka", "30" to "Goa",
        "31" to "Lakshadweep", "32" to "Kerala", "33" to "Tamil Nadu", "34" to "Puducherry", "35" to "Andaman and Nicobar Islands",
        "36" to "Telangana", "37" to "Andhra Pradesh", "38" to "Ladakh", "97" to "Other Territory",
    )

    fun stateLabel(code: String) = STATES[code]?.let { "$code – $it" } ?: ""

    private const val CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    /** Structure and check-digit validation of a 15-character GSTIN. */
    fun isValidGstin(input: String): Boolean {
        val g = input.trim().uppercase()
        if (!g.matches(Regex("^[0-9]{2}[A-Z0-9]{10}[0-9A-Z][Z0-9A-Z][0-9A-Z]$"))) return false
        if (g.substring(0, 2) !in STATES) return false
        return checkDigit(g.substring(0, 14)) == g[14]
    }

    /** GSTIN checksum (mod-36, alternating weights 1 and 2). */
    fun checkDigit(first14: String): Char {
        var sum = 0
        first14.forEachIndexed { i, c ->
            val v = CHARS.indexOf(c)
            require(v >= 0) { "invalid character" }
            val product = v * (if (i % 2 == 0) 1 else 2)
            sum += product / 36 + product % 36
        }
        return CHARS[(36 - sum % 36) % 36]
    }

    fun stateFromGstin(gstin: String): String? = gstin.trim().takeIf { it.length >= 2 }?.substring(0, 2)?.takeIf { it in STATES }

    /** Quantity text → thousandths ("1.5" → 1500). Positive, at most 3 decimals; null when invalid. */
    fun parseQuantity(text: String): Long? = runCatching {
        val bd = BigDecimal(text.trim().replace(",", ""))
        if (bd.signum() <= 0 || bd.stripTrailingZeros().scale() > 3) null else bd.movePointRight(3).setScale(0, RoundingMode.UNNECESSARY).longValueExact()
            .takeIf { it <= 1_000_000_000L }
    }.getOrNull()

    /** Percentage text → basis points ("12.5" → 1250). 0–100, at most 2 decimals; blank = 0; null when invalid. */
    fun parsePercent(text: String): Int? {
        if (text.isBlank()) return 0
        return runCatching {
            val bd = BigDecimal(text.trim())
            if (bd.signum() < 0 || bd > BigDecimal(100) || bd.stripTrailingZeros().scale() > 2) null
            else bd.movePointRight(2).setScale(0, RoundingMode.UNNECESSARY).intValueExact()
        }.getOrNull()
    }

    fun formatQuantity(milli: Long): String = BigDecimal.valueOf(milli).movePointLeft(3).stripTrailingZeros().toPlainString()
    fun formatPercent(bp: Int): String = BigDecimal.valueOf(bp.toLong()).movePointLeft(2).stripTrailingZeros().toPlainString()

    /** "18%", "0.25%". */
    fun rateLabel(bp: Int): String = BigDecimal.valueOf(bp.toLong()).movePointLeft(2).stripTrailingZeros().toPlainString() + "%"
}

/** One invoice line. Quantity in thousandths (1.5 kg = 1500), rate per unit in paise, discount and GST in basis points. */
data class InvoiceItem(
    val id: Long = 0,
    val description: String,
    val hsn: String = "",
    val quantityMilli: Long = 1000,
    val unit: String = "",
    val rate: Long,
    val discountBp: Int = 0,
    val gstBp: Int = 0,
)

data class LineTotals(val item: InvoiceItem, val gross: Long, val discount: Long, val taxable: Long, val cgst: Long, val sgst: Long, val igst: Long) {
    val tax: Long get() = cgst + sgst + igst
    val total: Long get() = taxable + tax
}

data class RateBreakup(val gstBp: Int, val taxable: Long, val cgst: Long, val sgst: Long, val igst: Long) {
    val tax: Long get() = cgst + sgst + igst
}

data class InvoiceTotals(
    val lines: List<LineTotals>,
    val interState: Boolean,
    val breakup: List<RateBreakup>,
    val taxable: Long,
    val cgst: Long,
    val sgst: Long,
    val igst: Long,
    val roundOff: Long,
) {
    val tax: Long get() = cgst + sgst + igst
    val beforeRounding: Long get() = taxable + tax
    val grandTotal: Long get() = beforeRounding + roundOff
}

object GstCalc {
    private fun round(v: BigDecimal): Long = v.setScale(0, RoundingMode.HALF_UP).longValueExact()

    /**
     * Tax is calculated per line and rounded to the paisa (CGST and SGST each at half the rate for a
     * supply within the state; IGST for an inter-state supply). With [roundOff] the grand total is
     * rounded to the nearest rupee and the difference shown as "Round off".
     */
    fun totals(items: List<InvoiceItem>, interState: Boolean, roundOff: Boolean): InvoiceTotals {
        val lines = items.map { it ->
            val gross = round(BigDecimal.valueOf(it.quantityMilli).multiply(BigDecimal.valueOf(it.rate)).divide(BigDecimal.valueOf(1000)))
            val discount = round(BigDecimal.valueOf(gross).multiply(BigDecimal.valueOf(it.discountBp.toLong())).divide(BigDecimal.valueOf(10_000)))
            val taxable = gross - discount
            val t = BigDecimal.valueOf(taxable)
            if (interState) LineTotals(it, gross, discount, taxable, 0, 0, round(t.multiply(BigDecimal.valueOf(it.gstBp.toLong())).divide(BigDecimal.valueOf(10_000))))
            else {
                val half = round(t.multiply(BigDecimal.valueOf(it.gstBp.toLong())).divide(BigDecimal.valueOf(20_000)))
                LineTotals(it, gross, discount, taxable, half, half, 0)
            }
        }
        val breakup = lines.groupBy { it.item.gstBp }.toSortedMap().map { (bp, l) ->
            RateBreakup(bp, l.sumOf { it.taxable }, l.sumOf { it.cgst }, l.sumOf { it.sgst }, l.sumOf { it.igst })
        }
        val taxable = lines.sumOf { it.taxable }
        val cgst = lines.sumOf { it.cgst }; val sgst = lines.sumOf { it.sgst }; val igst = lines.sumOf { it.igst }
        val before = taxable + cgst + sgst + igst
        val ro = if (roundOff) round(BigDecimal.valueOf(before).movePointLeft(2)) * 100 - before else 0L
        return InvoiceTotals(lines, interState, breakup, taxable, cgst, sgst, igst, ro)
    }

    /** Supply is inter-state when both states are known and differ. Unknown states default to intra-state. */
    fun isInterState(sellerState: String, placeOfSupply: String) = sellerState.isNotBlank() && placeOfSupply.isNotBlank() && sellerState != placeOfSupply
}

/** Amount in words using the Indian system: "Rupees One Lakh Twenty-Five Thousand and Fifty Paise Only". */
object AmountInWords {
    private val ones = listOf("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
    private val tens = listOf("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")

    private fun twoDigits(n: Int): String = if (n < 20) ones[n] else tens[n / 10] + (if (n % 10 != 0) "-" + ones[n % 10] else "")
    private fun threeDigits(n: Int): String {
        val h = n / 100; val r = n % 100
        return listOfNotNull(if (h > 0) ones[h] + " Hundred" else null, if (r > 0) twoDigits(r) else null).joinToString(" ")
    }

    fun words(n: Long): String {
        if (n == 0L) return "Zero"
        val parts = ArrayList<String>()
        var x = n
        val crore = x / 10_000_000; x %= 10_000_000
        val lakh = x / 100_000; x %= 100_000
        val thousand = x / 1000; x %= 1000
        if (crore > 0) parts += words(crore) + " Crore"
        if (lakh > 0) parts += twoDigits(lakh.toInt()) + " Lakh"
        if (thousand > 0) parts += twoDigits(thousand.toInt()) + " Thousand"
        if (x > 0) parts += threeDigits(x.toInt())
        return parts.joinToString(" ")
    }

    fun rupees(paise: Long): String {
        val r = kotlin.math.abs(paise) / 100; val p = (kotlin.math.abs(paise) % 100).toInt()
        val sb = StringBuilder("Rupees ").append(words(r))
        if (p > 0) sb.append(" and ").append(twoDigits(p)).append(" Paise")
        return sb.append(" Only").toString()
    }
}
