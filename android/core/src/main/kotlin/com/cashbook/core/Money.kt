package com.cashbook.core

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Money is always held as a [Long] number of **paise** (1 rupee = 100 paise).
 * No floating point arithmetic is ever used for amounts.
 */
object Money {
    /** Largest accepted single amount: ₹9,99,99,99,999.99 (well inside Long range for sums). */
    const val MAX_PAISE: Long = 99_999_999_999L

    sealed interface ParseResult {
        data class Ok(val paise: Long) : ParseResult
        data class Error(val reason: AmountError) : ParseResult
    }

    enum class AmountError { EMPTY, INVALID, ZERO_OR_NEGATIVE, TOO_MANY_DECIMALS, TOO_LARGE }

    /**
     * Parses user input such as `15000`, `1,25,000.50` or `₹ 2,500` into paise.
     * Rejects zero, negative values, more than two decimals and non-numeric text.
     */
    fun parse(input: String): ParseResult {
        val clean = input.trim().replace("₹", "").replace(",", "").replace(" ", "")
        if (clean.isEmpty()) return ParseResult.Error(AmountError.EMPTY)
        if (!clean.matches(Regex("^-?\\d*(\\.\\d*)?$")) || clean == "." || clean == "-") {
            return ParseResult.Error(AmountError.INVALID)
        }
        val bd = try { BigDecimal(clean) } catch (e: NumberFormatException) {
            return ParseResult.Error(AmountError.INVALID)
        }
        if (bd.signum() <= 0) return ParseResult.Error(AmountError.ZERO_OR_NEGATIVE)
        if (bd.stripTrailingZeros().scale() > 2) return ParseResult.Error(AmountError.TOO_MANY_DECIMALS)
        val paise = bd.movePointRight(2).setScale(0, RoundingMode.UNNECESSARY)
        if (paise > BigDecimal.valueOf(MAX_PAISE)) return ParseResult.Error(AmountError.TOO_LARGE)
        return ParseResult.Ok(paise.longValueExact())
    }

    /** Parses an opening balance, which may be zero (but not negative). */
    fun parseOpening(input: String): ParseResult {
        val clean = input.trim().replace("₹", "").replace(",", "").replace(" ", "")
        if (clean.isEmpty()) return ParseResult.Ok(0)
        if (clean.matches(Regex("^0*(\\.0*)?$"))) return ParseResult.Ok(0)
        return parse(input)
    }

    /** Plain editable text for a form field, e.g. 1250050 → "12500.50". */
    fun toPlain(paise: Long): String {
        val bd = BigDecimal.valueOf(paise).movePointLeft(2).setScale(2)
        val s = bd.toPlainString()
        return if (s.endsWith(".00")) s.dropLast(3) else s
    }

    /** Machine-readable decimal string with exactly two decimals, e.g. "12500.50". */
    fun toDecimalString(paise: Long): String =
        BigDecimal.valueOf(paise).movePointLeft(2).setScale(2).toPlainString()

    /**
     * Indian digit grouping: 12500050 paise → "1,25,000.50".
     * [prefix] is placed after the minus sign, e.g. "-₹1,500.00".
     */
    fun formatIndian(paise: Long, prefix: String = "₹"): String {
        val negative = paise < 0
        val abs = if (paise == Long.MIN_VALUE) Long.MAX_VALUE else kotlin.math.abs(paise)
        val rupees = abs / 100
        val p = abs % 100
        val sb = StringBuilder()
        if (negative) sb.append('-')
        sb.append(prefix)
        sb.append(groupIndian(rupees.toString()))
        sb.append('.')
        if (p < 10) sb.append('0')
        sb.append(p)
        return sb.toString()
    }

    internal fun groupIndian(digits: String): String {
        if (digits.length <= 3) return digits
        val last3 = digits.takeLast(3)
        var rest = digits.dropLast(3)
        val parts = ArrayList<String>()
        while (rest.length > 2) {
            parts.add(0, rest.takeLast(2))
            rest = rest.dropLast(2)
        }
        if (rest.isNotEmpty()) parts.add(0, rest)
        return parts.joinToString(",") + "," + last3
    }

    /** Percentage with one decimal using integer arithmetic only. */
    fun percent(part: Long, total: Long): String {
        if (total == 0L) return "0.0%"
        val tenths = BigDecimal.valueOf(part).multiply(BigDecimal.valueOf(1000))
            .divide(BigDecimal.valueOf(total), 0, RoundingMode.HALF_UP)
        return BigDecimal(tenths.toBigInteger()).movePointLeft(1).setScale(1).toPlainString() + "%"
    }
}

/** How the currency is shown in the UI and reports (Settings › Financial). */
enum class CurrencyDisplay { SYMBOL, CODE, NONE;
    fun prefix(code: String = "INR"): String = when (this) {
        SYMBOL -> if (code == "INR") "₹" else "$code "
        CODE -> "$code "
        NONE -> ""
    }
}

class MoneyFormatter(private val display: CurrencyDisplay = CurrencyDisplay.SYMBOL, private val code: String = "INR") {
    fun format(paise: Long): String = Money.formatIndian(paise, display.prefix(code))
    /** Signed format used in lists: "+₹15,000.00" / "−₹2,500.00". */
    fun signed(paise: Long): String = if (paise >= 0) "+" + format(paise) else "−" + format(-paise)
}
