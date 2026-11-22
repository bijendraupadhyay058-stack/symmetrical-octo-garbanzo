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
}
