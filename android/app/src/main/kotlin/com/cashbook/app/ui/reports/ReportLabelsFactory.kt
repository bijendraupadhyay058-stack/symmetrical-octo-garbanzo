package com.cashbook.app.ui.reports

import android.content.Context
import com.cashbook.app.R
import com.cashbook.app.ui.components.reportTitleRes
import com.cashbook.core.PaymentMode
import com.cashbook.core.ReportLabels
import com.cashbook.core.ReportType
import com.cashbook.core.TxnType

/** Builds report text from string resources so PDFs/Excel follow the app language. */
fun reportLabels(c: Context): ReportLabels {
    fun s(id: Int) = c.getString(id)
    return ReportLabels(
        titles = ReportType.entries.associateWith { s(reportTitleRes(it)) },
        types = mapOf(TxnType.INCOME to s(R.string.type_income), TxnType.EXPENSE to s(R.string.type_expense), TxnType.TRANSFER to s(R.string.type_transfer)),
        modes = mapOf(PaymentMode.CASH to s(R.string.mode_cash), PaymentMode.UPI to s(R.string.mode_upi), PaymentMode.BANK_TRANSFER to s(R.string.mode_bank_transfer),
            PaymentMode.CARD to s(R.string.mode_card), PaymentMode.CHEQUE to s(R.string.mode_cheque), PaymentMode.OTHER to s(R.string.mode_other)),
        date = s(R.string.date), particulars = s(R.string.rl_particulars), account = s(R.string.account), category = s(R.string.category),
        party = s(R.string.party), description = s(R.string.description), type = s(R.string.rl_type), mode = s(R.string.payment_mode),
        reference = s(R.string.reference_number), cashbook = s(R.string.cashbook), receipts = s(R.string.rl_receipts), payments = s(R.string.rl_payments),
        balance = s(R.string.rl_balance), income = s(R.string.income), expense = s(R.string.type_expense), expenses = s(R.string.expenses),
        transfer = s(R.string.type_transfer), transfers = s(R.string.rl_transfers), transfersNet = s(R.string.rl_transfers_net),
        transferIn = s(R.string.rl_transfer_in), transferOut = s(R.string.rl_transfer_out), transferSource = s(R.string.rl_transfer_source),
        transferDestination = s(R.string.rl_transfer_destination), from = s(R.string.rl_from), to = s(R.string.rl_to), amount = s(R.string.amount),
        count = s(R.string.rl_count), percent = s(R.string.rl_percent), month = s(R.string.rl_month), net = s(R.string.rl_net),
        opening = s(R.string.opening_balance), openingOf = s(R.string.rl_opening_of), closing = s(R.string.closing_balance),
        totalIncome = s(R.string.rl_total_income), totalExpenses = s(R.string.rl_total_expenses), netSurplus = s(R.string.rl_net_surplus),
        netDeficit = s(R.string.rl_net_deficit), netSurplusOrDeficit = s(R.string.rl_net_surplus_deficit), total = s(R.string.rl_total),
        totalTransactions = s(R.string.rl_total_entries), daySummary = s(R.string.rl_day_summary), dayDetail = s(R.string.rl_day_detail),
        accountBalances = s(R.string.account_balances), monthWise = s(R.string.rl_month_wise), incomeByCategory = s(R.string.rl_income_by_category),
        expenseByCategory = s(R.string.rl_expense_by_category), uncategorised = s(R.string.uncategorised), transferArrow = "%s → %s",
        cashBasisNote = s(R.string.rl_cash_basis_note), partyNote = s(R.string.rl_party_note), transferNote = s(R.string.rl_transfer_note),
    )
}
