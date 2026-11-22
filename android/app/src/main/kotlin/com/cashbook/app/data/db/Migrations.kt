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

    val ALL: Array<Migration> = arrayOf(MIGRATION_1_2)
}
