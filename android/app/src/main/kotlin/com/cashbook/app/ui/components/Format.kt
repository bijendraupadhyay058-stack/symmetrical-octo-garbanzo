package com.cashbook.app.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.res.stringResource
import com.cashbook.app.R
import com.cashbook.core.AccountType
import com.cashbook.core.CurrencyDisplay
import com.cashbook.core.DateFormatOption
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.PartyType
import com.cashbook.core.PaymentMode
import com.cashbook.core.PeriodPreset
import com.cashbook.core.ReportType
import com.cashbook.core.SortOrder
import com.cashbook.core.TxnType
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Formatting preferences shared through the composition. */
data class UiFormat(val currency: CurrencyDisplay = CurrencyDisplay.SYMBOL, val dateFormat: DateFormatOption = DateFormatOption.DD_MM_YYYY) {
    val money = MoneyFormatter(currency)
    fun amount(paise: Long) = money.format(paise)
    fun date(d: LocalDate) = dateFormat.format(d)
    fun dateTime(millis: Long): String {
        val dt = java.time.Instant.ofEpochMilli(millis).atZone(java.time.ZoneId.systemDefault())
        return dateFormat.format(dt.toLocalDate()) + " " + dt.format(DateTimeFormatter.ofPattern("HH:mm"))
    }
}

val LocalUiFormat = staticCompositionLocalOf { UiFormat() }

@Composable fun txnTypeLabel(t: TxnType) = stringResource(when (t) {
    TxnType.INCOME -> R.string.type_income; TxnType.EXPENSE -> R.string.type_expense; TxnType.TRANSFER -> R.string.type_transfer })

@Composable fun paymentModeLabel(m: PaymentMode) = stringResource(when (m) {
    PaymentMode.CASH -> R.string.mode_cash; PaymentMode.UPI -> R.string.mode_upi; PaymentMode.BANK_TRANSFER -> R.string.mode_bank_transfer
    PaymentMode.CARD -> R.string.mode_card; PaymentMode.CHEQUE -> R.string.mode_cheque; PaymentMode.OTHER -> R.string.mode_other })

@Composable fun accountTypeLabel(t: AccountType) = stringResource(when (t) {
    AccountType.CASH -> R.string.acct_cash; AccountType.BANK -> R.string.acct_bank; AccountType.WALLET -> R.string.acct_wallet
    AccountType.OTHER -> R.string.acct_other })

@Composable fun partyTypeLabel(t: PartyType) = stringResource(when (t) {
    PartyType.CUSTOMER -> R.string.party_customer; PartyType.SUPPLIER -> R.string.party_supplier; PartyType.EMPLOYEE -> R.string.party_employee
    PartyType.SERVICE_PROVIDER -> R.string.party_service_provider; PartyType.CLIENT -> R.string.party_client; PartyType.OTHER -> R.string.party_other })

@Composable fun periodLabel(p: PeriodPreset) = stringResource(when (p) {
    PeriodPreset.TODAY -> R.string.period_today; PeriodPreset.THIS_WEEK -> R.string.period_this_week
    PeriodPreset.THIS_MONTH -> R.string.period_this_month; PeriodPreset.LAST_MONTH -> R.string.period_last_month
    PeriodPreset.THIS_FY -> R.string.period_this_fy; PeriodPreset.LAST_FY -> R.string.period_last_fy
    PeriodPreset.THIS_YEAR -> R.string.period_this_year; PeriodPreset.ALL_TIME -> R.string.period_all_time
    PeriodPreset.CUSTOM -> R.string.period_custom })

@Composable fun sortLabel(s: SortOrder) = stringResource(when (s) {
    SortOrder.LATEST -> R.string.sort_latest; SortOrder.OLDEST -> R.string.sort_oldest
    SortOrder.HIGHEST -> R.string.sort_highest; SortOrder.LOWEST -> R.string.sort_lowest })

fun reportTitleRes(t: ReportType) = when (t) {
    ReportType.DAILY_CASHBOOK -> R.string.report_daily; ReportType.MONTHLY_SUMMARY -> R.string.report_monthly
    ReportType.YEARLY_SUMMARY -> R.string.report_yearly; ReportType.FINANCIAL_YEAR -> R.string.report_fy
    ReportType.CATEGORY_WISE -> R.string.report_category; ReportType.PARTY_WISE -> R.string.report_party
    ReportType.ACCOUNT_WISE -> R.string.report_account; ReportType.INCOME_EXPENSE -> R.string.report_income_expense
    ReportType.TRANSFERS -> R.string.report_transfers; ReportType.CUSTOM -> R.string.report_custom
    ReportType.OUTSTANDING -> R.string.report_outstanding
}

fun reportDescRes(t: ReportType) = when (t) {
    ReportType.DAILY_CASHBOOK -> R.string.report_daily_desc; ReportType.MONTHLY_SUMMARY -> R.string.report_monthly_desc
    ReportType.YEARLY_SUMMARY -> R.string.report_yearly_desc; ReportType.FINANCIAL_YEAR -> R.string.report_fy_desc
    ReportType.CATEGORY_WISE -> R.string.report_category_desc; ReportType.PARTY_WISE -> R.string.report_party_desc
    ReportType.ACCOUNT_WISE -> R.string.report_account_desc; ReportType.INCOME_EXPENSE -> R.string.report_income_expense_desc
    ReportType.TRANSFERS -> R.string.report_transfers_desc; ReportType.CUSTOM -> R.string.report_custom_desc
    ReportType.OUTSTANDING -> R.string.report_outstanding_desc
}
