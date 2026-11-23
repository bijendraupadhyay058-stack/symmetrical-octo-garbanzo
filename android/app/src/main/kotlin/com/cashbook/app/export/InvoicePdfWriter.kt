package com.cashbook.app.export

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import com.cashbook.core.AmountInWords
import com.cashbook.core.DateFormatOption
import com.cashbook.core.Gst
import com.cashbook.core.GstCalc
import com.cashbook.core.InvoiceBalance
import com.cashbook.core.InvoiceItem
import com.cashbook.core.InvoiceTotals
import com.cashbook.core.MoneyFormatter
import com.cashbook.core.PartyInfo
import com.cashbook.core.backup.BusinessProfileDto
import java.io.OutputStream

/**
 * A4 tax invoice: seller and buyer blocks, line items (headings repeated on every page), GST summary
 * by rate, totals with round-off, amount in words, payment details, terms and signature.
 * Without line items it prints a simple one-line invoice.
 */
class InvoicePdfWriter(private val money: MoneyFormatter, private val dates: DateFormatOption, private val s: Strings) {

    data class Strings(
        val taxInvoice: String, val invoice: String, val invoiceNo: String, val invoiceDate: String, val dueDate: String, val placeOfSupply: String,
        val billTo: String, val gstin: String, val state: String, val phone: String, val sr: String, val description: String, val hsn: String,
        val qty: String, val rate: String, val discount: String, val taxable: String, val gstRate: String, val amount: String, val taxSummary: String,
        val cgst: String, val sgst: String, val igst: String, val totalTax: String, val roundOff: String, val grandTotal: String, val paid: String,
        val balanceDue: String, val amountInWords: String, val paymentDetails: String, val bank: String, val accountName: String, val accountNo: String,
        val ifsc: String, val upi: String, val terms: String, val forBusiness: String, val authorisedSignatory: String, val page: String,
        val generatedBy: String, val reverseNote: String,
        val creditNote: String = "CREDIT NOTE", val debitNote: String = "DEBIT NOTE", val originalInvoice: String = "Against invoice",
        val noteNo: String = "Note no.", val noteDate: String = "Note date",
    )

