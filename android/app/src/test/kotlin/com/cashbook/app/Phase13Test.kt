package com.cashbook.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.Snapshot
import com.cashbook.core.AccountInfo
import com.cashbook.core.AccountType
import com.cashbook.core.Ledger
import com.cashbook.core.Money
import com.cashbook.core.Reconcile
import com.cashbook.core.StatementImport
import com.cashbook.core.StatementMatcher
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Builds a bank-style CSV (withdrawal / deposit / balance) of [bank]'s entries plus [extra] lines (date, text, signed paise). */
fun bankCsv(s: Snapshot, bank: AccountInfo, extra: List<Triple<LocalDate, String, Long>>): Pair<String, Long> {
    val fmt = DateTimeFormatter.ofPattern("dd/MM/yyyy")
    val rows = s.txns.filter { Ledger.touches(it, setOf(bank.id)) }.map { Triple(it.date, it.description.ifBlank { "ENTRY ${it.id}" }, Ledger.effect(it, bank.id)) } + extra
    var bal = bank.openingBalance
    val body = rows.sortedBy { it.first }.joinToString("\n") { (d, text, amt) ->
        bal += amt
        val money = { p: Long -> "\"" + Money.toPlain(p) + "\"" }
        "${d.format(fmt)},\"$text\",,${if (amt < 0) money(-amt) else ""},${if (amt > 0) money(amt) else ""},${money(bal)}"
    }
    return ("Account Statement\nTxn Date,Description,Ref No,Withdrawal Amt,Deposit Amt,Closing Balance\n$body\n") to bal
}

/** Importing a bank statement into a reconciliation. */
@RunWith(AndroidJUnit4::class)
class Phase13Test {
    private val d = deps()
    private val repo = d.ledger

    @Test fun importMatchAddAndReconcile(): Unit = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        var s = d.snap { it.txns.size == 4 }
        val bank = s.accounts.first { it.cashbookId == cb && it.type == AccountType.BANK }
        val last = s.txns.maxOf { it.date }
        val (csv, closing) = bankCsv(s, bank, listOf(Triple(last, "SMS CHARGES INCL GST", -1_770L), Triple(last, "INTEREST CREDIT", 12_500L)))
        val r = StatementImport.parse(csv)
        assertEquals(closing, r.closingBalance)
        assertEquals(last, r.lastDate)

        var (matched, missing) = StatementMatcher.match(r.lines, Reconcile.uncleared(bank, s.txns, last), bank.id)
        val bankEntries = s.txns.count { Ledger.touches(it, setOf(bank.id)) }
        assertEquals(bankEntries, matched.size)
        assertEquals(listOf("SMS CHARGES INCL GST", "INTEREST CREDIT"), missing.map { it.description })

        missing.forEach { repo.addStatementLine(bank.id, it) }
        s = d.snap { it.txns.size == 6 }
        val charge = s.txns.single { it.description == "SMS CHARGES INCL GST" }
        assertEquals(TxnType.EXPENSE, charge.type); assertEquals(1_770L, charge.amount); assertNull(charge.categoryId); assertEquals(bank.id, charge.accountId)
        assertEquals(TxnType.INCOME, s.txns.single { it.description == "INTEREST CREDIT" }.type)

        val open = Reconcile.uncleared(bank, s.txns, last)
        StatementMatcher.match(r.lines, open, bank.id).let { matched = it.first; missing = it.second }
        assertTrue(missing.isEmpty())
        assertEquals(0L, Reconcile.difference(closing, bank, s.txns, matched.map { it.txn }))
        repo.reconcile(bank.id, last, closing, matched.map { it.txn.id })
        s = d.snap { it.reconciliations.isNotEmpty() }
        assertEquals(closing, Reconcile.clearedBalance(bank, s.txns))
        assertEquals(Ledger.balanceAsOf(bank, s.txns, last), closing)                                 // the books now agree with the bank
    }
}
