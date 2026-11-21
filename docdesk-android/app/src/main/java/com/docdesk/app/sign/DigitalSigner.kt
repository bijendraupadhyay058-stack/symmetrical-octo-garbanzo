package com.docdesk.app.sign

import com.docdesk.app.jobs.OperationFailed
import com.docdesk.core.PageTransform
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.PDPageContentStream
import com.tom_roush.pdfbox.pdmodel.font.PDType1Font
import com.tom_roush.pdfbox.pdmodel.interactive.digitalsignature.PDSignature
import com.tom_roush.pdfbox.pdmodel.interactive.digitalsignature.SignatureInterface
import com.tom_roush.pdfbox.util.Matrix
import java.io.File
import java.io.InputStream
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.cert.X509Certificate
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import org.bouncycastle.asn1.x500.X500NameBuilder
import org.bouncycastle.asn1.x500.style.BCStyle
import org.bouncycastle.cert.jcajce.JcaCertStore
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder
import org.bouncycastle.cms.CMSProcessableByteArray
import org.bouncycastle.cms.CMSSignedData
import org.bouncycastle.cms.CMSSignedDataGenerator
import org.bouncycastle.cms.jcajce.JcaSignerInfoGeneratorBuilder
import org.bouncycastle.cms.jcajce.JcaSimpleSignerInfoVerifierBuilder
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder
import org.bouncycastle.operator.jcajce.JcaDigestCalculatorProviderBuilder

data class Identity(val key: PrivateKey, val chain: List<X509Certificate>) {
    val cert get() = chain.first()
    val commonName: String get() = cert.subjectX500Principal.name.split(",").firstOrNull { it.trim().startsWith("CN=") }?.substringAfter("CN=") ?: cert.subjectX500Principal.name
    val selfSigned get() = cert.subjectX500Principal == cert.issuerX500Principal
}

data class SignOptions(val reason: String, val location: String, val visible: Boolean, val page: Int, val bottomRight: Boolean = true)

data class SignatureReport(
    val signer: String,
    val date: Date?,
    val reason: String?,
    val location: String?,
    val intact: Boolean,
    val coversWholeFile: Boolean,
    val selfSigned: Boolean,
    val issuer: String,
    val certValidAtSigning: Boolean?,
    val problem: String?,
)

/**
 * Certificate-based (PKCS#7 / CAdES-style detached) PDF signatures, verifiable in Adobe Acrobat.
 * Keys come from a .pfx/.p12 file chosen by the user or a personal certificate created in the
 * app; the certificate password is asked each time and never stored.
 */
object DigitalSigner {
    /** "CN=Asha Rao,O=ACME" → "Asha Rao (ACME)" for display. */
    fun displayName(dn: String): String {
        val parts = dn.split(",").map { it.trim() }
        val cn = parts.firstOrNull { it.startsWith("CN=") }?.substringAfter("CN=")
        val o = parts.firstOrNull { it.startsWith("O=") }?.substringAfter("O=")
        return listOfNotNull(cn, o?.let { "($it)" }).joinToString(" ").ifBlank { dn }
    }

    fun loadIdentity(p12: File, password: CharArray): Identity {
        val ks = KeyStore.getInstance("PKCS12")
        try { p12.inputStream().use { ks.load(it, password) } } catch (e: Exception) {
            throw OperationFailed(if (e.message?.contains("password", true) == true || e.cause is javax.crypto.BadPaddingException) "Wrong certificate password." else "This certificate file could not be read (${e.javaClass.simpleName}). Use a .pfx or .p12 file.")
        }
        val alias = ks.aliases().toList().firstOrNull { ks.isKeyEntry(it) } ?: throw OperationFailed("The certificate file contains no private key, so it cannot sign.")
        val key = ks.getKey(alias, password) as? PrivateKey ?: throw OperationFailed("The private key could not be opened.")
        val chain = ks.getCertificateChain(alias)?.map { it as X509Certificate } ?: throw OperationFailed("The certificate chain is missing.")
        return Identity(key, chain)
    }

