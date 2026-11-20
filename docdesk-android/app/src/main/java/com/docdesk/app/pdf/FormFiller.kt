package com.docdesk.app.pdf

import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDCheckBox
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDChoice
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDNonTerminalField
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDField
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDRadioButton
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDSignatureField
import com.tom_roush.pdfbox.pdmodel.interactive.form.PDTextField

enum class FieldKind { TEXT, CHECKBOX, RADIO, CHOICE, SIGNATURE, OTHER }

data class FormField(
    val name: String,
    val label: String,
    val kind: FieldKind,
    val value: String,
    val options: List<String>,
    val readOnly: Boolean,
    val multiline: Boolean,
    val page: Int?,
)

/** Reads and fills interactive (AcroForm) PDF form fields. */
object FormFiller {
    fun read(doc: PDDocument): List<FormField> {
        val form = doc.documentCatalog.acroForm ?: return emptyList()
        val out = mutableListOf<FormField>()
        fun pageOf(f: PDField): Int? = f.widgets.firstOrNull()?.page?.let { p -> doc.pages.indexOf(p).takeIf { it >= 0 } }
        fun visit(f: PDField) {
            if (f is PDNonTerminalField) { f.children.forEach { visit(it) }; return }
            val label = f.alternateFieldName?.takeIf { it.isNotBlank() } ?: f.partialName ?: f.fullyQualifiedName
            val (kind, opts) = when (f) {
                is PDTextField -> FieldKind.TEXT to emptyList()
                is PDCheckBox -> FieldKind.CHECKBOX to emptyList()
                is PDRadioButton -> FieldKind.RADIO to f.exportValues.ifEmpty { f.onValues.toList() }
                is PDChoice -> FieldKind.CHOICE to f.optionsDisplayValues.ifEmpty { f.options }
                is PDSignatureField -> FieldKind.SIGNATURE to emptyList()
                else -> FieldKind.OTHER to emptyList()
            }
            val value = when (f) { is PDCheckBox -> if (f.isChecked) "true" else "false"; else -> runCatching { f.valueAsString }.getOrDefault("") }
            out.add(FormField(f.fullyQualifiedName, label, kind, value, opts, f.isReadOnly, (f as? PDTextField)?.isMultiline == true, pageOf(f)))
        }
        form.fields.forEach { visit(it) }
        return out
    }

    data class FillResult(val filled: Int, val failed: List<String>)

    /** Applies [values] (field name → value; checkboxes use "true"/"false"). */
    fun fill(doc: PDDocument, values: Map<String, String>, flatten: Boolean): FillResult {
        val form = doc.documentCatalog.acroForm ?: return FillResult(0, emptyList())
        form.needAppearances = false
        var filled = 0
        val failed = mutableListOf<String>()
        for ((name, v) in values) {
            val f = form.getField(name) ?: continue
            try {
                when (f) {
                    is PDCheckBox -> if (v == "true") f.check() else f.unCheck()
                    else -> f.setValue(v)
                }
                filled++
            } catch (e: Exception) {
                // Typically characters the field's font cannot encode (e.g. Hindi in a Helvetica field).
                failed.add(f.alternateFieldName ?: f.partialName ?: name)
            }
        }
        runCatching { form.refreshAppearances() }
        if (flatten) form.flatten()
        return FillResult(filled, failed)
    }
}
