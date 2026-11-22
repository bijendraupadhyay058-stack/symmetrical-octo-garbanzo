package com.cashbook.core

import java.time.LocalDate

/** The sample cashbook from the specification, used by several tests. */
object SampleScenario {
    val d = { day: Int -> LocalDate.of(2026, 4, day) }
    val cash = AccountInfo(1, 1, "Office Cash", AccountType.CASH, 1_000_000, d(1))
    val sbi = AccountInfo(2, 1, "SBI Bank", AccountType.BANK, 5_000_000, d(1))
    val accounts = listOf(cash, sbi)
    val fees = CategoryInfo(10, CategoryKind.INCOME, "Professional fees")
    val stationery = CategoryInfo(20, CategoryKind.EXPENSE, "Printing and stationery")
    val internet = CategoryInfo(21, CategoryKind.EXPENSE, "Telephone and internet")
    val categories = listOf(fees, stationery, internet).associateBy { it.id }
    val txns = listOf(
        Txn(1, 1, TxnType.INCOME, d(2), 1_500_000, sbi.id, categoryId = fees.id, paymentMode = PaymentMode.UPI, description = "Professional fees received", createdAt = 1),
        Txn(2, 1, TxnType.EXPENSE, d(3), 150_000, cash.id, categoryId = stationery.id, description = "Office stationery", createdAt = 2),
        Txn(3, 1, TxnType.EXPENSE, d(4), 100_000, sbi.id, categoryId = internet.id, paymentMode = PaymentMode.BANK_TRANSFER, description = "Internet bill", createdAt = 3),
        Txn(4, 1, TxnType.TRANSFER, d(5), 500_000, sbi.id, toAccountId = cash.id, description = "SBI Bank to Office Cash", createdAt = 4),
    )
}