    /** Creates a personal self-signed certificate (RSA 2048, SHA-256, 3 years) saved as a password-protected .p12. */
    fun createSelfSigned(out: File, name: String, email: String, organisation: String, password: CharArray) {
        val kp = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
        val subject = X500NameBuilder(BCStyle.INSTANCE).apply {
            addRDN(BCStyle.CN, name)
            if (organisation.isNotBlank()) addRDN(BCStyle.O, organisation)
            if (email.isNotBlank()) addRDN(BCStyle.EmailAddress, email)
        }.build()
        val now = Date()
        val until = Calendar.getInstance().apply { add(Calendar.YEAR, 3) }.time
        val builder = JcaX509v3CertificateBuilder(subject, BigInteger.valueOf(System.currentTimeMillis()), now, until, subject, kp.public)
        val holder = builder.build(JcaContentSignerBuilder("SHA256withRSA").build(kp.private))
        val cert = JcaX509CertificateConverter().getCertificate(holder)
        val ks = KeyStore.getInstance("PKCS12").apply { load(null, null) }
        ks.setKeyEntry("docdesk", kp.private, password, arrayOf(cert))
        out.outputStream().use { ks.store(it, password) }
    }

    private class Signer(private val id: Identity) : SignatureInterface {
        override fun sign(content: InputStream): ByteArray {
            val gen = CMSSignedDataGenerator()
            val signer = JcaContentSignerBuilder(if (id.key.algorithm == "EC") "SHA256withECDSA" else "SHA256withRSA").build(id.key)
            gen.addSignerInfoGenerator(JcaSignerInfoGeneratorBuilder(JcaDigestCalculatorProviderBuilder().build()).build(signer, id.cert))
            gen.addCertificates(JcaCertStore(id.chain))
            return gen.generate(CMSProcessableByteArray(content.readBytes()), false).encoded
        }
    }

    /**
     * Signs [source] into [out]. If [opts].visible, a signature box is first drawn on the page
     * (full save), then the signature is added as an incremental update so earlier signatures,
     * if any, stay valid (in that case no box is drawn, to avoid invalidating them).
     */
    fun sign(source: File, out: File, id: Identity, opts: SignOptions, work: File): List<String> {
        val notes = mutableListOf<String>()
        var toSign = source
        PDDocument.load(source).use { doc ->
            if (doc.isEncrypted) throw OperationFailed("Remove the password protection before signing (sign first, then protect).")
            val alreadySigned = doc.signatureDictionaries.isNotEmpty()
            if (opts.visible && alreadySigned) notes.add("The PDF already has a signature, so no visible box was drawn (drawing it would invalidate the earlier signature). The new signature is shown in the signature panel.")
            if (opts.visible && !alreadySigned) {
                drawBox(doc, id, opts)
                val tmp = File.createTempFile("sig", ".pdf", work)
                doc.save(tmp)
                toSign = tmp
            }
        }
        try {
            PDDocument.load(toSign).use { doc ->
                val sig = PDSignature().apply {
                    setFilter(PDSignature.FILTER_ADOBE_PPKLITE)
                    setSubFilter(PDSignature.SUBFILTER_ADBE_PKCS7_DETACHED)
                    name = id.commonName
                    if (opts.reason.isNotBlank()) reason = opts.reason
                    if (opts.location.isNotBlank()) location = opts.location
                    signDate = Calendar.getInstance()
                }
                doc.addSignature(sig, Signer(id))
                val part = File(out.parentFile, out.name + ".part")
                part.outputStream().use { doc.saveIncremental(it) }
                if (!part.renameTo(out)) throw java.io.IOException("Could not save the signed PDF")
            }
        } finally { if (toSign !== source) toSign.delete() }
        if (id.selfSigned) notes.add("Signed with a personal (self-signed) certificate. Adobe Acrobat will show the signature as valid in integrity but with \"identity unknown\" until the recipient trusts your certificate. For legally recognised signatures in India use a Class 3 DSC from a licensed Certifying Authority exported as .pfx where permitted.")
        notes.add("Do not edit the signed PDF afterwards – any change after signing is reported as a modification.")
        return notes
    }

