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

/** Payment reminders sent through WhatsApp's click-to-chat link. */
object Reminders {
    /**
     * International number for wa.me (digits only, country code first) from a mobile number as people type it:
     * "98765 43210", "+91-98765-43210", "098765 43210" → "919876543210". Other countries need the "+" prefix.
     * Returns null when it isn't a usable mobile number.
     */
    fun whatsappNumber(mobile: String): String? {
        val t = mobile.trim()
        val digits = t.filter { it.isDigit() }
        return when {
            t.startsWith("+") || t.startsWith("00") -> digits.removePrefix(if (t.startsWith("00")) "00" else "").takeIf { it.length in 8..15 && it[0] != '0' }
            digits.length == 10 && digits[0] in '6'..'9' -> "91$digits"
            digits.length == 11 && digits[0] == '0' && digits[1] in '6'..'9' -> "91" + digits.drop(1)
            digits.length == 12 && digits.startsWith("91") && digits[2] in '6'..'9' -> digits
            else -> null
        }
    }

    /** Click-to-chat link that opens WhatsApp on [number] with [text] typed in (the user still taps send). */
    fun whatsappLink(number: String, text: String) = "https://wa.me/$number?text=" + Upi.encode(text).replace("/", "%2F")
}
