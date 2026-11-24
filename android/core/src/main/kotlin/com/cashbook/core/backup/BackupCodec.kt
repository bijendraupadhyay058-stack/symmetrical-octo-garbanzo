package com.cashbook.core.backup

import com.cashbook.core.AccountType
import com.cashbook.core.CategoryKind
import com.cashbook.core.PartyType
import com.cashbook.core.PaymentMode
import com.cashbook.core.TxnType
import kotlinx.serialization.json.Json
import java.io.InputStream
import java.io.OutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/** A file to place inside the backup, opened lazily so large files are streamed. */
class AttachmentSource(val storedName: String, val open: () -> InputStream?)

data class DecodedBackup(val manifest: BackupManifest, val data: BackupData, val attachmentFiles: Set<String>)

/**
 * Reads and writes the encrypted backup archive:
 * encrypted( zip{ manifest.json, data.json, attachments/<storedName>... } ).
 */
object BackupCodec {
    val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = false }
    private const val MAX_JSON_BYTES = 200L * 1024 * 1024

    fun write(
        out: OutputStream,
        password: CharArray,
        manifest: BackupManifest,
        data: BackupData,
        attachments: List<AttachmentSource>,
        iterations: Int = BackupCrypto.DEFAULT_ITERATIONS,
    ) {
        val enc = BackupCrypto.encrypt(out, password, iterations)
        val zip = ZipOutputStream(enc)
        zip.putNextEntry(ZipEntry("manifest.json"))
        zip.write(json.encodeToString(BackupManifest.serializer(), manifest).toByteArray())
        zip.closeEntry()
        zip.putNextEntry(ZipEntry("data.json"))
        zip.write(json.encodeToString(BackupData.serializer(), data).toByteArray())
        zip.closeEntry()
        for (a in attachments) {
            val stream = a.open() ?: continue
            stream.use {
                zip.putNextEntry(ZipEntry("attachments/" + safeName(a.storedName)))
                it.copyTo(zip)
                zip.closeEntry()
            }
        }
        zip.finish()
        zip.close() // closes the encrypting stream, which writes the final authenticated chunk
    }

    /**
     * Decrypts and fully reads the backup. Attachment bytes are handed to [attachmentSink]
     * (stored name, stream) so the caller can stage them. The whole file is authenticated before
     * this returns, then the data is validated.
     */
    fun read(input: InputStream, password: CharArray, attachmentSink: (String, InputStream) -> Unit): DecodedBackup {
        val plain = BackupCrypto.decrypt(input, password)
        var manifest: BackupManifest? = null
        var data: BackupData? = null
        val files = HashSet<String>()
        try {
            val zip = ZipInputStream(plain)
            while (true) {
                val e = zip.nextEntry ?: break
                when {
                    e.name == "manifest.json" -> manifest = json.decodeFromString(BackupManifest.serializer(), readText(zip))
                    e.name == "data.json" -> data = json.decodeFromString(BackupData.serializer(), readText(zip))
                    e.name.startsWith("attachments/") && !e.isDirectory -> {
                        val name = e.name.removePrefix("attachments/")
                        if (name != safeName(name)) throw BackupException(BackupException.Reason.INVALID_DATA)
                        attachmentSink(name, zip)
                        files += name
                    }
                }
                zip.closeEntry()
            }
            // Drain so the final chunk is authenticated even if zip stops early.
            val buf = ByteArray(8192)
            while (plain.read(buf) != -1) { /* drain */ }
        } catch (e: BackupException) {
            throw e
        } catch (e: Exception) {
            throw BackupException(BackupException.Reason.INVALID_DATA, e)
        }
        val m = manifest ?: throw BackupException(BackupException.Reason.INVALID_DATA)
        val d = data ?: throw BackupException(BackupException.Reason.INVALID_DATA)
        if (m.format != "cashbook-backup") throw BackupException(BackupException.Reason.NOT_A_BACKUP)
        if (m.formatVersion > BACKUP_FORMAT_VERSION) throw BackupException(BackupException.Reason.UNSUPPORTED_VERSION)
        val problems = validate(d)
        if (problems.isNotEmpty()) throw BackupException(BackupException.Reason.INVALID_DATA, IllegalStateException(problems.take(5).joinToString("; ")))
        return DecodedBackup(m, d, files)
    }

    private fun readText(zip: ZipInputStream): String {
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(8192)
        var total = 0L
        while (true) {
            val n = zip.read(buf)
            if (n < 0) break
            total += n
            if (total > MAX_JSON_BYTES) throw BackupException(BackupException.Reason.INVALID_DATA)
            out.write(buf, 0, n)
        }
        return out.toString(Charsets.UTF_8.name())
    }

    fun safeName(name: String): String = name.replace(Regex("[^A-Za-z0-9._-]"), "_").trimStart('.').ifEmpty { "file" }

    /** Referential and value checks. Returns a list of human-readable problems (empty = valid). */
    fun validate(d: BackupData): List<String> {
        val p = ArrayList<String>()
        fun <T> dupes(list: List<T>, id: (T) -> Long, what: String) {
            val seen = HashSet<Long>()
            list.forEach { if (!seen.add(id(it))) p += "duplicate $what id ${id(it)}" }
        }
        dupes(d.cashbooks, { it.id }, "cashbook"); dupes(d.accounts, { it.id }, "account")
        dupes(d.categories, { it.id }, "category"); dupes(d.parties, { it.id }, "party")
        dupes(d.transactions, { it.id }, "transaction"); dupes(d.attachments, { it.id }, "attachment")
        val cb = d.cashbooks.map { it.id }.toSet()
        val acc = d.accounts.associateBy { it.id }
        val cat = d.categories.associateBy { it.id }
        val party = d.parties.map { it.id }.toSet()
        val txn = d.transactions.map { it.id }.toSet()
        d.cashbooks.forEach { if (it.name.isBlank()) p += "cashbook ${it.id} has no name" }
        d.accounts.forEach {
            if (it.cashbookId !in cb) p += "account ${it.id} has unknown cashbook"
            if (runCatching { AccountType.valueOf(it.type) }.isFailure) p += "account ${it.id} has invalid type"
            if (it.openingBalance < 0) p += "account ${it.id} has negative opening balance"
        }
        d.categories.forEach {
            if (runCatching { CategoryKind.valueOf(it.kind) }.isFailure) p += "category ${it.id} has invalid kind"
            if (it.parentId != null && it.parentId !in cat) p += "category ${it.id} has unknown parent"
        }
        d.parties.forEach { if (runCatching { PartyType.valueOf(it.type) }.isFailure) p += "party ${it.id} has invalid type" }
        d.transactions.forEach { t ->
            val type = runCatching { TxnType.valueOf(t.type) }.getOrNull()
            if (type == null) p += "transaction ${t.id} has invalid type"
            if (runCatching { PaymentMode.valueOf(t.paymentMode) }.isFailure) p += "transaction ${t.id} has invalid payment mode"
            if (t.amount <= 0) p += "transaction ${t.id} has invalid amount"
            if (t.cashbookId !in cb) p += "transaction ${t.id} has unknown cashbook"
            val a = acc[t.accountId]
            if (a == null || a.cashbookId != t.cashbookId) p += "transaction ${t.id} has invalid account"
            if (type == TxnType.TRANSFER) {
                val to = t.toAccountId?.let { acc[it] }
                if (to == null || to.cashbookId != t.cashbookId || t.toAccountId == t.accountId) p += "transfer ${t.id} has invalid destination"
            } else {
                if (t.toAccountId != null) p += "transaction ${t.id} must not have a destination account"
                if (t.categoryId != null && t.categoryId !in cat) p += "transaction ${t.id} has unknown category"
            }
            if (t.partyId != null && t.partyId !in party) p += "transaction ${t.id} has unknown party"
        }
        dupes(d.recurring, { it.id }, "recurring rule"); dupes(d.budgets, { it.id }, "budget")
        d.recurring.forEach { r ->
            val type = runCatching { TxnType.valueOf(r.type) }.getOrNull()
            if (type == null) p += "recurring ${r.id} has invalid type"
            if (runCatching { com.cashbook.core.Frequency.valueOf(r.frequency) }.isFailure) p += "recurring ${r.id} has invalid frequency"
            if (runCatching { PaymentMode.valueOf(r.paymentMode) }.isFailure) p += "recurring ${r.id} has invalid payment mode"
            if (r.amount <= 0 || r.interval < 1) p += "recurring ${r.id} has invalid amount or interval"
            if (r.cashbookId !in cb) p += "recurring ${r.id} has unknown cashbook"
            val a = acc[r.accountId]
            if (a == null || a.cashbookId != r.cashbookId) p += "recurring ${r.id} has invalid account"
            if (type == TxnType.TRANSFER) {
                val to = r.toAccountId?.let { acc[it] }
                if (to == null || to.cashbookId != r.cashbookId || r.toAccountId == r.accountId) p += "recurring ${r.id} has invalid destination"
            } else if (r.categoryId != null && r.categoryId !in cat) p += "recurring ${r.id} has unknown category"
            if (r.partyId != null && r.partyId !in party) p += "recurring ${r.id} has unknown party"
        }
        val budgetKeys = HashSet<Pair<Long, Long>>()
        d.budgets.forEach { b ->
            if (b.cashbookId !in cb || b.categoryId !in cat || b.monthlyAmount <= 0) p += "budget ${b.id} is invalid"
            if (!budgetKeys.add(b.cashbookId to b.categoryId)) p += "budget ${b.id} is a duplicate"
        }
        dupes(d.invoices, { it.id }, "invoice"); dupes(d.allocations, { it.id }, "allocation")
        val inv = d.invoices.associateBy { it.id }
        val txnById = d.transactions.associateBy { it.id }
        val invoiceKeys = HashSet<Triple<Long, String, String>>()
        d.invoices.forEach { i ->
            val kind = runCatching { com.cashbook.core.InvoiceKind.valueOf(i.kind) }.getOrNull()
            if (kind == null) p += "invoice ${i.id} has invalid kind"
            if (i.cashbookId !in cb) p += "invoice ${i.id} has unknown cashbook"
            if (i.partyId !in party) p += "invoice ${i.id} has unknown party"
            if (i.amount <= 0 || i.number.isBlank() || i.dueDate < i.issueDate) p += "invoice ${i.id} has invalid values"
            if (!invoiceKeys.add(Triple(i.cashbookId, i.kind + "/" + i.docType, i.number.trim().lowercase()))) p += "invoice ${i.id} has a duplicate number"
            val dt = runCatching { com.cashbook.core.DocType.valueOf(i.docType) }.getOrNull()
            if (dt == null) p += "invoice ${i.id} has invalid document type"
            if (dt != null && dt.isOffBook) {
                if (dt != com.cashbook.core.DocType.QUOTATION && i.kind != "SALE") p += "document ${i.id} must be a sale"
                val conv = i.convertedInvoiceId?.let { c -> d.invoices.firstOrNull { o -> o.id == c } }
                if (i.convertedInvoiceId != null && (conv == null || conv.docType != "INVOICE" || conv.cashbookId != i.cashbookId)) p += "quotation ${i.id} has an invalid converted invoice"
            }
            if (dt != null && dt.isNote) {
                val ref = i.refInvoiceId?.let { d.invoices.firstOrNull { o -> o.id == it } }
                if (ref == null || ref.docType != "INVOICE" || ref.cashbookId != i.cashbookId || ref.kind != i.kind) p += "note ${i.id} has an invalid original invoice"
            }
        }
        val perTxn = HashMap<Long, Long>()
        d.allocations.forEach { a ->
            val i = inv[a.invoiceId]; val t = txnById[a.transactionId]
            if (i == null || t == null) { p += "allocation ${a.id} has unknown invoice or entry"; return@forEach }
            // payment (income for sales, expense for purchases) or refund (the opposite)
            if (t.type == "TRANSFER" || i.docType != "INVOICE" || t.cashbookId != i.cashbookId || a.amount <= 0) p += "allocation ${a.id} is invalid"
            perTxn[t.id] = (perTxn[t.id] ?: 0) + a.amount
        }
        perTxn.forEach { (tid, sum) -> if (sum > (txnById[tid]?.amount ?: 0)) p += "entry $tid is allocated more than its amount" }
        dupes(d.invoiceItems, { it.id }, "invoice item"); dupes(d.catalog, { it.id }, "catalogue item"); dupes(d.stockAdjustments, { it.id }, "stock adjustment")
        val catalogIds = d.catalog.map { it.id }.toSet()
        d.catalog.forEach { c ->
            if (c.name.isBlank() || runCatching { com.cashbook.core.ItemKind.valueOf(c.kind) }.isFailure || c.saleRate < 0 || c.purchaseRate < 0 ||
                c.gstBp !in 0..10_000 || c.reorderLevelMilli < 0) p += "catalogue item ${c.id} is invalid"
        }
        d.stockAdjustments.forEach { if (it.itemId !in catalogIds || it.quantityMilli == 0L) p += "stock adjustment ${it.id} is invalid" }
        dupes(d.reconciliations, { it.id }, "reconciliation"); dupes(d.cashCounts, { it.id }, "cash count"); dupes(d.categoryRules, { it.id }, "category rule")
        val categoryIds = d.categories.map { it.id }.toSet()
        d.categoryRules.forEach { if (it.categoryId !in categoryIds || it.key.isBlank()) p += "category rule ${it.id} is invalid" }
        if (d.categoryRules.map { it.key }.distinct().size != d.categoryRules.size) p += "two category rules share a key"
        val accountIds = d.accounts.map { it.id }.toSet()
        d.reconciliations.forEach { if (it.accountId !in accountIds || it.entries < 0) p += "reconciliation ${it.id} is invalid" }
        d.cashCounts.forEach { c ->
            // the adjustment entry may since have been purged from the recycle bin, so it isn't required to exist
            if (c.accountId !in accountIds || c.counted < 0) p += "cash count ${c.id} is invalid"
        }
        dupes(d.invoiceSchedules, { it.id }, "invoice schedule")
        val scheduleIds = d.invoiceSchedules.map { it.id }.toSet()
        d.invoiceSchedules.forEach { s ->
            val t = d.invoices.firstOrNull { it.id == s.templateId }
            if (t == null || t.docType != "TEMPLATE" || runCatching { com.cashbook.core.Frequency.valueOf(s.frequency) }.isFailure || s.interval < 1 ||
                s.dueDays < 0 || (s.endDate != null && s.endDate < s.startDate)) p += "invoice schedule ${s.id} is invalid"
        }
        if (d.invoiceSchedules.map { it.templateId }.distinct().size != d.invoiceSchedules.size) p += "two schedules share a template"
        d.invoices.forEach { i -> if (i.scheduleId != null && i.scheduleId !in scheduleIds) p += "invoice ${i.id} has an unknown schedule" }
        d.invoiceItems.forEach { li -> if (li.itemId != null && li.itemId !in catalogIds) p += "invoice item ${li.id} has unknown catalogue item" }
        d.invoiceItems.forEach { li ->
            if (li.invoiceId !in inv) p += "invoice item ${li.id} has unknown invoice"
            if (li.quantityMilli <= 0 || li.rate < 0 || li.discountBp !in 0..10_000 || li.gstBp !in 0..10_000 || li.description.isBlank()) p += "invoice item ${li.id} is invalid"
        }
        d.attachments.forEach {
            if (it.transactionId !in txn) p += "attachment ${it.id} has unknown transaction"
            if (it.storedName != safeName(it.storedName)) p += "attachment ${it.id} has unsafe file name"
        }
        return p
    }
}
