package com.docdesk.core

import java.time.LocalDate

enum class DocStatus(val label: String) { PENDING_REVIEW("Pending review"), REVIEWED("Reviewed"), COMPLETED("Completed") }

enum class FolderKind(val label: String) { FINANCIAL_YEAR("Financial year"), ASSESSMENT_YEAR("Assessment year"), CATEGORY("Document category"), OTHER("Folder") }

/** Helpers for the client workspace that don't need Android. */
object Workspace {
    val categories = listOf("GST", "Income Tax", "Bank Statements", "Audit", "TDS", "MCA", "Other")

    /** Indian financial year (April–March) containing [d], e.g. "FY 2024-25". */
    fun financialYear(d: LocalDate): String { val y = if (d.monthValue >= 4) d.year else d.year - 1; return "FY $y-${(y + 1) % 100}".let { it.replace(Regex("-(\\d)$"), "-0$1") } }

    /** Assessment year for the financial year containing [d], e.g. "AY 2025-26". */
    fun assessmentYear(d: LocalDate): String { val y = (if (d.monthValue >= 4) d.year else d.year - 1) + 1; return "AY $y-${((y + 1) % 100).toString().padStart(2, '0')}" }

    /** The current and previous [n] financial years, newest first. */
    fun recentFinancialYears(today: LocalDate, n: Int = 4): List<String> = (0 until n).map { financialYear(today.minusYears(it.toLong())) }
    fun recentAssessmentYears(today: LocalDate, n: Int = 4): List<String> = (0 until n).map { assessmentYear(today.minusYears(it.toLong())) }

    /** Tags typed as "gst, march , urgent" → ["gst","march","urgent"] (trimmed, de-duplicated, case kept). */
    fun parseTags(s: String): List<String> = s.split(',', ';').map { it.trim() }.filter { it.isNotEmpty() }.distinctBy { it.lowercase() }

    /** Case-insensitive match of every word of [query] against any of the [fields]. */
    fun matches(query: String, vararg fields: String?): Boolean {
        val words = query.lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (words.isEmpty()) return true
        val hay = fields.filterNotNull().joinToString(" ").lowercase()
        return words.all { hay.contains(it) }
    }

    /** Ready-made checklists. Starting points only – adjust them to the client and current rules. */
    val checklistTemplates: Map<String, List<String>> = linkedMapOf(
        "ITR filing" to listOf(
            "PAN and Aadhaar (linked)", "Form 16 / salary certificates", "Form 26AS and AIS / TIS downloaded and reviewed",
            "Bank statements for the year (all accounts)", "Interest certificates (savings, FD, RD)", "Capital gains statements (shares, mutual funds, property)",
            "Rent receipts / HRA details", "Deduction proofs (80C, 80D, 80G, home loan interest)", "Business/profession: books, P&L, balance sheet",
            "Advance tax / self-assessment tax challans", "Previous year's return and carried-forward losses", "Bank account for refund (pre-validated)",
            "Regime choice confirmed with client", "Return reviewed with client before filing", "E-verification done",
        ),
        "GST registration" to listOf(
            "PAN of the business", "Proof of constitution (partnership deed / incorporation certificate)", "Photographs of proprietor / partners / directors",
            "Identity and address proof of promoters", "Proof of principal place of business (rent agreement / electricity bill / NOC)",
            "Bank account proof (cancelled cheque / statement)", "Authorisation letter / board resolution for authorised signatory",
            "Details of goods/services (HSN/SAC)", "Aadhaar authentication completed", "ARN received", "Registration certificate downloaded",
        ),
        "Tax audit" to listOf(
            "Books of account and trial balance", "Financial statements (P&L, balance sheet)", "Bank statements and reconciliations",
            "Fixed asset register and depreciation working", "Stock records and valuation", "TDS returns and challans; Form 26AS / AIS",
            "GST returns and reconciliation with books", "Loans and deposits (section 269SS/269T) details", "Cash payments above limits checked",
            "Related-party transactions", "Previous year's audit report", "Form 3CD clauses reviewed", "Management representation letter", "Audit report uploaded and accepted by client",
        ),
        "Company annual filing" to listOf(
            "Audited financial statements", "Directors' report", "Auditor's report", "Board meeting minutes approving accounts",
            "AGM notice and minutes", "Shareholding pattern / list of shareholders", "Director KYC (DIR-3 KYC) status checked",
            "AOC-4 prepared and filed", "MGT-7 / MGT-7A prepared and filed", "Auditor appointment (ADT-1) if applicable", "Challans / SRNs saved",
        ),
        "Client document collection" to listOf(
            "Engagement letter signed", "KYC: PAN, Aadhaar, address proof", "Contact details and authorised person confirmed",
            "Bank statements received", "Sales and purchase invoices received", "Previous returns and acknowledgements",
            "Login access arranged (where the client agrees)", "Missing documents requested from client", "All documents reviewed",
        ),
    )
}
