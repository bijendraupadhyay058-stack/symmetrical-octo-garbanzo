package com.docdesk.core

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkspaceTest {
    @Test fun years() {
        assertEquals("FY 2024-25", Workspace.financialYear(LocalDate.of(2025, 3, 31)))
        assertEquals("FY 2025-26", Workspace.financialYear(LocalDate.of(2025, 4, 1)))
        assertEquals("AY 2025-26", Workspace.assessmentYear(LocalDate.of(2025, 3, 31)))
        assertEquals("FY 2099-00", Workspace.financialYear(LocalDate.of(2099, 6, 1)))
        assertEquals("FY 2008-09", Workspace.financialYear(LocalDate.of(2008, 6, 1)))
        assertEquals(listOf("FY 2025-26", "FY 2024-25"), Workspace.recentFinancialYears(LocalDate.of(2025, 11, 21), 2))
    }

    @Test fun tagsAndSearch() {
        assertEquals(listOf("GST", "march"), Workspace.parseTags(" GST, march ; gst ,, "))
        assertTrue(Workspace.matches("sharma gst", "Sharma Traders", "GSTR-3B March.pdf"))
        assertFalse(Workspace.matches("sharma tds", "Sharma Traders", "GSTR-3B March.pdf"))
        assertTrue(Workspace.matches("  ", "x"))
        assertTrue(Workspace.checklistTemplates.keys.containsAll(listOf("ITR filing", "GST registration", "Tax audit", "Company annual filing", "Client document collection")))
    }
}

class BatchNamingTest {
    @Test fun patterns() {
        val d = LocalDate.of(2025, 11, 21)
        assertEquals("Invoice 5 (compressed)", BatchNaming.name(BatchNaming.DEFAULT, "Invoice 5", 0, 3, "compressed", d))
        assertEquals("07 - Sharma_GST - 2025-11-21", BatchNaming.name("{n} - {name} - {date}", "Sharma/GST", 6, 12, "x", d))
        assertEquals("Stmt part 2", BatchNaming.name("{name}", "Stmt", 0, 1, "split", d, part = 2))
        assertEquals("Stmt-2", BatchNaming.name("{name}-{part}", "Stmt", 0, 1, "split", d, part = 2))
        assertEquals(listOf("a.pdf", "A (2).pdf", "b.pdf"), BatchNaming.unique(listOf("a.pdf", "A.pdf", "b.pdf")))
    }
}
