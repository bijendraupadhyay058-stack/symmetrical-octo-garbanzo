package com.docdesk.app.ui.edit

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.docdesk.app.ui.components.CheckRow
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Change a line of existing text (covers the old line and places new text in the same spot). */
@Composable
fun EditTextDialog(original: String, sizePt: Float, bold: Boolean, onDismiss: () -> Unit, onConfirm: (String, Float, Boolean) -> Unit) {
    var text by remember { mutableStateOf(original) }
    var size by remember { mutableFloatStateOf(sizePt.coerceIn(5f, 48f)) }
    var isBold by remember { mutableStateOf(bold) }
    AlertDialog(
        onDismissRequest = onDismiss, title = { Text("Edit text") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth(), label = { Text("New text") })
                Text("Size ${"%.1f".format(size)} pt (original ${"%.1f".format(sizePt)})", style = MaterialTheme.typography.bodySmall)
                Slider(size, { size = it }, valueRange = 5f..48f, modifier = Modifier.semantics { contentDescription = "Text size" })
                CheckRow("Bold", isBold) { isBold = it }
                Text("Leave empty to remove the line. Non-English characters are added as an image.", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { TextButton(onClick = { onConfirm(text, size, isBold) }) { Text("Replace") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private val presets = listOf("PAID", "APPROVED", "RECEIVED", "VERIFIED", "REJECTED", "DRAFT", "CONFIDENTIAL", "ORIGINAL", "COPY", "FOR REVIEW")
private val stampColors = listOf(0xFFC62828.toInt() to "Red", 0xFF2E7D32.toInt() to "Green", 0xFF1E4FA3.toInt() to "Blue", 0xFF424242.toInt() to "Grey")

@Composable
fun StampDialog(onDismiss: () -> Unit, onConfirm: (String, String?, Int) -> Unit) {
    var label by remember { mutableStateOf("PAID") }
    var custom by remember { mutableStateOf("") }
    var withDate by remember { mutableStateOf(true) }
    var color by remember { mutableStateOf(stampColors[0].first) }
    val date = LocalDate.now().format(DateTimeFormatter.ofPattern("dd-MM-yyyy"))
    AlertDialog(
        onDismissRequest = onDismiss, title = { Text("Add stamp") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    presets.forEach { p -> FilterChip(selected = label == p && custom.isBlank(), onClick = { label = p; custom = "" }, label = { Text(p) }) }
                }
                OutlinedTextField(custom, { custom = it.uppercase().take(24) }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Or your own text") })
                CheckRow("Add date ($date)", withDate) { withDate = it }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    stampColors.forEach { (c, name) ->
                        Surface(onClick = { color = c }, shape = CircleShape, color = Color(c),
                            border = if (c == color) androidx.compose.foundation.BorderStroke(3.dp, MaterialTheme.colorScheme.onSurface) else null,
                            modifier = Modifier.size(36.dp).semantics { contentDescription = "$name" + if (c == color) ", selected" else "" }) {}
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onConfirm(custom.ifBlank { label }, if (withDate) date else null, color) }) { Text("Place stamp") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
