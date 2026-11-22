package com.cashbook.app

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.app.data.LedgerRepository.InvoiceException
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.widget.WidgetUpdater
import com.cashbook.app.work.Alerts
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.InvoiceInfo
import com.cashbook.core.InvoiceKind
import com.cashbook.core.InvoiceStatus
import com.cashbook.core.Ledger
import com.cashbook.core.PaymentMode
import com.cashbook.core.TxnType
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDate

/** Invoices/bills with payments, alerts and the widget, against the real database. */
@RunWith(AndroidJUnit4::class)
class Phase3Test {
    private val d = deps()
    private val repo = d.ledger
    private val today = LocalDate.now()

    private data class F(val cb: Long, val bank: Long, val party: Long, val salesCat: Long, val purchaseCat: Long)

    private fun fixture(): F = runBlocking {
        val cb = repo.addSampleData("en", SAMPLE_NAMES)
        val s = d.snap { it.txns.size == 4 }
        val party = repo.saveParty(PartyEntity(name = "ABC Enterprises", type = "CLIENT", createdAt = 0, updatedAt = 0))
        F(cb, s.accounts.first { it.type == AccountType.BANK }.id, party, s.categories.first { it.kind == CategoryKind.INCOME && it.name == "Sales" }.id,
            s.categories.first { it.kind == CategoryKind.EXPENSE && it.name == "Purchases" }.id)
    }

    private suspend fun invoice(f: F, amount: Long = 5_000_000, kind: InvoiceKind = InvoiceKind.SALE, due: LocalDate = today.plusDays(15), number: String? = null) =
        repo.saveInvoice(InvoiceInfo(0, f.cb, kind, number ?: repo.nextInvoiceNumber(f.cb, kind, today), f.party, today, due, amount, "Accounting services"))

    private inline fun expect(reason: InvoiceException.Reason, block: () -> Unit) {
        try { block(); fail("expected $reason") } catch (e: InvoiceException) { assertEquals(reason, e.reason) }
    }

    @Test fun invoiceDoesNotTouchBalancesUntilPaid() = runBlocking {
        val f = fixture()
        val id = invoice(f)
        var s = d.snap { it.invoices.size == 1 }
        val bank = s.accountById[f.bank]!!
        assertEquals(5_900_000L, Ledger.currentBalance(bank, s.txns))     // invoice alone: no cash movement
        assertEquals(InvoiceStatus.OPEN, s.invoiceBalances(today).single().status)

        val pay = repo.recordPayment(id, f.bank, f.salesCat, 2_000_000, today, PaymentMode.UPI, "UPI123", "Payment received")
        s = d.snap { it.allocations.size == 1 }
        val b = s.invoiceBalances(today).single()
        assertEquals(InvoiceStatus.PARTIAL, b.status)
        assertEquals(3_000_000L, b.outstanding)
        val entry = s.txns.first { it.id == pay }
        assertEquals(TxnType.INCOME, entry.type); assertEquals(f.party, entry.partyId); assertEquals("UPI123", entry.reference)
        assertEquals(7_900_000L, Ledger.currentBalance(bank, s.txns))     // payment is real income

        repo.recordPayment(id, f.bank, f.salesCat, 3_000_000, today, PaymentMode.UPI, "", "")
        assertEquals(InvoiceStatus.PAID, d.snap { it.allocations.size == 2 }.invoiceBalances(today).single().status)
        expect(InvoiceException.Reason.INVALID_ALLOCATION) { repo.recordPayment(id, f.bank, f.salesCat, 1, today, PaymentMode.UPI, "", "") }
    }

    @Test fun deletingAndRestoringPaymentReopensAndSettles() = runBlocking {
        val f = fixture()
        val id = invoice(f, 1_000_000)
        val pay = repo.recordPayment(id, f.bank, f.salesCat, 1_000_000, today, PaymentMode.CASH, "", "")
        assertEquals(InvoiceStatus.PAID, d.snap { it.allocations.size == 1 }.invoiceBalances(today).single().status)
        repo.deleteTxn(pay)
        assertEquals(1_000_000L, d.snap { it.deleted.any { t -> t.id == pay } }.invoiceBalances(today).single().outstanding)
        repo.restoreTxn(pay)
        assertEquals(0L, d.snap { it.deleted.isEmpty() }.invoiceBalances(today).single().outstanding)
        repo.purge(listOf(pay).also { repo.deleteTxn(pay) })        // permanent delete removes the link too
        assertTrue(d.snap { it.allocations.isEmpty() }.allocations.isEmpty())
    }

