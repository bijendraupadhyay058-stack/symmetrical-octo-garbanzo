package com.cashbook.app

import android.graphics.Bitmap
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.printToString
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.onNodeWithContentDescription
import org.junit.Assert.assertTrue
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.assertCountEquals
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
import kotlinx.coroutines.flow.first
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
        waitFor("Budgets")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Budgets"))
        click("Budgets")
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
        click("Itemised with GST")                                            // simple invoice: one total, no line items
        waitFor("Invoice amount")
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

    @Test fun itemisedGstInvoice() {
        seed("en")
        val d = deps()
        runBlocking {
            d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "Bengaluru Tech LLP", type = "CLIENT", gstin = "29AAGCB7383J1Z4",
                createdAt = 0, updatedAt = 0, stateCode = "29"))
            d.snap { it.parties.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Business profile"); click("Business profile")
        waitFor("Business / trade name")
        field("Business / trade name").performTextInput("Sharma & Associates")
        field("GSTIN (optional)").performTextInput("27AAPFU0939F1ZV")       // fills State / UT = 27 automatically
        waitFor("27 – Maharashtra")
        shot("24_business_profile")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Invoices & bills")                                           // back on Settings after saving
        // (the saved seller state 27 is verified below: Karnataka place of supply must give IGST)
        compose.waitUntil(15_000) { !exists("Saved") }                         // let the "Saved" message clear the bottom of the screen
        click("Invoices & bills")
        waitFor("New invoice"); click("New invoice")
        waitFor("Customer / client *")
        click("Customer / client *"); waitFor("Bengaluru Tech LLP"); click("Bengaluru Tech LLP")
        waitFor("29 – Karnataka")                                             // place of supply from the party
        field("Item / service").performTextInput("Tax audit")
        field("HSN / SAC").performTextInput("998221")
        field("Rate").performTextInput("40000")
        waitFor("Inter-state supply (IGST)", timeout = 10_000)
        shot("25_invoice_items")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Record receipt")
        val inv = runBlocking { d.snap { it.invoiceItems.isNotEmpty() } }.invoices.single { it.kind == com.cashbook.core.InvoiceKind.SALE }
        assertEquals(4_720_000L, inv.amount)                                   // 40,000 + 18 % IGST
        assertEquals("29", inv.placeOfSupply)
        compose.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(hasText("Save PDF", substring = true))
        shot("26_invoice_detail_items")
    }

    @Test fun creditNoteAndRefundFlow() {
        seed("en")
        val d = deps()
        var invoiceId = 0L
        runBlocking {
            d.settings.updateBusinessProfile(com.cashbook.core.backup.BusinessProfileDto(name = "Sharma & Associates", gstin = "27AAPFU0939F1ZV", stateCode = "27"))
            val p = d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27"))
            val s = d.snap { it.parties.isNotEmpty() }
            val cb = s.cashbooks.single().id
            invoiceId = d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "INV/26-27/001", p, LocalDate.now(),
                LocalDate.now().plusDays(15), 1, placeOfSupply = "27"), listOf(
                com.cashbook.core.InvoiceItem(description = "Laser printer", quantityMilli = 1000, rate = 1_500_000, gstBp = 1800),
                com.cashbook.core.InvoiceItem(description = "Toner cartridge", quantityMilli = 2000, rate = 250_000, gstBp = 1800)), "27")   // 23,600
            d.ledger.recordPayment(invoiceId, s.accounts.first { it.type == AccountType.BANK }.id, s.categories.first { it.kind == CategoryKind.INCOME }.id,
                2_360_000, LocalDate.now(), PaymentMode.UPI, "", "Paid")
            d.snap { it.allocations.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Invoices & bills"); click("Invoices & bills")
        waitFor("Unpaid"); click("Paid"); waitFor("ABC Enterprises"); click("ABC Enterprises")
        waitFor("Credit / debit notes", timeout = 10_000)
        compose.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(hasText("Credit note"))
        click("Credit note")
        waitFor("New credit note")
        // starts from the invoice's items: drop the printer line, keep one toner returned
        compose.onAllNodes(androidx.compose.ui.test.hasContentDescription("Remove item"))[0].performClick()
        field("Qty").performTextClearance(); field("Qty").performTextInput("1")
        field("Reason").performTextInput("One toner returned damaged")
        shot("28_credit_note_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Against INV/26-27/001", substring = true)
        compose.onAllNodesWithText("Against INV/26-27/001", substring = true, useUnmergedTree = true).onFirst().performClick()
        waitFor("Refund due", substring = true)
        shot("29_invoice_refund_due")
        val b = runBlocking { d.snap { it.invoices.size == 2 } }.invoiceBalances().single()
        assertEquals(295_000L, b.refundDue)                                   // 2,500 + 18 %
        compose.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(hasText("Record refund to customer"))
        click("Record refund to customer")
        waitFor("Payment mode")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        compose.waitUntil(10_000) { runBlocking { d.snap { true } }.invoiceBalances().single().status == com.cashbook.core.InvoiceStatus.PAID }
        val s2 = runBlocking { d.snap { true } }
        assertEquals(TxnType.EXPENSE, s2.txns.first { t -> s2.allocations.any { it.txnId == t.id && t.type == TxnType.EXPENSE } }.type)
        assertEquals(invoiceId, s2.invoices.first { it.docType == com.cashbook.core.DocType.CREDIT_NOTE }.refInvoiceId)
    }

    @Test fun productsAndStockFlow() {
        seed("en")
        val d = deps()
        runBlocking {
            d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27"))
            d.ledger.saveCatalogItem(com.cashbook.core.CatalogItem(0, "A4 paper ream", com.cashbook.core.ItemKind.GOODS, "4802", "Ream", 32_000, 26_000, 1200,
                openingStockMilli = 40_000, openingDate = LocalDate.now().minusDays(10), reorderLevelMilli = 10_000))
            d.ledger.saveCatalogItem(com.cashbook.core.CatalogItem(0, "GST return filing", com.cashbook.core.ItemKind.SERVICE, "998231", "Month", 250_000, 0, 1800))
            d.snap { it.catalog.size == 2 && it.parties.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Products & services"); click("Products & services")
        waitFor("New item"); click("New item")
        waitFor("Item name")
        field("Item name").performTextInput("Toner cartridge")
        field("HSN / SAC").performTextInput("8443")
        field("Unit").performTextInput("Nos")
        field("Sale rate").performTextInput("2500")
        field("Purchase rate").performTextInput("1800")
        field("Opening stock").performTextInput("6")
        field("Reorder level").performTextInput("5")
        shot("30_item_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Toner cartridge")
        shot("31_products_list")
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }

        waitFor("Invoices & bills"); click("Invoices & bills")
        waitFor("New invoice"); click("New invoice")
        waitFor("Customer / client *")
        click("Customer / client *"); waitFor("ABC Enterprises"); click("ABC Enterprises")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Add a saved item", substring = true))
        compose.onAllNodes(androidx.compose.ui.test.hasContentDescription("Pick a saved item"))[0].performClick()   // fill line 1
        waitFor("Toner cartridge"); click("Toner cartridge")
        waitFor("In stock: 6 Nos")
        field("Qty").performTextClearance(); field("Qty").performTextInput("2")
        shot("32_invoice_pick_item")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Record receipt")
        val s = runBlocking { d.snap { it.invoiceItems.isNotEmpty() } }
        val toner = s.catalog.first { it.name == "Toner cartridge" }
        assertEquals(toner.id, s.invoiceItems.values.single().single().itemId)
        assertEquals(590_000L, s.invoices.single().amount)                                     // 2 × 2,500 + 18 %
        assertEquals(4_000L, s.onHand(toner))                                                    // 6 − 2: now below the reorder level of 5
        repeat(2) { scenario?.onActivity { a -> a.onBackPressedDispatcher.onBackPressed() }; compose.waitForIdle() }   // invoice → list → Settings
        tab("Dashboard"); waitFor("Total balance")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Low stock"))
        waitFor("4 left (reorder at 5 Nos)", substring = true)
        shot("33_dashboard_low_stock")
    }

    @Test fun quotationToInvoiceWithUpiQr() {
        seed("en")
        val d = deps()
        runBlocking {
            d.settings.updateBusinessProfile(com.cashbook.core.backup.BusinessProfileDto(name = "Sharma & Associates", gstin = "27AAPFU0939F1ZV", stateCode = "27",
                upiId = "sharma.assoc@oksbi"))
            d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27"))
            d.ledger.saveCatalogItem(com.cashbook.core.CatalogItem(0, "Toner cartridge", com.cashbook.core.ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 10_000, openingDate = LocalDate.now().minusDays(10), reorderLevelMilli = 2_000))
            d.snap { it.catalog.isNotEmpty() && it.parties.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Invoices & bills"); click("Invoices & bills")
        waitFor("Receivables"); tab("Quotes & orders")
        waitFor("No quotations yet.")
        click("New quotation")
        waitFor("Customer / client *")
        click("Customer / client *"); waitFor("ABC Enterprises"); click("ABC Enterprises")
        waitFor("Valid until")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Add a saved item", substring = true))
        compose.onAllNodes(androidx.compose.ui.test.hasContentDescription("Pick a saved item"))[0].performClick()
        waitFor("Toner cartridge"); click("Toner cartridge")
        waitFor("In stock: 10 Nos")
        field("Qty").performTextClearance(); field("Qty").performTextInput("3")
        shot("37_quotation_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Convert to invoice")
        var s = runBlocking { d.snap { it.quotations.isNotEmpty() } }
        assertEquals(885_000L, s.quotations.single().amount)                                    // 3 × 2,500 + 18 %
        assertTrue(s.invoices.isEmpty())
        assertEquals(10_000L, s.onHand(s.catalog.single()))                                     // a quotation doesn't move stock
        shot("38_quotation_detail")
        compose.onNodeWithText("Convert to invoice", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Record receipt")
        waitFor("From quotation", substring = true)
        s = runBlocking { d.snap { it.invoices.isNotEmpty() } }
        assertEquals(s.invoices.single().id, s.quotations.single().convertedInvoiceId)
        assertEquals(7_000L, s.onHand(s.catalog.single()))
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Collect by UPI"))
        waitFor("sharma.assoc@oksbi")
        compose.onNodeWithContentDescription("UPI QR code to pay", substring = true).assertExists()
        shot("39_invoice_upi_qr")
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }
        waitFor("Converted to invoice", substring = true)
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }
        waitFor("Open quotations"); waitFor("Converted")
        shot("40_quotations_list")
    }

    @Test fun purchaseOrderStatementAndReminder() {
        seed("en")
        val d = deps()
        runBlocking {
            d.settings.updateBusinessProfile(com.cashbook.core.backup.BusinessProfileDto(name = "Sharma & Associates", stateCode = "27", upiId = "sharma.assoc@oksbi"))
            val customer = d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", mobile = "98765 43210",
                createdAt = 0, updatedAt = 0, stateCode = "27"))
            d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "Office Mart", type = "SUPPLIER", createdAt = 0, updatedAt = 0, stateCode = "27"))
            d.ledger.saveCatalogItem(com.cashbook.core.CatalogItem(0, "Toner cartridge", com.cashbook.core.ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 2_000, openingDate = LocalDate.now().minusDays(30), reorderLevelMilli = 3_000))
            val s = d.snap { it.parties.size == 2 && it.catalog.isNotEmpty() }
            val cb = s.cashbooks.single().id
            val inv = d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "INV/26-27/007", customer,
                LocalDate.now().minusDays(40), LocalDate.now().minusDays(25), 1_180_000))
            d.ledger.recordPayment(inv, s.accounts.first().id, s.categories.first { it.kind == com.cashbook.core.CategoryKind.INCOME }.id, 500_000,
                LocalDate.now().minusDays(20), com.cashbook.core.PaymentMode.UPI, "UTR123", "Part payment")
            d.snap { it.allocations.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Invoices & bills"); click("Invoices & bills")
        // payment reminder on the overdue invoice (the customer has a mobile number, so it goes to WhatsApp)
        waitFor("INV/26-27/007", substring = true); click("ABC Enterprises")
        waitFor("Record receipt")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("WhatsApp payment reminder", substring = true))
        waitFor("Send PDF on WhatsApp", substring = true)
        shot("45_invoice_reminder")
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }

        // purchase order → bill
        waitFor("Receivables"); tab("Quotes & orders")
        waitFor("Purchase orders"); click("Purchase orders")
        waitFor("No purchase orders yet."); click("New purchase order")
        waitFor("Supplier *"); click("Supplier *"); waitFor("Office Mart"); click("Office Mart")
        waitFor("Expected by")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Add a saved item", substring = true))
        compose.onAllNodes(androidx.compose.ui.test.hasContentDescription("Pick a saved item"))[0].performClick()
        waitFor("Toner cartridge"); click("Toner cartridge")
        field("Qty").performTextClearance(); field("Qty").performTextInput("10")
        shot("42_purchase_order_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Convert to bill")
        var s = runBlocking { d.snap { it.quotations.isNotEmpty() } }
        assertTrue(s.quotations.single().number.startsWith("PO/"))
        assertEquals(2_000L, s.onHand(s.catalog.single()))
        shot("43_purchase_order_detail")
        compose.onNodeWithText("Convert to bill", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Record payment"); waitFor("From purchase order", substring = true)
        s = runBlocking { d.snap { it.invoices.size == 2 } }
        assertEquals(12_000L, s.onHand(s.catalog.single()))
        repeat(2) { scenario?.onActivity { a -> a.onBackPressedDispatcher.onBackPressed() }; compose.waitForIdle() }
        waitFor("Open purchase orders"); waitFor("Billed")
        shot("44_purchase_orders_list")
        repeat(2) { scenario?.onActivity { a -> a.onBackPressedDispatcher.onBackPressed() }; compose.waitForIdle() }   // list → Settings → Dashboard

        // statement of account for the customer
        tab("Reports")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Statement of account"))
        click("Statement of account")
        waitFor("All parties"); waitFor("Closing balance")
        // the preview is recomposed while the report builds, which can swallow the first tap on the dropdown: retry it
        val menuItem = hasText("ABC Enterprises") and androidx.compose.ui.test.hasClickAction()
        for (attempt in 1..3) {
            compose.onNode(hasText("All parties") and androidx.compose.ui.test.hasClickAction()).performClick()
            compose.waitForIdle()
            if (runCatching { compose.waitUntil(2_000) { compose.onAllNodes(menuItem).fetchSemanticsNodes().isNotEmpty() } }.isSuccess) break
        }
        compose.onAllNodes(hasText("ABC Enterprises") and androidx.compose.ui.test.hasClickAction()).onFirst().performClick()
        waitFor("Received – UPI (INV/26-27/007) · UTR123", substring = true)
        waitFor("Closing balance")
        compose.onAllNodesWithText("Office Mart", useUnmergedTree = true).assertCountEquals(0)          // only the chosen party
        shot("46_statement_of_account")
    }

    @Test fun challansAndCollections() {
        seed("en")
        val d = deps()
        runBlocking {
            d.settings.updateBusinessProfile(com.cashbook.core.backup.BusinessProfileDto(name = "Sharma & Associates", stateCode = "27", upiId = "sharma.assoc@oksbi"))
            val customer = d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", mobile = "98765 43210",
                createdAt = 0, updatedAt = 0, stateCode = "27"))
            val toner = d.ledger.saveCatalogItem(com.cashbook.core.CatalogItem(0, "Toner cartridge", com.cashbook.core.ItemKind.GOODS, "8443", "Nos", 250_000, 180_000, 1800,
                openingStockMilli = 20_000, openingDate = LocalDate.now().minusDays(60), reorderLevelMilli = 3_000))
            val cb = d.snap { it.parties.isNotEmpty() && it.catalog.isNotEmpty() }.cashbooks.single().id
            d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "INV/26-27/001", customer,
                LocalDate.now().minusDays(50), LocalDate.now().minusDays(35), 1_180_000))
            d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "DC/26-27/001", customer,
                LocalDate.now().minusDays(5), LocalDate.now().minusDays(5), 1, placeOfSupply = "27", docType = com.cashbook.core.DocType.CHALLAN),
                listOf(com.cashbook.core.InvoiceItem(description = "Toner cartridge", hsn = "8443", quantityMilli = 3_000, unit = "Nos", rate = 250_000, gstBp = 1800, itemId = toner)), "27")
            d.snap { it.invoices.isNotEmpty() && it.challans.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Invoices & bills"); click("Invoices & bills")
        // overdue collections
        waitFor("Remind overdue customers (1)", substring = true); click(" Remind overdue customers (1)")
        waitFor("Overdue collections"); waitFor("ABC Enterprises")
        waitFor("Overdue invoices: 1 · oldest 35 days")
        waitFor("WhatsApp payment reminder", substring = true)
        shot("48_overdue_collections")
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }

        // a second delivery challan through the form, then bill both in one invoice
        waitFor("Receivables"); tab("Quotes & orders")
        waitFor("Delivery challans"); click("Delivery challans")
        waitFor("DC/26-27/001", substring = true)
        click("New delivery challan")
        waitFor("Customer / client *"); click("Customer / client *"); waitFor("ABC Enterprises"); click("ABC Enterprises")
        waitFor("Challan date")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Add a saved item", substring = true))
        compose.onAllNodes(androidx.compose.ui.test.hasContentDescription("Pick a saved item"))[0].performClick()
        waitFor("Toner cartridge"); click("Toner cartridge")
        waitFor("In stock: 17 Nos")
        field("Qty").performTextClearance(); field("Qty").performTextInput("2")
        shot("49_challan_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Bill in one invoice")
        var s = runBlocking { d.snap { it.challans.size == 2 } }
        assertEquals(15_000L, s.onHand(s.catalog.single()))                                      // stock left with the challans
        assertTrue(s.challans.all { it.number.startsWith("DC/") })
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Create invoice", substring = true))
        waitFor("Create invoice · 2 challans · ₹14,750.00")
        shot("50_challan_detail")
        compose.onNodeWithText("Create invoice · 2 challans · ₹14,750.00", useUnmergedTree = true).performClick()
        waitFor("Record receipt"); waitFor("From delivery challan DC/26-27/001")
        s = runBlocking { d.snap { it.invoices.size == 2 } }
        val inv = s.invoices.first { it.number != "INV/26-27/001" }
        assertEquals(1_475_000L, inv.amount)
        assertTrue(s.challans.all { it.convertedInvoiceId == inv.id })
        assertEquals(15_000L, s.onHand(s.catalog.single()))
        shot("51_invoice_from_challans")
        repeat(2) { scenario?.onActivity { a -> a.onBackPressedDispatcher.onBackPressed() }; compose.waitForIdle() }
        waitFor("Not yet billed"); waitFor("Billed")
        shot("52_challans_list")
    }

    @Test fun recurringInvoiceAndTransport() {
        seed("en")
        val d = deps()
        runBlocking {
            d.settings.updateBusinessProfile(com.cashbook.core.backup.BusinessProfileDto(name = "Sharma & Associates", stateCode = "27"))
            val customer = d.ledger.saveParty(com.cashbook.app.data.db.PartyEntity(name = "ABC Enterprises", type = "CUSTOMER", createdAt = 0, updatedAt = 0, stateCode = "27"))
            val cb = d.snap { it.parties.isNotEmpty() }.cashbooks.single().id
            d.ledger.saveInvoice(com.cashbook.core.InvoiceInfo(0, cb, com.cashbook.core.InvoiceKind.SALE, "INV/26-27/050", customer, LocalDate.now(), LocalDate.now().plusDays(15),
                590_000, "Toner supply", transport = com.cashbook.core.Transport("MH12AB1234", "VRL Logistics", "LR-5521", "381001234567")))
            d.snap { it.invoices.isNotEmpty() }
        }
        launch()
        waitFor("Total balance")
        tab("Settings"); waitFor("Invoices & bills"); click("Invoices & bills")
        // transport details on an invoice
        waitFor("INV/26-27/050", substring = true); click("ABC Enterprises")
        waitFor("Vehicle no. MH12AB1234 · VRL Logistics · LR no. LR-5521 · E-way bill no. 3810 0123 4567")
        shot("56_invoice_transport")
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }

        // a monthly retainer created through the form; today's invoice is made straight away
        waitFor("Receivables")
        compose.onNodeWithContentDescription("Recurring invoices").performClick()
        waitFor("No recurring invoices yet."); click("New recurring invoice")
        waitFor("Customer / client *"); click("Customer / client *"); waitFor("ABC Enterprises"); click("ABC Enterprises")
        waitFor("First invoice on")
        field("Item / service").performTextInput("Accounting retainer")
        field("Rate").performTextInput("10000")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Description"))
        field("Description").performTextInput("Retainer for {month}")
        shot("54_recurring_form")
        compose.onNodeWithText("Save", useUnmergedTree = true).performScrollTo().performClick()
        waitFor("Invoices created: 1")
        val s = runBlocking { d.snap { it.invoices.size == 2 && it.schedules.isNotEmpty() } }
        val made = s.invoices.single { it.scheduleId != null }
        assertEquals(1_180_000L, made.amount)
        assertEquals("Retainer for " + LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("MMMM yyyy", java.util.Locale.getDefault())), made.description)
        assertEquals(LocalDate.now().plusMonths(1), s.schedules.single().nextDate)
        waitFor("Monthly · Next", substring = true)
        shot("55_recurring_list")
    }

    @Test fun cashCountAndReconciliation() {
        seed("en")
        val d = deps()
        launch()
        waitFor("Total balance")
        tab("Settings")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Cash count"))
        click("Cash count")
        waitFor("No. of ₹500")
        field("No. of ₹500").performTextInput("20")                         // ₹10,000 counted against ₹10,200 in the books
        waitFor("Balance in the books"); waitFor("Shortage")
        waitFor("Record the difference as an entry")
        shot("57_cash_count")
        compose.onNodeWithText("Save cash count", useUnmergedTree = true).performScrollTo().performClick()
        var s = runBlocking { d.snap { it.cashCounts.isNotEmpty() } }
        val cc = s.cashCounts.single()
        assertEquals(-20_000L, cc.difference)
        assertEquals(20_000L, s.txns.single { it.id == cc.adjustmentTxnId }.amount)
        scenario?.onActivity { it.onBackPressedDispatcher.onBackPressed() }

        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Bank reconciliation"))
        click("Bank reconciliation")
        waitFor("Statement balance")
        val bank = s.accounts.first { it.type == com.cashbook.core.AccountType.BANK }
        val bankBalance = com.cashbook.core.Ledger.balanceAsOf(bank, s.txns, LocalDate.now())
        field("Statement balance").performTextInput(com.cashbook.core.Money.toPlain(bankBalance))
        click("Tick all")
        waitFor("Matches ✓")
        shot("58_bank_reconciliation")
        // the "Cash count saved" snackbar sits over the bottom of the screen until it times out
        compose.waitUntil(15_000) { compose.onAllNodesWithText("Cash count saved").fetchSemanticsNodes().isEmpty() }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Finish", substring = true))
        compose.onNodeWithText("Finish", substring = true, useUnmergedTree = true).performClick()
        s = runBlocking { d.snap { it.reconciliations.isNotEmpty() } }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Everything up to this date is cleared."))
        assertEquals(bankBalance, s.reconciliations.single().statementBalance)
        shot("59_reconciled")
    }

    @Test fun bankStatementImport() {
        seed("en")
        val d = deps()
        launch()
        waitFor("Total balance")
        val s = runBlocking { d.snap { it.txns.isNotEmpty() } }
        val bank = s.accounts.first { it.type == com.cashbook.core.AccountType.BANK }
        val last = s.txns.maxOf { it.date }
        val (csv, closing) = bankCsv(s, bank, listOf(Triple(last, "SMS CHARGES", -1_770L), Triple(last, "INTEREST CREDIT", 12_500L)))
        tab("Settings")
        compose.onNode(androidx.compose.ui.test.SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange))
            .performScrollToNode(hasText("Bank reconciliation"))
        click("Bank reconciliation")
        waitFor("Import bank statement (CSV)")
        // what the file picker hands over
        scenario?.onActivity { a -> androidx.lifecycle.ViewModelProvider(a)[com.cashbook.app.ui.AppViewModel::class.java].loadStatement(csv) }
        waitFor("not in Cashbook", substring = true)
        waitFor("SMS CHARGES")
        shot("60_statement_import")
        fun added() = runBlocking { d.snap { true } }.txns.count { it.description == "INTEREST CREDIT" || it.description == "SMS CHARGES" }
        repeat(2) { n ->
            // the list re-lays out after each add (the line moves to "matched"), so retry a tap that lands mid-update
            for (attempt in 1..3) {
                compose.waitForIdle()
                // only enabled buttons: one already tapped stays disabled (and keeps its place) until the snapshot catches up
                val addButton = hasText("Add") and androidx.compose.ui.test.hasClickAction() and androidx.compose.ui.test.isEnabled()
                // a lazy list only composes what's on screen: scroll the enabled button into view first
                if (runCatching { compose.onNode(hasScrollToIndexAction()).performScrollToNode(addButton) }.isFailure) { compose.waitForIdle(); continue }
                compose.onAllNodes(addButton).onFirst().performClick()
                if (runCatching { compose.waitUntil(10_000) { added() >= n + 1 } }.isSuccess) break
            }
        }
        assertEquals(2, added())
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Import bank statement (CSV)"))
        waitFor("Matches ✓")
        shot("61_statement_matched")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("Finish", substring = true))
        compose.onNodeWithText("Finish", substring = true, useUnmergedTree = true).performClick()
        waitFor("Everything up to this date is cleared.")
        compose.onAllNodesWithText("not in Cashbook", substring = true).assertCountEquals(0)       // import cleared after finishing
        val after = runBlocking { d.snap { it.reconciliations.isNotEmpty() } }
        assertEquals(2, after.txns.count { it.description == "INTEREST CREDIT" || it.description == "SMS CHARGES" })   // no duplicates
        assertEquals(closing, after.reconciliations.single().statementBalance)
        assertEquals(last, after.reconciliations.single().statementDate)
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
