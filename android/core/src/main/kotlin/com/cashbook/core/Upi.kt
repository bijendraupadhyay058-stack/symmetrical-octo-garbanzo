package com.cashbook.core

import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import com.google.zxing.qrcode.encoder.Encoder
import java.math.BigDecimal

/** UPI payment links ("upi://pay?…"), understood by every UPI app (BHIM, GPay, PhonePe, Paytm, bank apps). */
object Upi {
    // handle@psp, e.g. shop.name@okhdfcbank, 9876543210@ybl
    private val VPA = Regex("^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9.-]{1,63}$")

    fun isValidVpa(vpa: String) = VPA.matches(vpa.trim())

    /**
     * Payment link for [vpa]. [amountPaise] pre-fills the amount (the payer can't change it in most apps);
     * null leaves it for the payer to type. [note] (e.g. the invoice number) shows in their app and statement.
     */
    fun payUri(vpa: String, payeeName: String, amountPaise: Long?, note: String = ""): String {
        require(isValidVpa(vpa)) { "invalid UPI ID" }
        val params = buildList {
            add("pa" to vpa.trim())
            if (payeeName.isNotBlank()) add("pn" to payeeName.trim())
            if (amountPaise != null && amountPaise > 0) add("am" to BigDecimal.valueOf(amountPaise).movePointLeft(2).setScale(2).toPlainString())
            add("cu" to "INR")
            if (note.isNotBlank()) add("tn" to note.trim().take(80))
        }
        return "upi://pay?" + params.joinToString("&") { (k, v) -> k + "=" + encode(v) }
    }

    /** Percent-encodes as UTF-8, keeping unreserved characters and '@' / '/' (common in IDs and invoice numbers). */
    fun encode(v: String): String = buildString {
        v.toByteArray(Charsets.UTF_8).forEach { b ->
            val c = b.toInt() and 0xFF
            if (c < 0x80 && (c.toChar().isLetterOrDigit() || c.toChar() in "-._~@/")) append(c.toChar())
            else append('%').append("0123456789ABCDEF"[c shr 4]).append("0123456789ABCDEF"[c and 15])
        }
    }
}

/** A QR code as a square grid of modules (true = dark), without the quiet zone. */
class QrMatrix(val size: Int, private val dark: BooleanArray) {
    operator fun get(x: Int, y: Int) = dark[y * size + x]
}

object Qr {
    /** Encodes [text] (UTF-8) with error correction level M — readable even when printed small or slightly smudged. */
    fun encode(text: String): QrMatrix {
        val m = Encoder.encode(text, ErrorCorrectionLevel.M, mapOf(EncodeHintType.CHARACTER_SET to "UTF-8")).matrix
        val n = m.width
        return QrMatrix(n, BooleanArray(n * n) { m.get(it % n, it / n).toInt() == 1 })
    }
}
