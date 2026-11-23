package com.cashbook.core

import java.time.LocalDate

enum class ReportType {
    DAILY_CASHBOOK, MONTHLY_SUMMARY, YEARLY_SUMMARY, FINANCIAL_YEAR, CATEGORY_WISE,
    PARTY_WISE, ACCOUNT_WISE, INCOME_EXPENSE, TRANSFERS, CUSTOM, OUTSTANDING, GST_SUMMARY;

    /** Balance-based reports only accept an account filter; others accept every filter. */
    val supportsDetailFilters: Boolean
        get() = this == CUSTOM || this == CATEGORY_WISE || this == PARTY_WISE || this == INCOME_EXPENSE
}

enum class Align { START, END }

data class Column(val title: String, val weight: Float, val align: Align = Align.START)

sealed interface Cell {
    data class Text(val value: String) : Cell
    data class Amount(val paise: Long) : Cell
    data class Count(val value: Int) : Cell
    data class Day(val date: LocalDate) : Cell
    data object Empty : Cell
}

enum class RowStyle { NORMAL, HEADING, SUBTOTAL, TOTAL }

data class Row(val cells: List<Cell>, val style: RowStyle = RowStyle.NORMAL)

data class ReportTable(val title: String?, val columns: List<Column>, val rows: List<Row>)

data class SummaryItem(val label: String, val value: Cell)

data class ReportDocument(
    val type: ReportType,
    val title: String,
    val cashbookName: String,
    val periodLabel: String,
    val filtersLabel: String,
    val generatedAt: String,
    val currency: String,
    val summary: List<SummaryItem>,
    val tables: List<ReportTable>,
    val notes: List<String>,
    /** Flat transaction listing in the standard export columns (used for the Excel "Transactions" sheet). */
    val exportTable: ReportTable,
    val labels: ReportLabels,
) {
    val isEmpty: Boolean get() = tables.all { it.rows.isEmpty() }
}

/**
 * All user-visible report text. English defaults; the Android app fills these from string
 * resources so reports follow the chosen language (English / Hindi).
 */
data class ReportLabels(
    val titles: Map<ReportType, String> = mapOf(
        ReportType.DAILY_CASHBOOK to "Daily Cashbook",
        ReportType.MONTHLY_SUMMARY to "Monthly Summary",
        ReportType.YEARLY_SUMMARY to "Yearly Summary",
        ReportType.FINANCIAL_YEAR to "Financial Year Report",
        ReportType.CATEGORY_WISE to "Category-wise Report",
        ReportType.PARTY_WISE to "Party-wise Transaction Report",
        ReportType.ACCOUNT_WISE to "Account-wise Report",
        ReportType.INCOME_EXPENSE to "Income and Expense Statement",
        ReportType.TRANSFERS to "Transfer Report",
        ReportType.CUSTOM to "Custom Report",
        ReportType.OUTSTANDING to "Outstanding & Ageing",
        ReportType.GST_SUMMARY to "GST Summary",
    ),
    val types: Map<TxnType, String> = mapOf(TxnType.INCOME to "Income", TxnType.EXPENSE to "Expense", TxnType.TRANSFER to "Transfer"),
    val modes: Map<PaymentMode, String> = mapOf(
        PaymentMode.CASH to "Cash", PaymentMode.UPI to "UPI", PaymentMode.BANK_TRANSFER to "Bank transfer",
        PaymentMode.CARD to "Card", PaymentMode.CHEQUE to "Cheque", PaymentMode.OTHER to "Other",
    ),
    val date: String = "Date",
    val particulars: String = "Particulars",
    val account: String = "Account",
    val category: String = "Category",
    val party: String = "Party",
    val description: String = "Description",
    val type: String = "Type",
    val mode: String = "Payment mode",
    val reference: String = "Reference",
    val cashbook: String = "Cashbook",
    val receipts: String = "Receipts",
    val payments: String = "Payments",
    val balance: String = "Balance",
    val income: String = "Income",
    val expense: String = "Expense",
    val expenses: String = "Expenses",
    val transfer: String = "Transfer",
    val transfers: String = "Transfers",
    val transfersNet: String = "Transfers (net)",
    val transferIn: String = "Transfers in",
    val transferOut: String = "Transfers out",
    val transferSource: String = "Transfer source",
    val transferDestination: String = "Transfer destination",
    val from: String = "From",
    val to: String = "To",
    val amount: String = "Amount",
    val count: String = "No. of entries",
    val percent: String = "% of total",
    val month: String = "Month",
    val net: String = "Net",
    val opening: String = "Opening balance",
    val openingOf: String = "Opening balance – %s",
    val closing: String = "Closing balance",
    val totalIncome: String = "Total income",
    val totalExpenses: String = "Total expenses",
    val netSurplus: String = "Net surplus",
    val netDeficit: String = "Net deficit",
    val netSurplusOrDeficit: String = "Net surplus / (deficit)",
    val total: String = "Total",
    val totalTransactions: String = "Total (%d entries)",
    val daySummary: String = "Date-wise summary",
    val dayDetail: String = "Entries",
    val accountBalances: String = "Account balances",
    val monthWise: String = "Month-wise totals",
    val incomeByCategory: String = "Income by category",
    val expenseByCategory: String = "Expenses by category",
    val uncategorised: String = "Uncategorised",
    val transferArrow: String = "%s → %s",
    val cashBasisNote: String = "This report reflects recorded cash movements only. It is not an accrual-based profit and loss account.",
    val partyNote: String = "Shows money actually received from and paid to each party. It is not a receivables/payables ledger.",
    val receivables: String = "Receivable (owed to you)",
    val payables: String = "Payable (you owe)",
    val invoiceNo: String = "Invoice / bill no.",
    val dueDate: String = "Due date",
    val invoiceAmount: String = "Invoice amount",
    val paid: String = "Paid",
    val outstanding: String = "Outstanding",
    val daysOverdue: String = "Days overdue",
    val ageing: String = "Ageing",
    val notDue: String = "Not yet due",
    val days0to30: String = "1–30 days",
    val days31to60: String = "31–60 days",
    val days61to90: String = "61–90 days",
    val days90plus: String = "Over 90 days",
    val outstandingNote: String = "Invoices and bills are amounts owed, not cash movements; they do not change account balances until payments are recorded. Report as at the end of the period.",
    val gstRate: String = "GST rate",
    val taxableValue: String = "Taxable value",
    val cgst: String = "CGST",
    val sgst: String = "SGST / UTGST",
    val igst: String = "IGST",
    val totalTax: String = "Total tax",
    val outputTax: String = "Output tax (sales invoices)",
    val inputTax: String = "Input tax (purchase bills)",
    val netTaxPayable: String = "Net tax (output − input)",
    val invoicesCounted: String = "Itemised invoices counted",
    val gstNote: String = "Based on itemised invoices and bills by invoice date (cancelled ones excluded). Invoices entered as a single amount carry no tax detail and are not included. This is a summary for review, not a GST return.",
    val transferNote: String = "Transfers move money between your own accounts and are not counted as income or expenses.",
)