    @Test fun rulesProtectData() = runBlocking {
        val f = fixture()
        val id = invoice(f, 1_000_000, number = "INV/X/1")
        expect(InvoiceException.Reason.DUPLICATE_NUMBER) { invoice(f, number = "inv/x/1") }
        invoice(f, kind = InvoiceKind.PURCHASE, number = "INV/X/1")               // same number for a bill is fine
        val pay = repo.recordPayment(id, f.bank, f.salesCat, 600_000, today, PaymentMode.CASH, "", "")
        val inv = d.snap { it.allocations.size == 1 }.invoices.first { it.id == id }
        expect(InvoiceException.Reason.BELOW_PAID) { repo.saveInvoice(inv.copy(amount = 500_000)) }
        expect(InvoiceException.Reason.HAS_PAYMENTS) { repo.setInvoiceCancelled(id, true) }
        expect(InvoiceException.Reason.HAS_PAYMENTS) { repo.deleteInvoice(id) }
        val entry = d.snap { true }.txns.first { it.id == pay }
        expect(InvoiceException.Reason.BELOW_PAID) { repo.saveTxn(entry.copy(amount = 500_000), emptyList(), emptyList()) }
        assertFalse(repo.deleteParty(f.party))
        // unlink, then cancel and delete are allowed
        repo.allocate(id, pay, 0)
        repo.setInvoiceCancelled(id, true)
        assertEquals(InvoiceStatus.CANCELLED, d.snap { s -> s.invoices.first { it.id == id }.cancelled }.invoiceBalances(today).first { it.invoice.id == id }.status)
        repo.deleteInvoice(id)
    }

    @Test fun applyExistingEntryWithLimits() = runBlocking {
        val f = fixture()
        val inv1 = invoice(f, 700_000); val inv2 = invoice(f, 700_000)
        val s0 = d.snap { it.invoices.size == 2 }
        val entry = s0.txns.first { it.type == TxnType.INCOME }                   // ₹15,000 sample income
        repo.allocate(inv1, entry.id, 700_000)
        repo.allocate(inv2, entry.id, 700_000)
        expect(InvoiceException.Reason.INVALID_ALLOCATION) { repo.allocate(inv2, entry.id, 900_000) }       // > outstanding
        val big = invoice(f, 5_000_000)
        expect(InvoiceException.Reason.INVALID_ALLOCATION) { repo.allocate(big, entry.id, 200_000) }        // only ₹1,000 unapplied
        val expense = s0.txns.first { it.type == TxnType.EXPENSE }
        expect(InvoiceException.Reason.INVALID_ALLOCATION) { repo.allocate(big, expense.id, 100) }          // wrong type
        val s = d.snap { it.allocations.size == 2 }
        assertEquals(listOf(InvoiceStatus.PAID, InvoiceStatus.PAID), s.invoiceBalances(today).filter { it.invoice.id != big }.map { it.status })
    }

    @Test fun backupIncludesInvoicesAndAllocations() = runBlocking {
        val f = fixture()
        val id = invoice(f, 1_000_000)
        repo.recordPayment(id, f.bank, f.salesCat, 400_000, today, PaymentMode.CASH, "", "")
        d.snap { it.allocations.size == 1 }
        val file = File(context().cacheDir, "p3.cbk").also { it.delete() }
        d.backup.createBackup(Uri.fromFile(file), "secret-pass".toCharArray(), false).getOrThrow()
        repo.deleteCashbooks(listOf(f.cb))
        d.snap { it.invoices.isEmpty() }
        val decoded = d.backup.inspect(Uri.fromFile(file), "secret-pass".toCharArray()).getOrThrow()
        assertEquals(1, decoded.manifest.invoices)
        d.backup.restore(decoded, file.name).getOrThrow()
        assertEquals(600_000L, d.snap { it.allocations.size == 1 }.invoiceBalances(today).single().outstanding)
    }

    @Test fun alertsDigestAndBudgetKeys() = runBlocking {
        val f = fixture()
        invoice(f, 1_000_000, due = today.minusDays(5))
        invoice(f, 300_000, kind = InvoiceKind.PURCHASE, due = today.minusDays(40))
        invoice(f, 200_000, due = today.plusDays(1))
        repo.setBudget(f.cb, f.purchaseCat, 100_000)
        repo.saveTxn(com.cashbook.core.Txn(0, f.cb, TxnType.EXPENSE, today, 150_000, f.bank, categoryId = f.purchaseCat), emptyList(), emptyList())
        val s = d.snap { it.invoices.size == 3 && it.budgets.size == 1 && it.txns.size == 5 }
        val digest = Alerts.invoiceDigest(s, today)
        assertEquals(2, digest.overdueCount)
        assertEquals(1_000_000L, digest.overdueReceivable)
        assertEquals(300_000L, digest.overduePayable)
        assertEquals(1, digest.dueSoonCount)
        val settings = d.settings.settings.first()
        val pending = Alerts.pendingBudgetAlerts(s, settings, today)
        assertEquals(1, pending.size)
        assertTrue(pending.single().first.endsWith(":OVER"))
        assertTrue(Alerts.pendingBudgetAlerts(s, settings.copy(sentBudgetAlerts = setOf(pending.single().first)), today).isEmpty())
    }

    @Test fun widgetHidesAmountsUnlessAllowedAndUnlocked() = runBlocking {
        fixture()
        val s = d.snap { it.txns.size == 4 }
        val base = d.settings.settings.first().copy(onboarded = true)
        assertEquals("Balance hidden", WidgetUpdater.content(context(), s, base).balance)
        assertEquals("₹72,500.00", WidgetUpdater.content(context(), s, base.copy(widgetShowBalance = true)).balance)
        assertEquals("Balance hidden", WidgetUpdater.content(context(), s, base.copy(widgetShowBalance = true, lockEnabled = true)).balance)
        // the RemoteViews inflate with the real layout
        val v = WidgetUpdater.views(context(), WidgetUpdater.content(context(), s, base))
        assertEquals(context().packageName, v.`package`)
    }

}