    private fun drawBox(doc: PDDocument, id: Identity, o: SignOptions) {
        val page = doc.getPage(o.page.coerceIn(0, doc.numberOfPages - 1))
        val box = page.cropBox
        val (dw, _) = PageTransform.displaySize(box.width, box.height, page.rotation)
        val t = PageTransform.displayToPdf(box.lowerLeftX, box.lowerLeftY, box.width, box.height, page.rotation)
        val w = 190f; val h = 58f
        val x = if (o.bottomRight) dw - w - 30f else 30f; val y = 30f
        val date = SimpleDateFormat("dd-MM-yyyy HH:mm Z", Locale.ENGLISH).format(Date())
        fun latin(s: String) = s.filter { it.code in 32..255 }
        PDPageContentStream(doc, page, PDPageContentStream.AppendMode.APPEND, true, true).use { cs ->
            cs.saveGraphicsState()
            cs.transform(Matrix(t.a, t.b, t.c, t.d, t.e, t.f))
            cs.setStrokingColor(0.12f, 0.31f, 0.64f); cs.setLineWidth(1.2f)
            cs.addRect(x, y, w, h); cs.stroke()
            cs.setNonStrokingColor(0.12f, 0.31f, 0.64f)
            val lines = listOf(
                PDType1Font.HELVETICA_BOLD to "Digitally signed by",
                PDType1Font.HELVETICA_BOLD to latin(id.commonName).take(38),
                PDType1Font.HELVETICA to "Date: $date",
                PDType1Font.HELVETICA to latin(listOf(o.reason, o.location).filter { it.isNotBlank() }.joinToString(" · ")).take(45),
            )
            lines.forEachIndexed { i, (f, s) ->
                if (s.isBlank()) return@forEachIndexed
                cs.beginText(); cs.setFont(f, if (i == 1) 10f else 8f); cs.newLineAtOffset(x + 6f, y + h - 13f - i * 12f); cs.showText(s); cs.endText()
            }
            cs.restoreGraphicsState()
        }
    }

    /** Checks every signature: integrity (CMS), whether later changes were made, certificate details. */
    fun verify(file: File): List<SignatureReport> {
        val bytes = file.readBytes()
        val out = mutableListOf<SignatureReport>()
        PDDocument.load(file).use { doc ->
            for (sig in doc.signatureDictionaries) {
                try {
                    val range = sig.byteRange
                    val contents = sig.getContents(bytes)
                    val signed = sig.getSignedContent(bytes)
                    val cms = CMSSignedData(CMSProcessableByteArray(signed), contents)
                    val info = cms.signerInfos.signers.first()
                    @Suppress("UNCHECKED_CAST")
                    val holder = cms.certificates.getMatches(info.sid as org.bouncycastle.util.Selector<org.bouncycastle.cert.X509CertificateHolder>).firstOrNull()
                    val cert = holder?.let { JcaX509CertificateConverter().getCertificate(it) }
                    val intact = cert != null && info.verify(JcaSimpleSignerInfoVerifierBuilder().build(cert))
                    val covers = range.size == 4 && range[2].toLong() + range[3] == bytes.size.toLong()
                    val signDate = sig.signDate?.time
                    val validAt = cert?.let { c -> signDate?.let { d -> !d.before(c.notBefore) && !d.after(c.notAfter) } }
                    out.add(SignatureReport(
                        signer = sig.name ?: cert?.subjectX500Principal?.name ?: "Unknown",
                        date = signDate, reason = sig.reason, location = sig.location,
                        intact = intact, coversWholeFile = covers,
                        selfSigned = cert != null && cert.subjectX500Principal == cert.issuerX500Principal,
                        issuer = cert?.issuerX500Principal?.name?.let { displayName(it) } ?: "Unknown", certValidAtSigning = validAt, problem = null,
                    ))
                } catch (e: Exception) {
                    out.add(SignatureReport(sig.name ?: "Unknown", sig.signDate?.time, sig.reason, sig.location, false, false, false, "", null, "Could not check this signature (${e.javaClass.simpleName}); its format may be unsupported."))
                }
            }
        }
        return out
    }
}
