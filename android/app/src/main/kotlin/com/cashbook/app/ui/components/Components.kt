package com.cashbook.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.CallMade
import androidx.compose.material.icons.automirrored.filled.CallReceived
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.cashbook.app.R
import com.cashbook.app.ui.theme.AmountStyle
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.TxnType
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

@Composable
fun typeColor(t: TxnType): Color = LocalFinanceColors.current.let {
    when (t) { TxnType.INCOME -> it.income; TxnType.EXPENSE -> it.expense; TxnType.TRANSFER -> it.transfer }
}

fun typeIcon(t: TxnType): ImageVector = when (t) {
    TxnType.INCOME -> Icons.AutoMirrored.Filled.CallReceived
    TxnType.EXPENSE -> Icons.AutoMirrored.Filled.CallMade
    TxnType.TRANSFER -> Icons.Filled.SwapHoriz
}

/** Amount with a +/− sign and colour; the sign keeps the meaning clear without colour. */
@Composable
fun AmountText(paise: Long, type: TxnType?, modifier: Modifier = Modifier, style: androidx.compose.ui.text.TextStyle = AmountStyle) {
    val f = LocalUiFormat.current
    val text = when (type) {
        TxnType.INCOME -> "+" + f.amount(paise)
        TxnType.EXPENSE -> "−" + f.amount(paise)
        else -> f.amount(paise)
    }
    val color = when (type) {
        null -> if (paise < 0) LocalFinanceColors.current.expense else MaterialTheme.colorScheme.onSurface
        else -> typeColor(type)
    }
    Text(text, modifier = modifier, style = style, color = color, maxLines = 1)
}

/** Icon + text label for a transaction type (never colour alone). */
@Composable
fun TypeBadge(type: TxnType, modifier: Modifier = Modifier) {
    val fc = LocalFinanceColors.current
    val bg = when (type) { TxnType.INCOME -> fc.incomeBg; TxnType.EXPENSE -> fc.expenseBg; TxnType.TRANSFER -> fc.transferBg }
    Row(modifier.background(bg, RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(typeIcon(type), null, Modifier.size(12.dp), tint = typeColor(type))
        Spacer(Modifier.width(4.dp))
        Text(txnTypeLabel(type), style = MaterialTheme.typography.labelSmall, color = typeColor(type))
    }
}

@Composable
fun TypeAvatar(type: TxnType, icon: ImageVector? = null) {
    val fc = LocalFinanceColors.current
    val bg = when (type) { TxnType.INCOME -> fc.incomeBg; TxnType.EXPENSE -> fc.expenseBg; TxnType.TRANSFER -> fc.transferBg }
    Box(Modifier.size(42.dp).background(bg, CircleShape), contentAlignment = Alignment.Center) {
        Icon(icon ?: typeIcon(type), contentDescription = txnTypeLabel(type), tint = typeColor(type), modifier = Modifier.size(22.dp))
    }
}

@Composable
fun SectionCard(title: String? = null, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Card(modifier.fillMaxWidth(), shape = MaterialTheme.shapes.medium,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)) {
        Column(Modifier.padding(16.dp)) {
            if (title != null) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    action?.invoke()
                }
                Spacer(Modifier.size(8.dp))
            }
            content()
        }
    }
}

@Composable
fun EmptyState(icon: ImageVector, text: String, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Column(modifier.fillMaxWidth().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(icon, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.outline)
        Spacer(Modifier.size(12.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (action != null) { Spacer(Modifier.size(12.dp)); action() }
    }
}

@Composable
fun ConfirmDialog(
    title: String, text: String, confirm: String, onConfirm: () -> Unit, onDismiss: () -> Unit, destructive: Boolean = false,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(onClick = { onConfirm(); onDismiss() }) {
                Text(confirm, color = if (destructive) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppScaffold(
    title: String,
    onBack: (() -> Unit)? = null,
    actions: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit = {},
    snackbar: SnackbarHostState? = null,
    floating: @Composable () -> Unit = {},
    bottomBar: @Composable () -> Unit = {},
    titleContent: (@Composable () -> Unit)? = null,
    content: @Composable (PaddingValues) -> Unit,
) {
    val fc = LocalFinanceColors.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = { titleContent?.invoke() ?: Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    if (onBack != null) IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) }
                },
                actions = actions,
                colors = TopAppBarDefaults.topAppBarColors(containerColor = fc.header, titleContentColor = fc.onHeader,
                    navigationIconContentColor = fc.onHeader, actionIconContentColor = fc.onHeader),
            )
        },
        snackbarHost = { if (snackbar != null) SnackbarHost(snackbar) },
        floatingActionButton = floating,
        bottomBar = bottomBar,
        containerColor = MaterialTheme.colorScheme.background,
        content = content,
    )
}

