package com.docdesk.core

import java.math.BigDecimal
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AnalysisTest {
    private fun row(d: String, narr: String, dr: String?, cr: String?) =
        StatementRow(LocalDate.parse(d), d, narr, "", dr?.let { BigDecimal(it) }, cr?.let { BigDecimal(it) }, null, "", "s.pdf", 1)

    @Test fun counterparties() {
        assertEquals("RAMESH TRADERS", StatementAnalysis.counterparty("UPI/DR/412345678901/RAMESH TRADERS/YESB/ramesh@ybl/Payment"))
        assertEquals("ACME PVT LTD", StatementAnalysis.counterparty("NEFT-HDFCN52024040112345-ACME PVT LTD-SALARY APR"))
        assertEquals("BIG BAZAAR", StatementAnalysis.counterparty("POS 4111XXXXXX1111 BIG BAZAAR"))
    }

    @Test fun rulesAndSummaries() {
        val rules = LedgerRule.parse("# my rules\nSALARY => Salary A/c\nRENT = Rent Expense\nATM: Cash\nbad line")
        assertEquals(3, rules.size)
        val rows = listOf(row("2024-04-02", "UPI rent April", "15000", null), row("2024-04-30", "NEFT SALARY ACME", null, "80000"), row("2024-05-03", "ATM WDL MG ROAD", "5000", null))
        val m = StatementAnalysis.monthly(rows)
        assertEquals(listOf("Apr 2024", "May 2024"), m.map { it.key })
        assertEquals(BigDecimal("80000"), m[0].credit)
        val c = StatementAnalysis.categories(rows, rules).associateBy { it.key }
        assertEquals(BigDecimal("15000"), c["Rent Expense"]!!.debit)
        assertEquals(3, StatementAnalysis.sheets(rows, rules).size)
    }

    @Test fun tallyXml() {
        val rules = LedgerRule.parse("SALARY => Salary Received\nATM => Cash")
        val rows = listOf(
            StatementRow(LocalDate.of(2024, 4, 30), "30/04/2024", "NEFT SALARY <ACME> & Co", "N123", null, BigDecimal("80000.5"), null, "", "s", 1),
            StatementRow(LocalDate.of(2024, 5, 3), "03/05/2024", "ATM WDL", "", BigDecimal("5000"), null, null, "", "s", 1),
            StatementRow(LocalDate.of(2024, 5, 4), "04/05/2024", "Unknown", "", BigDecimal("10"), null, null, "", "s", 1),
            StatementRow(null, "??", "No date", "", BigDecimal("1"), null, null, "", "s", 1),
        )
        val r = TallyXml.build(rows, TallyXml.Options("HDFC Bank A/c", rules = rules))
        assertEquals(3, r.vouchers); assertEquals(1, r.skipped); assertEquals(1, r.suspense)
        assertTrue(r.xml.contains("VCHTYPE=\"Receipt\""))
        assertTrue(r.xml.contains("<LEDGERNAME>HDFC Bank A/c</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-80000.50</AMOUNT>"))
        assertTrue(r.xml.contains("<LEDGERNAME>Salary Received</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>80000.50</AMOUNT>"))
        assertTrue(r.xml.contains("VCHTYPE=\"Contra\""))
        assertTrue(r.xml.contains("&lt;ACME&gt; &amp; Co"))
        assertTrue(r.xml.contains("<DATE>20240503</DATE>"))
        // XML must be well-formed
        javax.xml.parsers.DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(r.xml.byteInputStream())
    }
}
