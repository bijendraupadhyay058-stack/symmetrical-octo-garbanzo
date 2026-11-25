package com.cashbook.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.ui.reports.reportLabels
import com.cashbook.app.R
import com.cashbook.core.AccountType
import com.cashbook.core.Cell
import com.cashbook.core.CategoryKind
import com.cashbook.core.DateRange
import com.cashbook.core.Ledger
import com.cashbook.core.PaymentMode
import com.cashbook.core.Reconcile
import com.cashbook.core.ReportEngine
import com.cashbook.core.ReportInput
import com.cashbook.core.ReportType
import com.cashbook.core.RowStyle
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate

/** Categories learned from typed entries, and the bank reconciliation statement. */
@RunWith(AndroidJUnit4::class)
class Phase15Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    @Test fun typedEntriesTeachWithoutOverriding(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.cashbookId == cb && it.type == AccountType.CASH }
        val exp = s.categories.filter { it.kind == CategoryKind.EXPENSE && it.parentId == null }
        val power = exp.first { it.name == "Electricity" }.id
        val other = exp.first { it.id != power }.id
        val rulesBefore = s.categoryRules.size
        repo.saveTxn(Txn(0, cb, TxnType.EXPENSE, today, 180_000, cash.id, categoryId = power, description = "Electricity bill May"), emptyList(), emptyList())
        s = d.snap { it.categoryRules.size == rulesBefore + 1 }
        assertEquals(power, s.categoryRules.single { it.key == "ELECTRICITY BILL" }.categoryId)
        assertEquals(power, repo.ruleCategory("Electricity bill June 2026", TxnType.EXPENSE))
        // a later entry with the same wording in another category doesn't replace what was learned
        repo.saveTxn(Txn(0, cb, TxnType.EXPENSE, today, 1_000, cash.id, categoryId = other, description = "Electricity bill late fee"), emptyList(), emptyList())
        s = d.snap { it.txns.any { t -> t.description == "Electricity bill late fee" } }
        assertEquals(power, s.categoryRules.single { it.key == "ELECTRICITY BILL" }.categoryId)
        // transfers and uncategorised entries teach nothing
        val n = s.categoryRules.size
        repo.saveTxn(Txn(0, cb, TxnType.EXPENSE, today, 500, cash.id, description = "Tea and snacks"), emptyList(), emptyList())
        d.snap { it.txns.any { t -> t.description == "Tea and snacks" } }.let { assertEquals(n, it.categoryRules.size) }
    }

    @Test fun reconciliationStatementOnRealData(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val bank = s.accounts.first { it.cashbookId == cb && it.type == AccountType.BANK }
        val fees = s.categories.first { it.kind == CategoryKind.INCOME }.id
        // reconcile everything so far, then a cheque deposited today that the bank hasn't credited yet
        repo.reconcile(bank.id, today, Ledger.balanceAsOf(bank, s.txns, today), Reconcile.uncleared(bank, s.txns, today).map { it.id })
        repo.saveTxn(Txn(0, cb, TxnType.INCOME, today, 300_000, bank.id, categoryId = fees, paymentMode = PaymentMode.CHEQUE, reference = "CHQ 552",
            description = "Cheque from ABC"), emptyList(), emptyList())
        s = d.snap { it.reconciliations.isNotEmpty() && it.txns.any { t -> t.reference == "CHQ 552" } }
        val r = ReportEngine(ReportInput(ReportType.BANK_RECONCILIATION, "Office", accounts = s.accounts, selectedAccountIds = setOf(bank.id),
            categories = s.categoryById, parties = s.partyById, txns = s.txns, range = DateRange(today, today), generatedAt = "now",
            labels = reportLabels(context()), reconciliations = s.reconciliations)).build()
        val rows = r.tables.single().rows
        val books = Ledger.balanceAsOf(bank, s.txns, today)
        assertEquals(Cell.Amount(books), rows.first().cells[2])
        assertEquals(Cell.Text("Cheque from ABC · CHQ 552"), rows[2].cells[1])
        assertEquals(Cell.Amount(books - 300_000), rows.single { it.style == RowStyle.TOTAL }.cells[2])   // what the bank shows
        assertEquals(Cell.Amount(s.reconciliations.single().statementBalance), rows.last().cells[2])
        assertEquals(context().getString(R.string.report_brs), r.title)
    }
}