    private val navy = Color.rgb(0x1A, 0x2B, 0x5C)
    private val grey = Color.rgb(0x5F, 0x66, 0x73)
    private val light = Color.rgb(0xEE, 0xF1, 0xF7)
    private fun p(size: Float, bold: Boolean = false, color: Int = Color.BLACK) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = size; this.color = color; typeface = Typeface.create(Typeface.DEFAULT, if (bold) Typeface.BOLD else Typeface.NORMAL)
    }
    private val pName = p(15f, true, navy); private val pTitle = p(14f, true, navy); private val pText = p(8.5f); private val pBold = p(8.5f, true)
    private val pSmall = p(7.5f, false, grey); private val pHead = p(8f, true, Color.WHITE); private val pTotal = p(10f, true)
    private val fill = Paint().apply { style = Paint.Style.FILL }
    private val stroke = Paint().apply { style = Paint.Style.STROKE; strokeWidth = 0.6f; color = Color.rgb(0xC8, 0xCE, 0xDA) }

    private val W = 595; private val H = 842; private val M = 32f
    private val CW = W - 2 * M
    private val bottom = H - M - 20f

    class Pages { val pages = ArrayList<ArrayList<(Canvas) -> Unit>>() }

    /** Lays out all pages (page count is known before drawing so footers can show "Page x of y"). */
    /** Optional images printed on the document. */
    data class Branding(val logo: android.graphics.Bitmap? = null, val signature: android.graphics.Bitmap? = null)

    /** For a credit/debit note: the original invoice's number and date, printed under the title. */
    data class Reference(val number: String, val date: java.time.LocalDate)

    fun layout(b: InvoiceBalance, items: List<InvoiceItem>, seller: BusinessProfileDto, buyer: PartyInfo?, branding: Branding = Branding(),
               reference: Reference? = null): Pages {
        val inv = b.invoice
        val totals: InvoiceTotals? = if (items.isEmpty()) null else GstCalc.totals(items, GstCalc.isInterState(seller.stateCode, inv.placeOfSupply), inv.roundOff)
        val out = Pages()
        var ops = ArrayList<(Canvas) -> Unit>().also { out.pages += it }
        var y = M

        fun text(t: String, x: Float, yy: Float, paint: Paint, right: Boolean = false) {
            val tx = if (right) x - paint.measureText(t) else x
            ops += { c -> c.drawText(t, tx, yy, paint) }
        }
        fun wrap(t: String, paint: Paint, w: Float): List<String> {
            if (t.isBlank()) return emptyList()
            val lines = ArrayList<String>()
            t.split('\n').forEach { para ->
                var cur = ""
                para.split(' ').forEach { word ->
                    val cand = if (cur.isEmpty()) word else "$cur $word"
                    if (paint.measureText(cand) <= w) cur = cand else { if (cur.isNotEmpty()) lines += cur; cur = word }
                }
                if (cur.isNotEmpty()) lines += cur
            }
            return lines
        }
        fun newPage() { ops = ArrayList<(Canvas) -> Unit>().also { out.pages += it }; y = M
            text("${s.invoiceNo}: ${inv.number}", M, y + 8f, pSmall); y += 18f }
        fun ensure(h: Float) { if (y + h > bottom) newPage() }

        // ----- header -----
        val title = when (inv.docType) {
            com.cashbook.core.DocType.CREDIT_NOTE -> s.creditNote
            com.cashbook.core.DocType.DEBIT_NOTE -> s.debitNote
            else -> if (seller.gstin.isNotBlank() && totals != null) s.taxInvoice else s.invoice
        }
        branding.logo?.let { logo ->
            // logo fits a 140 × 46 pt box at the top left; the seller block starts below it
            val sc = minOf(46f / logo.height, 140f / logo.width)
            val w = logo.width * sc; val h = logo.height * sc; val yy = y
            ops += { c -> c.drawBitmap(logo, null, android.graphics.RectF(M, yy, M + w, yy + h), Paint(Paint.FILTER_BITMAP_FLAG)) }
            y += h + 6f
        }
        text(seller.name.ifBlank { "—" }, M, y + 14f, pName)
        text(title, M + CW, y + 14f, pTitle, right = true)
        y += 22f
        val sellerLines = buildList {
            addAll(wrap(seller.address, pText, CW * 0.55f))
            if (seller.gstin.isNotBlank()) add("${s.gstin}: ${seller.gstin}")
            if (seller.stateCode.isNotBlank()) add("${s.state}: ${Gst.stateLabel(seller.stateCode)}")
            listOf(seller.phone, seller.email).filter { it.isNotBlank() }.takeIf { it.isNotEmpty() }?.let { add(it.joinToString(" · ")) }
        }
        val meta = buildList {
            val isNote = inv.docType != com.cashbook.core.DocType.INVOICE
            add((if (isNote) s.noteNo else s.invoiceNo) to inv.number); add((if (isNote) s.noteDate else s.invoiceDate) to dates.format(inv.issueDate))
            if (inv.docType == com.cashbook.core.DocType.INVOICE) add(s.dueDate to dates.format(inv.dueDate))
            if (inv.placeOfSupply.isNotBlank()) add(s.placeOfSupply to Gst.stateLabel(inv.placeOfSupply))
            reference?.let { add(s.originalInvoice to "${it.number} (${dates.format(it.date)})") }
        }
        val startY = y
        sellerLines.forEach { text(it, M, y + 9f, pText); y += 11f }
        var my = startY
        meta.forEach { (k, v) -> text(k, M + CW * 0.62f, my + 9f, pSmall); text(v, M + CW, my + 9f, pBold, right = true); my += 12f }
        y = maxOf(y, my) + 8f
        run { val yy = y; ops += { c -> fill.color = navy; c.drawRect(M, yy, M + CW, yy + 1.5f, fill) } }
        y += 10f

        // ----- bill to -----
        text(s.billTo.uppercase(), M, y + 8f, pSmall); y += 12f
        text(buyer?.name ?: "", M, y + 10f, pBold); y += 13f
        buildList {
            addAll(wrap(buyer?.address ?: "", pText, CW * 0.6f))
            buyer?.gstin?.takeIf { it.isNotBlank() }?.let { add("${s.gstin}: $it") }
            buyer?.stateCode?.takeIf { it.isNotBlank() }?.let { add("${s.state}: ${Gst.stateLabel(it)}") }
            buyer?.mobile?.takeIf { it.isNotBlank() }?.let { add("${s.phone}: $it") }
        }.forEach { text(it, M, y + 9f, pText); y += 11f }
        y += 10f

        // ----- items table -----
        // widths sum to 1; amount columns are wide enough for crore values (₹1,25,00,000.00)
        val cols = floatArrayOf(0.04f, 0.27f, 0.09f, 0.09f, 0.11f, 0.06f, 0.13f, 0.06f, 0.15f).map { it * CW }
        val titles = listOf(s.sr, s.description, s.hsn, s.qty, s.rate, s.discount, s.taxable, s.gstRate, s.amount)
        val rightCols = setOf(3, 4, 5, 6, 7, 8)
        fun header() {
            val yy = y
            ops += { c -> fill.color = navy; c.drawRect(M, yy, M + CW, yy + 16f, fill) }
            var x = M
            titles.forEachIndexed { i, t ->
                text(t, if (i in rightCols) x + cols[i] - 3f else x + 3f, yy + 11f, pHead, right = i in rightCols); x += cols[i]
            }
            y += 16f
        }
        if (totals != null) {
            header()
            totals.lines.forEachIndexed { idx, l ->
                val it = l.item
                val desc = wrap(it.description, pText, cols[1] - 6f).ifEmpty { listOf("") }
                val h = desc.size * 10.5f + 6f
                if (y + h > bottom) { newPage(); header() }
                val vals = listOf((idx + 1).toString(), "", it.hsn, Gst.formatQuantity(it.quantityMilli) + (if (it.unit.isNotBlank()) " ${it.unit}" else ""),
                    money.format(it.rate), if (it.discountBp > 0) Gst.formatPercent(it.discountBp) + "%" else "", money.format(l.taxable), Gst.rateLabel(it.gstBp),
                    money.format(l.total))
                var x = M
                vals.forEachIndexed { i, v ->
                    if (i == 1) desc.forEachIndexed { li, ln -> text(ln, x + 3f, y + 10f + li * 10.5f, pText) }
                    else text(v, if (i in rightCols) x + cols[i] - 3f else x + 3f, y + 10f, pText, right = i in rightCols)
                    x += cols[i]
                }
                val yy = y + h
                ops += { c -> c.drawLine(M, yy, M + CW, yy, stroke) }
                y += h
            }
        } else {
            // simple invoice: one line with the description and amount
            val yy = y
            ops += { c -> fill.color = navy; c.drawRect(M, yy, M + CW, yy + 16f, fill) }
            text(s.description, M + 3f, yy + 11f, pHead); text(s.amount, M + CW - 3f, yy + 11f, pHead, right = true); y += 16f
            val desc = wrap(inv.description.ifBlank { inv.number }, pText, CW * 0.7f)
            desc.forEachIndexed { i, ln -> text(ln, M + 3f, y + 10f + i * 10.5f, pText) }
            text(money.format(inv.amount), M + CW - 3f, y + 10f, pText, right = true)
            y += desc.size.coerceAtLeast(1) * 10.5f + 6f
        }
        y += 10f

        // ----- GST summary by rate -----
        if (totals != null && totals.tax > 0) {
            ensure(30f + totals.breakup.size * 13f)
            text(s.taxSummary, M, y + 9f, pBold); y += 13f
            // only the columns that apply: CGST + SGST within the state, IGST across states
            val tw = CW * 0.78f
            val st = if (totals.interState) listOf(s.gstRate, s.taxable, s.igst, s.totalTax) else listOf(s.gstRate, s.taxable, s.cgst, s.sgst, s.totalTax)
            val sc = (if (totals.interState) listOf(0.16f, 0.30f, 0.27f, 0.27f) else listOf(0.13f, 0.24f, 0.21f, 0.21f, 0.21f)).map { it * tw }
            run { val yy = y; ops += { c -> fill.color = light; c.drawRect(M, yy, M + tw, yy + 13f, fill) } }
            var x = M
            st.forEachIndexed { i, t -> text(t, if (i == 0) x + 3f else x + sc[i] - 3f, y + 9.5f, pSmall, right = i > 0); x += sc[i] }
            y += 13f
            totals.breakup.forEach { r ->
                x = M
                val vals = if (totals.interState) listOf(Gst.rateLabel(r.gstBp), money.format(r.taxable), money.format(r.igst), money.format(r.tax))
                    else listOf(Gst.rateLabel(r.gstBp), money.format(r.taxable), money.format(r.cgst), money.format(r.sgst), money.format(r.tax))
                vals.forEachIndexed { i, v -> text(v, if (i == 0) x + 3f else x + sc[i] - 3f, y + 9.5f, pText, right = i > 0); x += sc[i] }
                y += 12f
            }
            y += 6f
        }

        // ----- totals -----
        val lines = buildList {
            if (totals != null) {
                add(s.taxable to totals.taxable)
                if (totals.cgst > 0) add(s.cgst to totals.cgst)
                if (totals.sgst > 0) add(s.sgst to totals.sgst)
                if (totals.igst > 0) add(s.igst to totals.igst)
                if (totals.roundOff != 0L) add(s.roundOff to totals.roundOff)
            }
        }
        ensure(lines.size * 12f + 60f)
        lines.forEach { (k, v) -> text(k, M + CW * 0.62f, y + 9f, pText); text(money.format(v), M + CW, y + 9f, pText, right = true); y += 12f }
        run { val yy = y; ops += { c -> fill.color = light; c.drawRect(M + CW * 0.6f, yy, M + CW, yy + 18f, fill) } }
        text(s.grandTotal, M + CW * 0.62f, y + 12.5f, pTotal); text(money.format(inv.amount), M + CW - 3f, y + 12.5f, pTotal, right = true)
        y += 22f
        if (b.paid > 0) {
            text(s.paid, M + CW * 0.62f, y + 9f, pText); text(money.format(b.paid), M + CW, y + 9f, pText, right = true); y += 12f
            text(s.balanceDue, M + CW * 0.62f, y + 9f, pBold); text(money.format(b.outstanding), M + CW, y + 9f, pBold, right = true); y += 14f
        }
        y += 4f
        val words = wrap("${s.amountInWords}: ${AmountInWords.rupees(inv.amount)}", pText, CW)
        ensure(words.size * 11f + 6f)
        words.forEach { text(it, M, y + 9f, pText); y += 11f }
        y += 10f

        // ----- payment details, terms, signature -----
        val pay = buildList {
            if (seller.bankName.isNotBlank()) add("${s.bank}: ${seller.bankName}")
            if (seller.accountName.isNotBlank()) add("${s.accountName}: ${seller.accountName}")
            if (seller.accountNumber.isNotBlank()) add("${s.accountNo}: ${seller.accountNumber}")
            if (seller.ifsc.isNotBlank()) add("${s.ifsc}: ${seller.ifsc}")
            if (seller.upiId.isNotBlank()) add("${s.upi}: ${seller.upiId}")
        }
        val terms = wrap(seller.terms, pSmall, CW * 0.55f)
        ensure(maxOf(pay.size * 11f + 14f + terms.size * 10f, 70f))
        val blockY = y
        if (pay.isNotEmpty()) { text(s.paymentDetails, M, y + 9f, pBold); y += 13f; pay.forEach { text(it, M, y + 9f, pText); y += 11f }; y += 6f }
        if (terms.isNotEmpty()) { text(s.terms, M, y + 9f, pBold); y += 12f; terms.forEach { text(it, M, y + 9f, pSmall); y += 10f } }
        val sigY = blockY
        text("${s.forBusiness} ${seller.name}".trim(), M + CW, sigY + 9f, pBold, right = true)
        branding.signature?.let { sig ->
            val sc = minOf(30f / sig.height, 120f / sig.width)
            val w = sig.width * sc; val h = sig.height * sc
            ops += { c -> c.drawBitmap(sig, null, android.graphics.RectF(M + CW - w, sigY + 14f, M + CW, sigY + 14f + h), Paint(Paint.FILTER_BITMAP_FLAG)) }
        }
        text(seller.signatory.ifBlank { " " }, M + CW, sigY + 48f, pText, right = true)
        run { val yy = sigY + 52f; ops += { c -> c.drawLine(M + CW * 0.68f, yy, M + CW, yy, stroke) } }
        text(s.authorisedSignatory, M + CW, sigY + 62f, pSmall, right = true)
        y = maxOf(y, sigY + 70f)
        return out
    }

    fun drawPage(c: Canvas, pages: Pages, index: Int) {
        c.drawColor(Color.WHITE)
        pages.pages[index].forEach { it(c) }
        c.drawLine(M, H - M - 8f, W - M, H - M - 8f, stroke)
        c.drawText(s.generatedBy, M, H - M + 4f, pSmall)
        val pn = s.page.format(index + 1, pages.pages.size)
        c.drawText(pn, W - M - pSmall.measureText(pn), H - M + 4f, pSmall)
    }

    fun write(b: InvoiceBalance, items: List<InvoiceItem>, seller: BusinessProfileDto, buyer: PartyInfo?, out: OutputStream,
              branding: Branding = Branding(), reference: Reference? = null) {
        val pages = layout(b, items, seller, buyer, branding, reference)
        val pdf = PdfDocument()
        try {
            pages.pages.indices.forEach { i ->
                val pg = pdf.startPage(PdfDocument.PageInfo.Builder(W, H, i + 1).create())
                drawPage(pg.canvas, pages, i)
                pdf.finishPage(pg)
            }
            pdf.writeTo(out)
        } finally { pdf.close() }
    }

    companion object { const val WIDTH = 595; const val HEIGHT = 842 }
}
