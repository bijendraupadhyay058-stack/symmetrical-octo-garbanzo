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
