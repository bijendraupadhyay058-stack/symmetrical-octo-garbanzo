package com.cashbook.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MoneyTest {
    private fun ok(s: String) = (Money.parse(s) as Money.ParseResult.Ok).paise
    private fun err(s: String) = (Money.parse(s) as Money.ParseResult.Error).reason

    @Test fun parsesValidAmounts() {
        assertEquals(1_500_000L, ok("15000"))
        assertEquals(12_500_050L, ok("1,25,000.50"))
        assertEquals(250_000L, ok("₹ 2,500"))
        assertEquals(10L, ok("0.1"))
        assertEquals(1L, ok("0.01"))
        assertEquals(150L, ok("1.50"))
    }

    @Test fun rejectsInvalidAmounts() {
        assertEquals(Money.AmountError.EMPTY, err(""))
        assertEquals(Money.AmountError.ZERO_OR_NEGATIVE, err("0"))
        assertEquals(Money.AmountError.ZERO_OR_NEGATIVE, err("0.00"))
        assertEquals(Money.AmountError.ZERO_OR_NEGATIVE, err("-5"))
        assertEquals(Money.AmountError.TOO_MANY_DECIMALS, err("1.005"))
        assertEquals(Money.AmountError.INVALID, err("12a"))
        assertEquals(Money.AmountError.INVALID, err("1.2.3"))
        assertEquals(Money.AmountError.INVALID, err("."))
        assertEquals(Money.AmountError.TOO_LARGE, err("99999999999999"))
    }

    @Test fun openingBalanceMayBeZero() {
        assertEquals(0L, (Money.parseOpening("") as Money.ParseResult.Ok).paise)
        assertEquals(0L, (Money.parseOpening("0") as Money.ParseResult.Ok).paise)
        assertEquals(1_000_000L, (Money.parseOpening("10000") as Money.ParseResult.Ok).paise)
        assertTrue(Money.parseOpening("-1") is Money.ParseResult.Error)
    }

    @Test fun formatsIndianGrouping() {
        assertEquals("₹1,25,000.00", Money.formatIndian(12_500_000))
        assertEquals("₹1,25,00,000.50", Money.formatIndian(1_250_000_050))
        assertEquals("₹999.05", Money.formatIndian(99_905))
        assertEquals("₹0.00", Money.formatIndian(0))
        assertEquals("-₹1,500.00", Money.formatIndian(-150_000))
        assertEquals("INR 72,500.00", MoneyFormatter(CurrencyDisplay.CODE).format(7_250_000))
        assertEquals("−₹2,500.00", MoneyFormatter().signed(-250_000))
    }

    @Test fun plainAndDecimalStrings() {
        assertEquals("12500.50", Money.toPlain(1_250_050))
        assertEquals("15000", Money.toPlain(1_500_000))
        assertEquals("12500.50", Money.toDecimalString(1_250_050))
        assertEquals("-0.05", Money.toDecimalString(-5))
    }

    @Test fun percentUsesIntegerMath() {
        assertEquals("33.3%", Money.percent(1, 3))
        assertEquals("100.0%", Money.percent(5, 5))
        assertEquals("0.0%", Money.percent(5, 0))
    }
}
