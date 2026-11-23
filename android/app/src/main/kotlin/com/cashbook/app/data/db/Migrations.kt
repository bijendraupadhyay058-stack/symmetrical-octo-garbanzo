package com.cashbook.app.data.db

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * Schema upgrades. Each migration is verified against the exported Room schema in
 * `app/schemas/` by `MigrationTest`, so upgrading users never lose data.
 */
object Migrations {
    /** v1 → v2 (app 1.1): recurring rules, budgets, and the link from entries to their rule. */
    val MIGRATION_1_2 = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("ALTER TABLE `transactions` ADD COLUMN `recurring_id` INTEGER")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_transactions_recurring_id` ON `transactions` (`recurring_id`)")
            db.execSQL("CREATE TABLE IF NOT EXISTS `recurring` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `cashbook_id` INTEGER NOT NULL, `type` TEXT NOT NULL, `amount` INTEGER NOT NULL, `account_id` INTEGER NOT NULL, `to_account_id` INTEGER, `category_id` INTEGER, `party_id` INTEGER, `payment_mode` TEXT NOT NULL, `description` TEXT NOT NULL, `reference` TEXT NOT NULL, `notes` TEXT NOT NULL, `tags` TEXT NOT NULL, `frequency` TEXT NOT NULL, `interval` INTEGER NOT NULL, `start_date` INTEGER NOT NULL, `end_date` INTEGER, `next_index` INTEGER NOT NULL, `auto_post` INTEGER NOT NULL, `active` INTEGER NOT NULL, `created_at` INTEGER NOT NULL, `updated_at` INTEGER NOT NULL, FOREIGN KEY(`cashbook_id`) REFERENCES `cashbooks`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE , FOREIGN KEY(`account_id`) REFERENCES `accounts`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE , FOREIGN KEY(`to_account_id`) REFERENCES `accounts`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE , FOREIGN KEY(`category_id`) REFERENCES `categories`(`id`) ON UPDATE NO ACTION ON DELETE RESTRICT , FOREIGN KEY(`party_id`) REFERENCES `parties`(`id`) ON UPDATE NO ACTION ON DELETE RESTRICT )")
            listOf("cashbook_id", "account_id", "to_account_id", "category_id", "party_id").forEach {
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_recurring_$it` ON `recurring` (`$it`)")
            }
            db.execSQL("CREATE TABLE IF NOT EXISTS `budgets` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `cashbook_id` INTEGER NOT NULL, `category_id` INTEGER NOT NULL, `monthly_amount` INTEGER NOT NULL, `created_at` INTEGER NOT NULL, `updated_at` INTEGER NOT NULL, FOREIGN KEY(`cashbook_id`) REFERENCES `cashbooks`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE , FOREIGN KEY(`category_id`) REFERENCES `categories`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE )")
            db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_budgets_cashbook_id_category_id` ON `budgets` (`cashbook_id`, `category_id`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_budgets_category_id` ON `budgets` (`category_id`)")
        }
    }

    /** v2 → v3 (app 1.2): invoices / bills and the payments applied to them. */
    val MIGRATION_2_3 = object : Migration(2, 3) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("CREATE TABLE IF NOT EXISTS `invoices` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `cashbook_id` INTEGER NOT NULL, `kind` TEXT NOT NULL, `number` TEXT NOT NULL, `party_id` INTEGER NOT NULL, `issue_date` INTEGER NOT NULL, `due_date` INTEGER NOT NULL, `amount` INTEGER NOT NULL, `description` TEXT NOT NULL, `notes` TEXT NOT NULL, `cancelled` INTEGER NOT NULL, `created_at` INTEGER NOT NULL, `updated_at` INTEGER NOT NULL, FOREIGN KEY(`cashbook_id`) REFERENCES `cashbooks`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE , FOREIGN KEY(`party_id`) REFERENCES `parties`(`id`) ON UPDATE NO ACTION ON DELETE RESTRICT )")
            db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_invoices_cashbook_id_kind_number` ON `invoices` (`cashbook_id`, `kind`, `number`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_invoices_party_id` ON `invoices` (`party_id`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_invoices_due_date` ON `invoices` (`due_date`)")
            db.execSQL("CREATE TABLE IF NOT EXISTS `allocations` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `invoice_id` INTEGER NOT NULL, `transaction_id` INTEGER NOT NULL, `amount` INTEGER NOT NULL, `created_at` INTEGER NOT NULL, FOREIGN KEY(`invoice_id`) REFERENCES `invoices`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE , FOREIGN KEY(`transaction_id`) REFERENCES `transactions`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE )")
            db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_allocations_invoice_id_transaction_id` ON `allocations` (`invoice_id`, `transaction_id`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_allocations_transaction_id` ON `allocations` (`transaction_id`)")
        }
    }

    /** v3 → v4 (app 1.3): itemised GST invoices, place of supply, round-off and party state. */
    val MIGRATION_3_4 = object : Migration(3, 4) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("ALTER TABLE `parties` ADD COLUMN `state_code` TEXT NOT NULL DEFAULT ''")
            db.execSQL("ALTER TABLE `invoices` ADD COLUMN `place_of_supply` TEXT NOT NULL DEFAULT ''")
            db.execSQL("ALTER TABLE `invoices` ADD COLUMN `round_off` INTEGER NOT NULL DEFAULT 1")
            db.execSQL("CREATE TABLE IF NOT EXISTS `invoice_items` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `invoice_id` INTEGER NOT NULL, `position` INTEGER NOT NULL, `description` TEXT NOT NULL, `hsn` TEXT NOT NULL, `quantity_milli` INTEGER NOT NULL, `unit` TEXT NOT NULL, `rate` INTEGER NOT NULL, `discount_bp` INTEGER NOT NULL, `gst_bp` INTEGER NOT NULL, FOREIGN KEY(`invoice_id`) REFERENCES `invoices`(`id`) ON UPDATE NO ACTION ON DELETE CASCADE )")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_invoice_items_invoice_id` ON `invoice_items` (`invoice_id`)")
            // Fill party state from a valid-looking GSTIN prefix so existing parties get a default place of supply.
            db.execSQL("UPDATE `parties` SET `state_code` = substr(`gstin`, 1, 2) WHERE length(`gstin`) = 15 AND substr(`gstin`, 1, 2) GLOB '[0-9][0-9]'")
        }
    }

    val ALL: Array<Migration> = arrayOf(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
}
