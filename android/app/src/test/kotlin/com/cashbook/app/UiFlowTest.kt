package com.cashbook.app

import android.graphics.Bitmap
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.printToString
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onLast
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextClearance
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.Ledger
import com.cashbook.core.PaymentMode
import com.cashbook.core.Txn
import com.cashbook.core.TxnType
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.time.LocalDate

/**
 * End-to-end UI checks on the JVM (Robolectric + Compose): first-run setup, adding an expense
 * and a transfer through the real forms, and screenshots of the main screens in light, dark and
 * Hindi for visual review (written to app/build/screenshots).
 */
@OptIn(ExperimentalTestApi::class)
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class UiFlowTest {
    @get:Rule val compose = createEmptyComposeRule()

    private fun exists(text: String, substring: Boolean = false) =
        compose.onAllNodesWithText(text, substring = substring, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()

    private var scenario: ActivityScenario<MainActivity>? = null
    private fun launch() { scenario = ActivityScenario.launch(MainActivity::class.java) }

    @org.junit.After fun closeActivity() { scenario?.close() }

    private fun waitFor(text: String, substring: Boolean = false, timeout: Long = 20_000) {
        try { compose.waitUntil(timeout) { exists(text, substring) } } catch (e: Throwable) {
            val dump = compose.onAllNodes(isRoot()).fetchSemanticsNodes().joinToString("\n----\n") { it.toString() }
            val tree = runCatching { compose.onAllNodes(isRoot())[0].printToString(maxDepth = 60) }.getOrDefault(dump)
            throw AssertionError("Text \"$text\" not found. UI tree:\n$tree", e)
        }
    }

    /** Bottom-navigation tab (not a same-named button elsewhere on the screen). */
    private fun tab(text: String) = compose.onNode(hasText(text) and androidx.compose.ui.test.isSelectable()).performClick()

    private fun click(text: String) = compose.onAllNodesWithText(text, useUnmergedTree = true).onFirst().performClick()

    /** Draws the activity window into a PNG under app/build/screenshots (Robolectric native graphics). */
    private fun shot(name: String) {
        compose.waitForIdle()
        scenario?.onActivity { a ->
            val v = a.window.decorView
            val bmp = Bitmap.createBitmap(v.width, v.height, Bitmap.Config.ARGB_8888)
            v.draw(android.graphics.Canvas(bmp))
            val dir = File("build/screenshots").apply { mkdirs() }
            File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }

    /** Opens the bottom-bar Add sheet and taps an option in it (the dashboard has same-named quick actions underneath). */
    private fun openFromAddSheet(option: String) {
        click("Add")
        compose.waitUntil(10_000) { compose.onAllNodesWithText(option, useUnmergedTree = true).fetchSemanticsNodes().size >= 2 }
        compose.onAllNodesWithText(option, useUnmergedTree = true).onLast().performClick()
    }

    private fun field(label: String): SemanticsNodeInteraction = compose.onNode(hasSetTextAction() and hasText(label))

    @Test fun firstRunSetupThenRecordExpenseAndTransfer() {
        launch()
        waitFor("Welcome to Cashbook")
        shot("01_setup_welcome")
        click("Next")
        waitFor("English"); shot("02_setup_language"); click("Skip")
        waitFor("System default"); click("Skip")
        waitFor("Cashbook name")
        field("Cashbook name").performTextInput("Office Cashbook")
        click("Next")
        waitFor("Cash in hand")
        val openings = compose.onAllNodes(hasSetTextAction() and hasText("Opening balance"))
        openings[0].performTextInput("10000")
        openings[1].performTextInput("50000")
        shot("03_setup_accounts")
        click("Next")
        waitFor("Set PIN"); click("Skip")
        waitFor("Start using Cashbook"); click("Start using Cashbook")

        waitFor("Total balance")
        waitFor("₹60,000.00")
        shot("04_dashboard_after_setup")

        // ---- add an expense through the form ----
        openFromAddSheet("Add Expense")
        waitFor("Expense category *")
        field("Amount *").performTextInput("2500")
        click("Expense category *")
        waitFor("Office rent"); click("Office rent")
        field("Description").performTextInput("Office rent payment")
        field("Bill / voucher number").performTextInput("RENT-APR-001")
        shot("05_expense_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("₹57,500.00")

        // ---- add a transfer ----
        openFromAddSheet("Transfer")
        waitFor("From account *")
        field("Amount *").performTextInput("5000")
        waitFor("decreases by", substring = true)
        shot("06_transfer_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Total balance")
        compose.waitUntil(20_000) { exists("₹12,500.00") } // cash: 10,000 − 2,500 + 5,000
        waitFor("₹57,500.00")                               // total unchanged by the transfer
        shot("07_dashboard_after_entries")

        val s = runBlocking { deps().snap { it.txns.size == 2 } }
        val cash = s.accounts.first { it.type == AccountType.CASH }
        val bank = s.accounts.first { it.type == AccountType.BANK }
        assertEquals(1_250_000L, Ledger.currentBalance(cash, s.txns))
        assertEquals(4_500_000L, Ledger.currentBalance(bank, s.txns))
        assertEquals("RENT-APR-001", s.txns.first { it.type == TxnType.EXPENSE }.reference)

        // ---- other tabs ----
        click("Transactions"); waitFor("Office rent payment"); shot("08_transactions")
        click("Reports"); waitFor("Daily Cashbook"); shot("09_reports")
        click("Monthly Summary"); waitFor("Account balances"); shot("10_report_monthly")
    }

    @Test fun invalidAmountIsRejected() {
        seed("en")
        launch()
        waitFor("Total balance")
        openFromAddSheet("Add Expense")
        waitFor("Amount *")
        field("Amount *").performTextInput("0")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Amount must be more than zero")
        waitFor("Select a category")
        shot("11_validation")
    }

    @Test fun lightScreens() { seed("en"); screens("light") }

    @Test @Config(qualifiers = "+night") fun darkScreens() { seed("en"); screens("dark") }

    @Test @Config(qualifiers = "hi") fun hindiScreens() { seed("hi"); screens("hindi", hindi = true) }

    @Test @Config(qualifiers = "w360dp-h640dp-xhdpi") fun smallPhone() { seed("en"); screens("small") }

    private fun screens(prefix: String, hindi: Boolean = false) {
        launch()
        waitFor(if (hindi) "कुल शेष" else "Total balance")
        shot("${prefix}_dashboard")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(if (hindi) "सबसे बड़ी व्यय श्रेणियाँ" else "Largest expense categories"))
        shot("${prefix}_dashboard_charts")
        click(if (hindi) "लेन-देन" else "Transactions"); waitFor(if (hindi) "ऑफ़िस किराया" else "Office rent", substring = true); shot("${prefix}_transactions")
        click(if (hindi) "रिपोर्ट" else "Reports"); waitFor(if (hindi) "दैनिक कैशबुक" else "Daily Cashbook"); shot("${prefix}_reports")
        click(if (hindi) "सेटिंग" else "Settings"); waitFor(if (hindi) "बैकअप और पुनर्स्थापना" else "Backup & restore"); shot("${prefix}_settings")
    }

    @Test fun recurringEntriesAndBudgets() {
        seed("en")
        val d = deps()
        runBlocking {
            val s = d.snap { true }
            val cb = s.cashbooks.single().id
            val bank = s.accounts.first { it.type == AccountType.BANK }.id
            val exp = s.categories.filter { it.kind == CategoryKind.EXPENSE }
            // a manual rule due today (amount varies, e.g. electricity) and budgets for the dashboard
            d.ledger.saveRecurring(com.cashbook.core.RecurringRule(0, cb, TxnType.EXPENSE, 180_000, bank, categoryId = exp.first { it.name == "Electricity" }.id,
                paymentMode = PaymentMode.UPI, description = "Electricity bill", startDate = LocalDate.now(), autoPost = false))
            d.ledger.setBudget(cb, exp.first { it.name == "Office rent" }.id, 300_000)
            d.ledger.setBudget(cb, exp.first { it.name == "Telephone and internet" }.id, 200_000)
            d.ledger.setBudget(cb, exp.first { it.name == "Travel and conveyance" }.id, 500_000)
            d.snap { it.recurring.size == 1 && it.budgets.size == 3 }
        }
        launch()
        waitFor("Total balance")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Waiting for confirmation"))
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Budgets this month"))
        shot("12_dashboard_due_and_budgets")
        click("Post")
        compose.waitUntil(10_000) { runBlocking { d.snap { true } }.txns.any { it.description == "Electricity bill" } }
        waitFor("Budgets this month")

        click("Settings"); waitFor("Recurring entries"); click("Recurring entries")
        waitFor("Electricity bill"); shot("13_recurring_list")
        // create a monthly salary schedule through the form
        click("New recurring entry")
        waitFor("Schedule")
        field("Amount *").performTextInput("25000")
        click("Expense category *"); waitFor("Select category")
        compose.onNode(hasSetTextAction() and hasText("Search")).performTextInput("salary")
        waitFor("Salary and wages"); click("Salary and wages")
        field("Description").performTextInput("Staff salary")
        shot("14_recurring_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Staff salary")
        val rule = runBlocking { d.snap { it.recurring.size == 2 } }.recurring.first { it.description == "Staff salary" }
        assertEquals(2_500_000L, rule.amount)
        assertEquals(com.cashbook.core.Frequency.MONTHLY, rule.frequency)
        assertEquals(LocalDate.now(), runBlocking { d.snap { s -> s.txns.any { it.recurringId == rule.id } } }.txns.first { it.recurringId == rule.id }.date)

        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }
        waitFor("Budgets"); click("Budgets")
        waitFor("Office rent"); shot("15_budgets")
    }

    @Test fun invoiceToPaymentFlow() {
        seed("en")
        val d = deps()
        runBlocking {
            d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CLIENT", createdAt = 0, updatedAt = 0))
            val s = d.snap { it.parties.isNotEmpty() }
            val cb = s.cashbooks.single().id
            val p = s.parties.single().id
            // an older overdue bill so the dashboard and ageing have something to show
            d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.PURCHASE, "BILL/26-27/001", p,
                LocalDate.now().minusDays(50), LocalDate.now().minusDays(35), 450_000, "Printer toner"))
        }
        launch()
        waitFor("Total balance")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Receivables & payables"))
        shot("16_dashboard_receivables")
        click("Settings"); waitFor("Invoices & bills"); click("Invoices & bills")
        waitFor("New invoice"); click("New invoice")
        waitFor("Customer / client *")
        click("Customer / client *"); waitFor("ABC Enterprises"); click("ABC Enterprises")
        field("Invoice amount").performTextInput("50000")
        field("Description").performTextInput("Audit fees for FY 2025-26")
        click("30 days")
        shot("17_invoice_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Record receipt")
        shot("18_invoice_detail_open")
        click("Record receipt")
        waitFor("Payment mode")
        field("Amount *").performTextClearance()
        field("Amount *").performTextInput("20000")
        shot("19a_record_receipt")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Partly paid")
        shot("19_invoice_detail_partial")
        val s = runBlocking { d.snap { it.allocations.size == 1 } }
        val b = s.invoiceBalances().first { it.invoice.kind == com.cashbook.core.InvoiceKind.SALE }
        assertEquals(3_000_000L, b.outstanding)
        assertEquals(LocalDate.now().plusDays(30), b.invoice.dueDate)
        assertEquals(TxnType.INCOME, s.txns.first { it.id == s.allocations.single().txnId }.type)
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }
        waitFor("To receive"); shot("20_invoices_list")
    }

    /** Delete an entry from its detail screen through the confirmation dialog; it moves to the recycle bin. */
    @Test fun deleteEntryViaDialog() {
        seed("en")
        launch()
        waitFor("Total balance")
        tab("Transactions"); waitFor("Accounting services"); click("Accounting services")
        waitFor("Entry details")
        compose.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(hasText("Delete", substring = true))
        compose.onAllNodesWithText("Delete", substring = true, useUnmergedTree = true).onFirst().performClick()
        waitFor("Delete this entry?")
        click("Move to recycle bin")
        compose.waitUntil(10_000) { runBlocking { deps().snap { true } }.deleted.any { it.description == "Accounting services" } }
    }

    @Test fun outstandingReport() {
        seed("en")
        runBlocking {
            val d = deps()
            d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CLIENT", createdAt = 0, updatedAt = 0))
            val s = d.snap { it.parties.isNotEmpty() }
            val cb = s.cashbooks.single().id; val p = s.parties.single().id
            d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "INV/26-27/001", p, LocalDate.now().minusDays(70), LocalDate.now().minusDays(40), 5_000_000))
            d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "INV/26-27/002", p, LocalDate.now().minusDays(5), LocalDate.now().plusDays(10), 1_200_000))
            d.snap { it.invoices.size == 2 }
        }
        launch()
        waitFor("Total balance")
        tab("Reports"); waitFor("Daily Cashbook")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Outstanding & Ageing"))
        click("Outstanding & Ageing")
        waitFor("INV/26-27/001")
        shot("21_report_outstanding")
    }

    /** Sample cashbook plus a few entries in the current month so charts have data. */
    private fun seed(lang: String) = runBlocking {
        val d = deps()
        val names = if (lang == "hi") SAMPLE_NAMES.copy(cashbook = "ऑफ़िस कैशबुक", cash = "ऑफ़िस नकद", bank = "SBI बैंक",
            t1 = "व्यावसायिक शुल्क प्राप्त", t2 = "ऑफ़िस स्टेशनरी", t3 = "इंटरनेट बिल", t4 = "SBI बैंक से ऑफ़िस नकद") else SAMPLE_NAMES
        val cb = d.ledger.addSampleData(lang, names)
        val s = d.snap { it.txns.size == 4 }
        val cash = s.accounts.first { it.type == AccountType.CASH }.id
        val bank = s.accounts.first { it.type == AccountType.BANK }.id
        val exp = s.categories.filter { it.kind == CategoryKind.EXPENSE }
        val inc = s.categories.filter { it.kind == CategoryKind.INCOME }
        val today = LocalDate.now()
        val rent = if (lang == "hi") "ऑफ़िस किराया" else "Office rent"
        listOf(
            Txn(0, cb, TxnType.INCOME, today.minusMonths(2), 4_000_000, bank, categoryId = inc[1].id, paymentMode = PaymentMode.UPI, description = "ABC Enterprises"),
            Txn(0, cb, TxnType.EXPENSE, today.minusMonths(1), 1_200_000, bank, categoryId = exp[2].id, paymentMode = PaymentMode.BANK_TRANSFER),
            Txn(0, cb, TxnType.INCOME, today, 1_500_000, bank, categoryId = inc[1].id, paymentMode = PaymentMode.UPI, description = "Accounting services"),
            Txn(0, cb, TxnType.EXPENSE, today, 250_000, cash, categoryId = exp[1].id, paymentMode = PaymentMode.CASH, description = rent, reference = "RENT-001"),
            Txn(0, cb, TxnType.EXPENSE, today, 80_000, cash, categoryId = exp[12].id, paymentMode = PaymentMode.CASH),
        ).forEach { d.ledger.saveTxn(it, emptyList(), emptyList()) }
        d.settings.update { it.copy(onboarded = true, language = lang, defaultCashbookId = cb, currentCashbookId = cb) }
        d.snap { it.txns.size == 9 }
    }
}