/** Date field that opens a Material date picker. Dates are always displayed in the chosen format. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DateField(label: String, date: LocalDate, onChange: (LocalDate) -> Unit, modifier: Modifier = Modifier, isError: Boolean = false, supporting: String? = null) {
    var open by remember { mutableStateOf(false) }
    val f = LocalUiFormat.current
    Box(modifier) {
        OutlinedTextField(
            value = f.date(date), onValueChange = {}, readOnly = true, label = { Text(label) },
            trailingIcon = { Icon(Icons.Filled.CalendarMonth, null) }, isError = isError,
            supportingText = supporting?.let { { Text(it) } },
            modifier = Modifier.fillMaxWidth(),
        )
        Box(Modifier.matchParentSize().clickable(onClickLabel = label) { open = true })
    }
    if (open) {
        val state = rememberDatePickerState(initialSelectedDateMillis = date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate()) }
                    open = false
                }) { Text(stringResource(R.string.ok)) }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text(stringResource(R.string.cancel)) } },
        ) { DatePicker(state = state) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun <T> DropdownField(label: String, options: List<T>, selected: T?, labelOf: @Composable (T) -> String, onSelect: (T) -> Unit,
                      modifier: Modifier = Modifier, isError: Boolean = false, supporting: String? = null, enabled: Boolean = true) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { if (enabled) expanded = it }, modifier = modifier) {
        OutlinedTextField(
            value = selected?.let { labelOf(it) } ?: "", onValueChange = {}, readOnly = true, label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) }, isError = isError, enabled = enabled,
            supportingText = supporting?.let { { Text(it) } },
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { o -> DropdownMenuItem(text = { Text(labelOf(o)) }, onClick = { onSelect(o); expanded = false }) }
        }
    }
}

@Composable
fun MoneyField(value: String, onChange: (String) -> Unit, label: String, modifier: Modifier = Modifier, error: String? = null, imeDone: Boolean = false) {
    OutlinedTextField(
        value = value,
        onValueChange = { v -> onChange(v.filter { it.isDigit() || it == '.' || it == ',' }.take(16)) },
        label = { Text(label) },
        prefix = { Text("₹ ") },
        isError = error != null,
        supportingText = error?.let { { Text(it) } },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
fun SwitchRow(title: String, checked: Boolean, onChange: (Boolean) -> Unit, subtitle: String? = null, enabled: Boolean = true) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = subtitle?.let { { Text(it) } },
        trailingContent = { Switch(checked = checked, onCheckedChange = onChange, enabled = enabled) },
        modifier = Modifier.clickable(enabled = enabled) { onChange(!checked) }.semantics { contentDescription = title },
    )
}

@Composable
fun NavRow(title: String, icon: ImageVector, subtitle: String? = null, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = subtitle?.let { { Text(it, maxLines = 2, overflow = TextOverflow.Ellipsis) } },
        leadingContent = { Icon(icon, null, tint = MaterialTheme.colorScheme.primary) },
        modifier = Modifier.clickable(onClick = onClick),
    )
}

/** Field that looks like a dropdown and opens a searchable picker. */
@Composable
fun PickerField(label: String, value: String, onClick: () -> Unit, modifier: Modifier = Modifier, isError: Boolean = false, supporting: String? = null, leading: ImageVector? = null) {
    Box(modifier) {
        OutlinedTextField(
            value = value, onValueChange = {}, readOnly = true, label = { Text(label) }, isError = isError,
            leadingIcon = leading?.let { { Icon(it, null) } },
            trailingIcon = { Icon(Icons.Filled.ArrowDropDown, null) },
            supportingText = supporting?.let { { Text(it) } },
            modifier = Modifier.fillMaxWidth(),
        )
        Box(Modifier.matchParentSize().clickable(onClickLabel = label, onClick = onClick))
    }
}

data class PickItem(val id: Long, val title: String, val subtitle: String = "", val icon: ImageVector? = null, val indent: Boolean = false)

/** Searchable bottom-sheet picker with an optional "create new" action. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchPickerSheet(
    title: String, items: List<PickItem>, onPick: (PickItem?) -> Unit, onDismiss: () -> Unit,
    createLabel: String? = null, onCreate: ((String) -> Unit)? = null, allowNone: String? = null,
) {
    var query by rememberSaveable { mutableStateOf("") }
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.size(8.dp))
            OutlinedTextField(query, { query = it }, leadingIcon = { Icon(Icons.Filled.Search, null) },
                placeholder = { Text(stringResource(R.string.search)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
        }
        val filtered = items.filter { query.isBlank() || it.title.contains(query, true) || it.subtitle.contains(query, true) }
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 520.dp)) {
            if (onCreate != null && createLabel != null) item {
                ListItem(
                    headlineContent = { Text(if (query.isBlank()) createLabel else "$createLabel: \"${query.trim()}\"") },
                    leadingContent = { Icon(Icons.Filled.Add, null, tint = MaterialTheme.colorScheme.primary) },
                    modifier = Modifier.clickable { onCreate(query.trim()) },
                )
                HorizontalDivider()
            }
            if (allowNone != null) item {
                ListItem(headlineContent = { Text(allowNone) }, modifier = Modifier.clickable { onPick(null) })
            }
            items(filtered, key = { it.id }) { it ->
                ListItem(
                    headlineContent = { Text(it.title) },
                    supportingContent = if (it.subtitle.isNotBlank()) ({ Text(it.subtitle) }) else null,
                    leadingContent = it.icon?.let { ic -> { Icon(ic, null, tint = MaterialTheme.colorScheme.primary) } },
                    modifier = Modifier.clickable { onPick(it) }.padding(start = if (it.indent) 24.dp else 0.dp),
                )
            }
            item { Spacer(Modifier.size(24.dp)) }
        }
    }
}

@Composable
fun InfoBanner(text: String, modifier: Modifier = Modifier, icon: ImageVector? = null, color: Color = MaterialTheme.colorScheme.secondaryContainer) {
    Surface(color = color, shape = MaterialTheme.shapes.small, modifier = modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (icon != null) { Icon(icon, null, Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)) }
            Text(text, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
fun FullScreenMessage(text: String, content: @Composable ColumnScope.() -> Unit = {}) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(24.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.size(16.dp))
        content()
    }
}
