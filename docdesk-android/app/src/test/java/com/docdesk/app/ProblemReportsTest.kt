package com.docdesk.app

import com.docdesk.app.data.ProblemReports
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProblemReportsTest {
    @Test fun sanitiseRemovesPersonalDetails() {
        val s = ProblemReports.sanitize("java.io.IOException: open failed /storage/emulated/0/Download/Asha Salary Slip.pdf content://com.android.providers/document/123 asha.rao@gmail.com \"HDFC statement March.pdf\" at com.docdesk.app.pdf.PdfOps.assemble(PdfOps.kt:42)")
        assertFalse(s, s.contains("Asha")); assertFalse(s, s.contains("Salary")); assertFalse(s.contains("gmail")); assertFalse(s.contains("HDFC")); assertFalse(s.contains("content://"))
        assertTrue(s.contains("PdfOps.kt:42")) // code locations are kept
    }
}
