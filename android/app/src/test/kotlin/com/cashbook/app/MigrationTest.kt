package com.cashbook.app

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.cashbook.app.data.db.AppDatabase
import com.cashbook.app.data.db.Migrations
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Upgrading from 1.0 (schema v1) keeps every row and produces exactly the schema Room expects. */
@RunWith(AndroidJUnit4::class)
class MigrationTest {
    @get:Rule val helper = MigrationTestHelper(InstrumentationRegistry.getInstrumentation(), AppDatabase::class.java)

    @Test fun migrate1To2KeepsData() {
        // Schemas are packaged into debug assets only; the release unit-test variant skips this test.
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/1.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test", 1).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Office', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO accounts (id, cashbook_id, name, type, opening_balance, opening_date, bank_name, last4, description, archived, sort_order, created_at, updated_at) VALUES (1, 1, 'Cash', 'CASH', 1000000, 20544, '', '', '', 0, 0, 1, 1)")
            execSQL("INSERT INTO categories (id, kind, name, parent_id, icon, archived, created_at, updated_at) VALUES (1, 'EXPENSE', 'Rent', NULL, 'home', 0, 1, 1)")
            execSQL("INSERT INTO transactions (id, cashbook_id, type, date, amount, account_id, to_account_id, category_id, party_id, payment_mode, description, reference, notes, tags, created_at, updated_at, deleted_at) VALUES (1, 1, 'EXPENSE', 20550, 250000, 1, NULL, 1, NULL, 'CASH', 'Office rent', 'R-1', '', '', 1, 1, NULL)")
            close()
        }
        // validateDroppedTables = true and Room's schema check: fails if the migration doesn't match 2.json exactly
        val db = helper.runMigrationsAndValidate("migration-test", 2, true, *Migrations.ALL)
        db.query("SELECT description, amount, recurring_id FROM transactions WHERE id = 1").use { c ->
            assertTrue(c.moveToFirst())
            assertEquals("Office rent", c.getString(0))
            assertEquals(250000L, c.getLong(1))
            assertTrue(c.isNull(2))
        }
        db.execSQL("INSERT INTO budgets (cashbook_id, category_id, monthly_amount, created_at, updated_at) VALUES (1, 1, 500000, 1, 1)")
        db.execSQL("INSERT INTO recurring (cashbook_id, type, amount, account_id, category_id, payment_mode, description, reference, notes, tags, frequency, interval, start_date, next_index, auto_post, active, created_at, updated_at) VALUES (1, 'EXPENSE', 250000, 1, 1, 'CASH', 'Rent', '', '', '', 'MONTHLY', 1, 20550, 1, 1, 1, 1, 1)")
        db.query("SELECT COUNT(*) FROM recurring").use { c -> c.moveToFirst(); assertEquals(1, c.getInt(0)) }
        db.close()
    }

    @Test fun migrate1To3KeepsDataAndAddsInvoices() {
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/1.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test-3", 1).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Office', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at) VALUES (1, 'ABC', 'CLIENT', '', '', '', '', '', 0, 1, 1)")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-3", 3, true, *Migrations.ALL)
        db.execSQL("INSERT INTO invoices (cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at) VALUES (1, 'SALE', 'INV/26-27/001', 1, 20544, 20560, 100000, '', '', 0, 1, 1)")
        db.query("SELECT name FROM parties WHERE id = 1").use { c -> c.moveToFirst(); assertEquals("ABC", c.getString(0)) }
        db.query("SELECT COUNT(*) FROM invoices").use { c -> c.moveToFirst(); assertEquals(1, c.getInt(0)) }
        db.close()
    }

    @Test fun migrate3To4AddsItemsAndFillsPartyState() {
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/3.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test-4", 3).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Office', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at) VALUES (1, 'ABC', 'CLIENT', '', '', '', '29AAGCB7383J1Z4', '', 0, 1, 1)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at) VALUES (2, 'No GST', 'CLIENT', '', '', '', '', '', 0, 1, 1)")
            execSQL("INSERT INTO invoices (id, cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at) VALUES (1, 1, 'SALE', 'INV/1', 1, 20544, 20560, 100000, '', '', 0, 1, 1)")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-4", 4, true, *Migrations.ALL)
        db.query("SELECT state_code FROM parties ORDER BY id").use { c -> c.moveToFirst(); assertEquals("29", c.getString(0)); c.moveToNext(); assertEquals("", c.getString(0)) }
        db.query("SELECT amount, place_of_supply, round_off FROM invoices WHERE id = 1").use { c ->
            c.moveToFirst(); assertEquals(100000L, c.getLong(0)); assertEquals("", c.getString(1)); assertEquals(1, c.getInt(2))
        }
        db.close()
    }

    @Test fun migrate4To5AddsDocumentTypes() {
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/4.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test-5", 4).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Office', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at, state_code) VALUES (1, 'ABC', 'CLIENT', '', '', '', '', '', 0, 1, 1, '')")
            execSQL("INSERT INTO invoices (id, cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off) VALUES (1, 1, 'SALE', 'INV/1', 1, 20544, 20560, 100000, '', '', 0, 1, 1, '27', 1)")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-5", 5, true, *Migrations.ALL)
        db.query("SELECT doc_type, ref_invoice_id FROM invoices WHERE id = 1").use { c -> c.moveToFirst(); assertEquals("INVOICE", c.getString(0)); assertTrue(c.isNull(1)) }
        // a credit note may reuse an invoice's number in its own series
        db.execSQL("INSERT INTO invoices (cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off, doc_type, ref_invoice_id) VALUES (1, 'SALE', 'INV/1', 1, 20550, 20550, 10000, '', '', 0, 1, 1, '27', 1, 'CREDIT_NOTE', 1)")
        db.close()
    }

    @Test fun migrate5To6AddsCatalogue() {
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/5.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test-6", 5).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Shop', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at, state_code) VALUES (1, 'ABC', 'CLIENT', '', '', '', '', '', 0, 1, 1, '')")
            execSQL("INSERT INTO invoices (id, cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off, doc_type) VALUES (1, 1, 'SALE', 'INV/1', 1, 20544, 20560, 118000, '', '', 0, 1, 1, '27', 1, 'INVOICE')")
            execSQL("INSERT INTO invoice_items (id, invoice_id, position, description, hsn, quantity_milli, unit, rate, discount_bp, gst_bp) VALUES (1, 1, 0, 'Toner', '8443', 1000, 'Nos', 100000, 0, 1800)")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-6", 6, true, *Migrations.ALL)
        db.query("SELECT description, item_id FROM invoice_items WHERE id = 1").use { c -> c.moveToFirst(); assertEquals("Toner", c.getString(0)); assertTrue(c.isNull(1)) }
        db.execSQL("INSERT INTO catalog_items (name, kind, hsn, unit, sale_rate, purchase_rate, gst_bp, description, opening_stock_milli, opening_date, reorder_level_milli, archived, created_at, updated_at) VALUES ('Toner', 'GOODS', '8443', 'Nos', 100000, 70000, 1800, '', 5000, 20544, 2000, 0, 1, 1)")
        db.close()
    }

    @Test fun migrate6To7AddsQuotationLink() {
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/6.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test-7", 6).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Shop', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at, state_code) VALUES (1, 'ABC', 'CLIENT', '', '', '', '', '', 0, 1, 1, '')")
            execSQL("INSERT INTO invoices (id, cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off, doc_type) VALUES (1, 1, 'SALE', 'INV/1', 1, 20544, 20560, 118000, 'Toner', '', 0, 1, 1, '27', 1, 'INVOICE')")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-7", 7, true, *Migrations.ALL)
        db.query("SELECT description, converted_invoice_id FROM invoices WHERE id = 1").use { c -> c.moveToFirst(); assertEquals("Toner", c.getString(0)); assertTrue(c.isNull(1)) }
        // quotations live in the same table with their own doc type and number series
        db.execSQL("INSERT INTO invoices (cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off, doc_type, converted_invoice_id) VALUES (1, 'SALE', 'QT/1', 1, 20540, 20554, 118000, '', '', 0, 1, 1, '27', 1, 'QUOTATION', 1)")
        db.close()
    }

    @Test fun migrate7To8AddsTransportAndSchedules() {
        val hasSchemas = runCatching { context().assets.open("com.cashbook.app.data.db.AppDatabase/7.json").close() }.isSuccess
        org.junit.Assume.assumeTrue("Room schemas only available in the debug variant", hasSchemas)
        helper.createDatabase("migration-test-8", 7).apply {
            execSQL("INSERT INTO cashbooks (id, name, description, opening_date, currency, created_at, updated_at, archived, is_sample) VALUES (1, 'Shop', '', 20544, 'INR', 1, 1, 0, 0)")
            execSQL("INSERT INTO parties (id, name, type, mobile, email, address, gstin, notes, archived, created_at, updated_at, state_code) VALUES (1, 'ABC', 'CLIENT', '', '', '', '', '', 0, 1, 1, '')")
            execSQL("INSERT INTO invoices (id, cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off, doc_type) VALUES (1, 1, 'SALE', 'DC/1', 1, 20544, 20544, 118000, 'Toner', '', 0, 1, 1, '27', 1, 'CHALLAN')")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-8", 8, true, *Migrations.ALL)
        db.query("SELECT description, vehicle_no, eway_bill_no, schedule_id FROM invoices WHERE id = 1").use { c ->
            c.moveToFirst(); assertEquals("Toner", c.getString(0)); assertEquals("", c.getString(1)); assertEquals("", c.getString(2)); assertTrue(c.isNull(3)) }
        db.execSQL("INSERT INTO invoices (id, cashbook_id, kind, number, party_id, issue_date, due_date, amount, description, notes, cancelled, created_at, updated_at, place_of_supply, round_off, doc_type) VALUES (2, 1, 'SALE', 'REC/1', 1, 20544, 20544, 118000, '', '', 0, 1, 1, '27', 1, 'TEMPLATE')")
        db.execSQL("INSERT INTO invoice_schedules (template_id, frequency, interval, start_date, next_index, due_days, active, created_at, updated_at) VALUES (2, 'MONTHLY', 1, 20544, 0, 15, 1, 1, 1)")
        db.close()
    }
}
